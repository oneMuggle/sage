"""
Episodic Memory - 情景记忆模块
基于 SQLite 存储对话历史和事件序列

中文支持：搜索时使用 jieba 分词，将查询拆分为多个词，
用多个 LIKE 条件 OR 连接，提升中文检索质量。
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional

from backend.memory.chinese_tokenizer import tokenize


class EpisodicMemory:
    """
    情景记忆 - 管理事件序列和经历

    特性:
    - SQLite 持久化存储
    - 支持重要性评分 (1-10)
    - 支持标签系统
    - 访问计数和 TTL 支持
    """

    def __init__(self, db):
        """
        初始化情景记忆

        Args:
            db: Database 实例
        """
        self.db = db

    def save(
        self,
        content: str,
        importance: int = 5,
        metadata: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        memory_type: str = "conversation",
        source_turn_id: Optional[str] = None,
        source_message_id: Optional[str] = None,
        memory_category: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> str:
        """
        保存情景记忆

        Args:
            content: 记忆内容
            importance: 重要性评分 (1-10)
            metadata: 额外元数据
            session_id: 关联的会话 ID
            memory_type: 记忆类型
            source_turn_id: 该事实来源的 turn ID（Task 4 / Gap A 可追溯性）
            source_message_id: 该事实来源的 message ID（Task 4 / Gap A）
            memory_category: 事实分类（user_pref / project_fact / task_summary /
                cross_session_pattern — 由 extractor 决定）
            summary: 可选的摘要覆盖；省略时由 content 自动生成（向后兼容）。
                ConsolidationPipeline.save_compressed 传入真实摘要，避免把
                "对话摘要: ..." 前缀再包一层。

        Returns:
            生成的记忆 ID
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        memory_id = str(uuid.uuid4())
        now = int(time.time() * 1000)

        # 处理标签
        tags = "[]"
        if metadata and "tags" in metadata:
            tags = json.dumps(metadata["tags"], ensure_ascii=False)

        # 生成摘要（F2 — 允许调用方覆盖，如 ConsolidationPipeline）
        if summary is None:
            summary = self._generate_summary(content)

        cursor.execute(
            """
            INSERT INTO memories_episodic
            (id, content, summary, session_id, memory_type, importance, tags,
             created_at, is_valid,
             source_turn_id, source_message_id, memory_category)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
        """,
            (
                memory_id,
                content,
                summary,
                session_id,
                memory_type,
                importance,
                tags,
                now,
                source_turn_id,
                source_message_id,
                memory_category,
            ),
        )

        conn.commit()
        return memory_id

    def _generate_summary(self, content: str, max_length: int = 100) -> str:
        """
        生成记忆摘要

        Args:
            content: 原始内容
            max_length: 最大长度

        Returns:
            摘要文本
        """
        if len(content) <= max_length:
            return content
        return content[:max_length] + "..."

    def search(
        self,
        query: str,
        limit: int = 10,
        min_importance: int = 1,
        memory_type: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        搜索情景记忆

        使用 jieba 分词，将查询拆分为多个词，用多个 LIKE 条件 OR 连接，
        支持中文检索（如搜索 "用户 火锅" 可匹配 "用户喜欢火锅"）。

        Args:
            query: 搜索关键词
            limit: 返回数量限制
            min_importance: 最小重要性
            memory_type: 可选，按记忆类型筛选

        Returns:
            匹配的记忆列表
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # 使用 jieba 分词，将查询拆分为多个搜索词
        tokens = [t.strip() for t in tokenize(query).split() if t.strip()]

        if not tokens:
            return []

        # 构建 WHERE 子句：每个 token 匹配 content OR summary
        like_conditions = []
        params = []
        for token in tokens:
            like_conditions.append("(content LIKE ? OR summary LIKE ?)")
            params.extend([f"%{token}%", f"%{token}%"])

        # 基础条件
        base_sql = "SELECT * FROM memories_episodic WHERE is_valid = 1"
        where_parts = [base_sql]

        # 分词 OR 条件
        where_parts.append(f"AND ({' OR '.join(like_conditions)})")

        # 重要性条件
        where_parts.append("AND importance >= ?")
        params.append(min_importance)

        # 记忆类型筛选
        if memory_type:
            where_parts.append("AND memory_type = ?")
            params.append(memory_type)

        # 会话筛选必须在 LIMIT 之前完成，避免其他会话占满候选结果。
        if session_id is not None:
            where_parts.append("AND session_id = ?")
            params.append(session_id)

        # 排序 + 限制
        where_parts.append("ORDER BY importance DESC, access_count DESC, created_at DESC LIMIT ?")
        params.append(limit)

        sql = " ".join(where_parts)
        cursor.execute(sql, params)

        results = []
        for row in cursor.fetchall():
            memory = dict(row)
            # 解析标签 JSON
            if memory.get("tags"):
                try:
                    memory["tags"] = json.loads(memory["tags"])
                except json.JSONDecodeError:
                    memory["tags"] = []
            results.append(memory)
            # 更新访问统计
            self._update_access(memory["id"])

        return results

    def get_recent(self, limit: int = 10, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取最近的记忆

        Args:
            limit: 返回数量限制
            session_id: 可选，按会话 ID 筛选

        Returns:
            记忆列表
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        if session_id:
            cursor.execute(
                """
                SELECT * FROM memories_episodic
                WHERE session_id = ? AND is_valid = 1
                ORDER BY created_at DESC
                LIMIT ?
            """,
                (session_id, limit),
            )
        else:
            cursor.execute(
                """
                SELECT * FROM memories_episodic
                WHERE is_valid = 1
                ORDER BY created_at DESC
                LIMIT ?
            """,
                (limit,),
            )

        results = []
        for row in cursor.fetchall():
            memory = dict(row)
            if memory.get("tags"):
                try:
                    memory["tags"] = json.loads(memory["tags"])
                except json.JSONDecodeError:
                    memory["tags"] = []
            results.append(memory)

        return results

    def get_by_session(self, session_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        获取指定会话的记忆

        Args:
            session_id: 会话 ID
            limit: 返回数量限制

        Returns:
            记忆列表
        """
        return self.get_recent(limit=limit, session_id=session_id)

    def delete(self, memory_id: str) -> bool:
        """
        删除记忆（软删除）

        Args:
            memory_id: 记忆 ID

        Returns:
            是否删除成功
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE memories_episodic
            SET is_valid = 0
            WHERE id = ?
        """,
            (memory_id,),
        )

        conn.commit()
        return cursor.rowcount > 0

    def _update_access(self, memory_id: str) -> None:
        """
        更新记忆访问统计

        Args:
            memory_id: 记忆 ID
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        now = int(time.time() * 1000)
        cursor.execute(
            """
            UPDATE memories_episodic
            SET access_count = access_count + 1, accessed_at = ?
            WHERE id = ?
        """,
            (now, memory_id),
        )

        conn.commit()

    def get_by_id(self, memory_id: str) -> Dict[str, Any] | None:
        """
        根据 ID 获取记忆

        Args:
            memory_id: 记忆 ID

        Returns:
            记忆字典，不存在则返回 None
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM memories_episodic
            WHERE id = ? AND is_valid = 1
        """,
            (memory_id,),
        )

        row = cursor.fetchone()
        if row:
            memory = dict(row)
            if memory.get("tags"):
                try:
                    memory["tags"] = json.loads(memory["tags"])
                except json.JSONDecodeError:
                    memory["tags"] = []
            self._update_access(memory_id)
            return memory
        return None

    def _row_to_dict(self, row: Any) -> Dict[str, Any]:
        """把 sqlite3.Row 转成 dict，并解析 tags JSON（新查询方法的公共辅助）。"""
        memory = dict(row)
        if memory.get("tags"):
            try:
                memory["tags"] = json.loads(memory["tags"])
            except json.JSONDecodeError:
                memory["tags"] = []
        return memory

    def find_by_turn(self, turn_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """按来源 turn 查询记忆（Task 5 / Gap E 可追溯性）。

        Args:
            turn_id: 产生该记忆的 turn ID（source_turn_id 列）
            limit: 返回数量限制，默认 50

        Returns:
            匹配的记忆列表，按创建时间倒序
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM memories_episodic
            WHERE source_turn_id = ? AND is_valid = 1
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (turn_id, limit),
        )
        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def find_by_category(
        self, category: str, *, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """按记忆分类查询记忆（Task 5 / Gap E）。

        Args:
            category: 记忆分类（user_pref / project_fact / task_summary /
                cross_session_pattern / decision）
            limit: 返回数量限制，默认 50

        Returns:
            匹配的记忆列表，按创建时间倒序
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM memories_episodic
            WHERE memory_category = ? AND is_valid = 1
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (category, limit),
        )
        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def find_by_category_and_session(
        self, category: str, session_id: str, *, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """按分类 + 会话查询记忆（Task 5 / Gap E，会话摘要用）。

        Args:
            category: 记忆分类
            session_id: 会话 ID
            limit: 返回数量限制，默认 50

        Returns:
            匹配的记忆列表，按创建时间倒序
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM memories_episodic
            WHERE memory_category = ? AND session_id = ? AND is_valid = 1
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (category, session_id, limit),
        )
        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def count(self, session_id: Optional[str] = None) -> int:
        """
        获取记忆总数（批次三 step 5：可按 session 过滤）

        Args:
            session_id: 可选，按会话 ID 严格过滤
                （spec §4.3 step 5 严禁跨 session 串味）

        Returns:
            有效记忆数量
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        if session_id is None:
            cursor.execute("""
                SELECT COUNT(*) FROM memories_episodic
                WHERE is_valid = 1
            """)
        else:
            cursor.execute(
                """
                SELECT COUNT(*) FROM memories_episodic
                WHERE is_valid = 1 AND session_id = ?
                """,
                (session_id,),
            )

        return cursor.fetchone()[0]
