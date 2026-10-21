"""
Episodic Memory - 情景记忆模块
基于 SQLite 存储对话历史和事件序列

中文支持：使用 jieba 分词，将分词结果存入独立 FTS5 表 memories_episodic_fts
（非 external-content，存分词文本而非原文）。写入/更新/删除由本类在 Python 侧
显式同步索引（单一事实来源，不使用触发器）。search() 优先走 FTS5 MATCH，
命中为空或查询异常时回退 LIKE+jieba（_search_like），保证可用性。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

from backend.data.database import fts_row_texts
from backend.memory import scope as memory_scope
from backend.memory.auto_tag import derive_tags, normalize_tags
from backend.memory.chinese_tokenizer import tokenize, tokenize_for_search
from backend.memory.summary_text import truncate_summary

logger = logging.getLogger(__name__)


# 单批回填行数。_backfill_fts() 循环执行直到补齐全部缺失行。
# 早期实现单批 LIMIT 500 后直接返回，而回填只在 _init_fts() 跑一次——
# 存量超过 500 条时绝大多数记忆永远进不了索引，FTS 检索静默漏召回。
_FTS_BACKFILL_BATCH = 500


def sync_fts_row_for_id(conn: sqlite3.Connection, memory_id: str) -> None:
    """把指定 id 的情景记忆同步进 FTS 索引（幂等：先删后插）。

    供绕过 EpisodicMemory.save() 的直写路径使用（如 scheduler/evolution.py
    的每日摘要），避免新增记忆必须等到下次重启才能被 FTS 检索到。

    失败只记 warning：FTS 是辅助路径，search() 命中为空即回退 LIKE；
    下次 _backfill_fts() 循环也会幂等补齐。
    """
    try:
        cursor = conn.cursor()
        row = cursor.execute(
            "SELECT rowid, content, summary, tags FROM memories_episodic WHERE id = ?",
            (memory_id,),
        ).fetchone()
        if row is None:
            return
        cursor.execute(
            "DELETE FROM memories_episodic_fts WHERE rowid = ?", (row["rowid"],)
        )
        cursor.execute(
            "INSERT INTO memories_episodic_fts (rowid, content, summary, tags) "
            "VALUES (?, ?, ?, ?)",
            (row["rowid"],) + fts_row_texts(row["content"], row["summary"], row["tags"]),
        )
    except sqlite3.DatabaseError as exc:
        logger.warning("FTS 索引同步失败 (memory_id=%s): %s", memory_id, exc)


class EpisodicMemory:
    """
    情景记忆 - 管理事件序列和经历

    特性:
    - SQLite 持久化存储
    - FTS5 全文搜索（基于 jieba 分词）
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
        self._init_fts()

    def _init_fts(self) -> None:
        """初始化 FTS5 全文索引表（memories_episodic_fts）。

        FTS 索引为辅助路径：同步失败只记 warning，不中断主表写入；
        搜索可回退 LIKE 路径，且下次启动会幂等回填补齐。
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # 创建 FTS5 虚拟表（如果不存在）
        try:
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_episodic_fts
                USING fts5(content, summary, tags)
            """)
            conn.commit()
        except sqlite3.DatabaseError as exc:
            logger.warning(f"FTS5 索引表创建失败: {exc}")
            return

        # 回填存量数据（幂等）
        self._backfill_fts()

    def _backfill_fts(self) -> None:
        """回填 FTS 索引（幂等：已存在 rowid 的行跳过）。

        分批循环执行直到补齐**全部**缺失行，每批 commit 一次。
        用于初始化时或存量数据缺 FTS 索引时批量补齐。

        历史缺陷（2026-10-19 修）：早期实现是单批 LIMIT 500 后立即返回，
        而 _backfill_fts() 仅在 _init_fts() 中调用一次。结果：当 memories_episodic
        存量超过 500 条时，绝大多数记忆永远进不了 FTS 索引，FTS 检索静默漏召回
        ——search() 命中非空即直接返回，不会回退 LIKE，用户完全无感知。
        实测 10k 合成语料下只有 500 行被索引，DevOps / 数据库等 topic 查询
        命中为 0，与 tokenizer 差异无关（误诊）。
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()
        total = 0

        try:
            while True:
                cursor.execute(
                    """
                    SELECT rowid, content, summary, tags FROM memories_episodic
                    WHERE is_valid = 1 AND invalid_at IS NULL
                      AND rowid NOT IN (SELECT rowid FROM memories_episodic_fts)
                    LIMIT ?
                    """,
                    (_FTS_BACKFILL_BATCH,),
                )
                rows = cursor.fetchall()
                if not rows:
                    break
                for row in rows:
                    cursor.execute(
                        "INSERT INTO memories_episodic_fts (rowid, content, summary, tags) "
                        "VALUES (?, ?, ?, ?)",
                        (row["rowid"],) + fts_row_texts(
                            row["content"], row["summary"], row["tags"]
                        ),
                    )
                conn.commit()
                total += len(rows)
            if total:
                logger.info("FTS 索引回填完成: %d 条", total)
        except sqlite3.DatabaseError as exc:
            logger.warning("FTS 索引回填失败 (已补 %d 条): %s", total, exc)

    def _sync_fts_row(self, cursor: sqlite3.Cursor, memory_id: str) -> None:
        """重建指定记忆的 FTS 索引行（按 rowid 先删后插，与主表行对齐）。

        FTS 索引为辅助路径：同步失败只记 warning，不中断主表写入；
        搜索可回退 LIKE 路径，且下次启动会幂等回填补齐。

        实现委托给模块级 sync_fts_row_for_id()，保持单一事实源。
        """
        sync_fts_row_for_id(cursor.connection, memory_id)

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
        scope: Optional[str] = None,
        project_key: Optional[str] = None,
        supersedes_id: Optional[str] = None,
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
            scope: 作用域 ('user'|'project'|'global')，None → 按会话
                workspace 绑定自动判定（见 backend.memory.scope）
            project_key: 项目目录（scope='project' 时生效）

        Returns:
            生成的记忆 ID
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        memory_id = str(uuid.uuid4())
        now = int(time.time() * 1000)

        # P1 作用域轴：未显式声明时自动判定（绑定项目 → project，否则 user）
        scope, project_key = memory_scope.finalize_scope(
            self.db, scope, project_key, session_id
        )

        # 处理标签：显式标签优先；缺省时从内容自动派生（缓解标签稀疏，
        # 否则 TagCooccurrenceGraph 的共现矩阵几乎没有边）
        tag_list = normalize_tags(metadata.get("tags") if metadata else None)
        if not tag_list:
            tag_list = derive_tags(content)
        tags = json.dumps(tag_list, ensure_ascii=False)

        # 生成摘要（F2 — 允许调用方覆盖，如 ConsolidationPipeline）
        if summary is None:
            summary = self._generate_summary(content)

        cursor.execute(
            """
            INSERT INTO memories_episodic
            (id, content, summary, session_id, memory_type, importance, tags,
             created_at, is_valid, scope, project_key, supersedes_id,
             source_turn_id, source_message_id, memory_category)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
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
                scope,
                project_key,
                supersedes_id,
                source_turn_id,
                source_message_id,
                memory_category,
            ),
        )

        # 显式同步 FTS 索引（单一事实来源：Python 侧维护，不使用触发器）
        self._sync_fts_row(cursor, memory_id)

        conn.commit()
        return memory_id

    def _generate_summary(self, content: str, max_length: int = 100) -> str:
        """生成记忆摘要 — 实现统一委托共享工具 (D2)。"""
        return truncate_summary(content, max_length)

    def search(
        self,
        query: str,
        limit: int = 10,
        min_importance: int = 1,
        memory_type: Optional[str] = None,
        session_id: Optional[str] = None,
        scope: Optional[str] = None,
        project_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        搜索情景记忆

        优先走 FTS5 全文索引（jieba 分词后 MATCH）；命中为空或 FTS 查询异常时
        回退 LIKE+jieba 路径（_search_like），保证任何情况下搜索可用。
        importance/标签过滤、排序（importance DESC, access_count DESC, created_at DESC）、
        limit 语义与原实现一致。

        Args:
            query: 搜索关键词
            limit: 返回数量限制
            min_importance: 最小重要性
            memory_type: 可选，按记忆类型筛选
            scope: P1 作用域过滤（'user'|'project'|'global'）。给定时
                不做 session 隔离 —— 用于同项目跨会话 / 用户级跨会话检索
            project_key: scope='project' 时必填，限定项目目录

        Returns:
            匹配的记忆列表
        """
        if not query or query.strip() == "":
            return self.get_recent(limit, session_id=session_id)

        # 优先走 FTS5
        fts_results = self._search_fts(
            query, limit, min_importance, memory_type, session_id=session_id,
            scope=scope, project_key=project_key,
        )
        if fts_results:
            return fts_results

        # FTS 无命中（如索引尚未回填）或异常 → 回退 LIKE+jieba
        return self._search_like(
            query, limit, min_importance, memory_type, session_id=session_id,
            scope=scope, project_key=project_key,
        )

    def _search_fts(
        self,
        query: str,
        limit: int = 10,
        min_importance: int = 1,
        memory_type: Optional[str] = None,
        session_id: Optional[str] = None,
        scope: Optional[str] = None,
        project_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """走 FTS5 全文索引搜索（jieba 分词 + OR MATCH）。

        查询串由 _prepare_fts_query 生成：每个词双引号包裹（内部引号翻倍转义，
        防 FTS 语法注入）后 OR 连接。FTS 索引行通过 rowid 与主表对齐。

        Args:
            query: 原始查询
            limit: 返回数量限制
            min_importance: 最小重要性
            memory_type: 可选，按记忆类型筛选

        Returns:
            匹配的记忆列表；查询异常或无命中时返回 []，由调用方回退 LIKE 路径
        """
        match_expr = self._prepare_fts_query(query)
        if not match_expr or match_expr == '""':
            return []

        sql_parts = [
            "SELECT me.* FROM memories_episodic me",
            "JOIN memories_episodic_fts ON memories_episodic_fts.rowid = me.rowid",
            "WHERE memories_episodic_fts MATCH ? AND me.is_valid = 1 AND me.invalid_at IS NULL",
        ]
        params: List[Any] = [match_expr]

        # 重要性条件
        sql_parts.append("AND me.importance >= ?")
        params.append(min_importance)

        # 记忆类型筛选
        if memory_type:
            sql_parts.append("AND me.memory_type = ?")
            params.append(memory_type)

        # P1 作用域检索
        if scope:
            if scope == memory_scope.SCOPE_PROJECT:
                if not project_key:
                    return []
                sql_parts.append("AND me.scope = ? AND me.project_key = ?")
                params.extend([scope, project_key])
            elif scope == memory_scope.SCOPE_USER:
                sql_parts.append("AND (me.scope IS NULL OR me.scope = ?)")
                params.append(scope)
            else:
                sql_parts.append("AND me.scope = ?")
                params.append(scope)
        elif session_id is not None:
            sql_parts.append("AND me.session_id = ?")
            params.append(session_id)

        sql_parts.append("ORDER BY me.importance DESC, me.access_count DESC, me.created_at DESC LIMIT ?")
        params.append(limit)

        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute(" ".join(sql_parts), params)
            results = []
            for row in cursor.fetchall():
                memory = dict(row)
                if memory.get("tags"):
                    try:
                        memory["tags"] = json.loads(memory["tags"])
                    except json.JSONDecodeError:
                        memory["tags"] = []
                results.append(memory)
                # 更新访问统计
                self._update_access(memory["id"])
            return results
        except sqlite3.DatabaseError as exc:
            logger.warning("FTS5 搜索失败，回退 LIKE 路径: %s", exc)
            return []

    def _prepare_fts_query(self, query: str) -> str:
        """准备 FTS5 查询字符串（使用 jieba 分词）。

        Args:
            query: 原始查询

        Returns:
            处理后的 FTS5 查询（jieba 分词 + 双引号包裹 + OR 连接）
        """
        return tokenize_for_search(query)

    def _search_like(
        self,
        query: str,
        limit: int = 10,
        min_importance: int = 1,
        memory_type: Optional[str] = None,
        session_id: Optional[str] = None,
        scope: Optional[str] = None,
        project_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """LIKE + jieba 回退搜索（FTS 索引不可用或无命中时使用）。

        Args:
            query: 搜索关键词
            limit: 返回数量限制
            min_importance: 最小重要性
            memory_type: 可选，按记忆类型筛选
            scope: 可选，P1 作用域过滤（跨会话）
            project_key: scope='project' 时限定项目目录

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

        # 基础条件（P3: invalid_at 非空 = 已被更新事实取代，不再召回）
        base_sql = "SELECT * FROM memories_episodic WHERE is_valid = 1 AND invalid_at IS NULL"
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

        # P1 作用域检索：scope 给定时按作用域轴取数（跨会话），
        # project 作用域必须带 project_key 才有效。
        if scope:
            if scope == memory_scope.SCOPE_PROJECT:
                if not project_key:
                    return []
                where_parts.append("AND scope = ? AND project_key = ?")
                params.extend([scope, project_key])
            elif scope == memory_scope.SCOPE_USER:
                # 存量行 scope 可能为 NULL（迁移窗口外直写），按 user 处理
                where_parts.append("AND (scope IS NULL OR scope = ?)")
                params.append(scope)
            else:
                where_parts.append("AND scope = ?")
                params.append(scope)
        elif session_id is not None:
            # 会话筛选必须在 LIMIT 之前完成，避免其他会话占满候选结果。
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
                WHERE session_id = ? AND is_valid = 1 AND invalid_at IS NULL
                ORDER BY created_at DESC
                LIMIT ?
            """,
                (session_id, limit),
            )
        else:
            cursor.execute(
                """
                SELECT * FROM memories_episodic
                WHERE is_valid = 1 AND invalid_at IS NULL
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
        deleted = cursor.rowcount > 0

        # D1 (P6): 软删除同样移除向量条目 —— 主表行保留供审计, 但失效
        # 记忆不应再被向量检索命中 (best-effort, 表不存在时静默跳过)。
        # 注意先取主表 rowcount 再做向量清理, 避免返回值被覆盖。
        try:
            cursor.execute("DELETE FROM memories_vec WHERE memory_id = ?", (memory_id,))
        except sqlite3.DatabaseError as exc:
            logger.warning("向量索引删除失败 (memory_id=%s): %s", memory_id, exc)

        conn.commit()
        return deleted

    def invalidate(self, memory_id: str) -> bool:
        """P3 时间有效区：把记忆标记为"已被更新的事实取代"（invalid_at=now）。

        与 :meth:`delete`（用户删除, is_valid=0）区分：失效行保留内容供审计
        与 supersedes 链追溯，但不再出现在任何检索/列表读路径。
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE memories_episodic
            SET invalid_at = ?
            WHERE id = ? AND is_valid = 1 AND invalid_at IS NULL
        """,
            (int(time.time() * 1000), memory_id),
        )
        invalidated = cursor.rowcount > 0
        # 与软删除同模式：失效记忆不再被向量检索命中（best-effort）
        if invalidated:
            try:
                cursor.execute("DELETE FROM memories_vec WHERE memory_id = ?", (memory_id,))
            except sqlite3.DatabaseError as exc:
                logger.warning("向量索引失效清理失败 (memory_id=%s): %s", memory_id, exc)
        conn.commit()
        return invalidated

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

    def exists_by_content(self, content: str) -> bool:
        """R21-B: 导入去重 —— 精确匹配 content 的有效记忆是否已存在。"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM memories_episodic "
            "WHERE content = ? AND is_valid = 1 AND invalid_at IS NULL LIMIT 1",
            (content,),
        )
        return cursor.fetchone() is not None

    def get_by_id(self, memory_id: str) -> Optional[Dict[str, Any]]:
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
                WHERE is_valid = 1 AND invalid_at IS NULL
            """)
        else:
            cursor.execute(
                """
                SELECT COUNT(*) FROM memories_episodic
                WHERE is_valid = 1 AND invalid_at IS NULL AND session_id = ?
                """,
                (session_id,),
            )

        return cursor.fetchone()[0]
