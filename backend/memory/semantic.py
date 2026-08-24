"""
Semantic Memory - 语义记忆模块
使用 SQLite FTS5 全文搜索存储知识和概念
注意：暂不使用 ChromaDB，保持简单

中文支持：使用 jieba 分词，将分词结果存入独立 FTS5 表 memories_semantic_fts
（非 external-content，存分词文本而非原文，见 backend.data.database 中的
ensure_semantic_fts_schema）。写入/更新/删除由本类在 Python 侧显式同步索引
（单一事实来源，不使用触发器——历史 external-content + 触发器方案曾导致
"database disk image is malformed"）。search() 优先走 FTS5 MATCH，
命中为空或查询异常时回退 LIKE+jieba（_search_like），保证可用性。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

from backend.data.database import (
    backfill_semantic_fts,
    ensure_semantic_fts_schema,
    fts_row_texts,
)
from backend.memory.chinese_tokenizer import tokenize, tokenize_for_search

logger = logging.getLogger(__name__)


class SemanticMemory:
    """
    语义记忆 - 管理知识和概念

    特性:
    - SQLite FTS5 全文搜索（基于 jieba 分词）
    - 支持摘要生成
    - 持久化存储
    - 不引入 ChromaDB（保持简单）
    """

    def __init__(self, db):
        """
        初始化语义记忆

        Args:
            db: Database 实例
        """
        self.db = db
        self._init_fts()

    def _init_fts(self) -> None:
        """确保主表与 FTS5 索引表存在且健康（schema 维护统一委托给 database 模块）。"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # 创建语义记忆主表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories_semantic (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                summary TEXT,
                tags TEXT DEFAULT '[]',
                session_id TEXT,
                created_at INTEGER NOT NULL
            )
        """)
        columns = {
            row["name"]
            for row in cursor.execute("PRAGMA table_info(memories_semantic)")
        }
        if "session_id" not in columns:
            cursor.execute(
                "ALTER TABLE memories_semantic ADD COLUMN session_id TEXT"
            )
            # 升级前已落库但 session_id 为 NULL 的旧语义记忆,统一回填为 'default'。
            # 必须仅在列刚被添加时执行,避免覆盖升级后新写入的合法 NULL 边界
            # (语义层非空约束由 save() 强制,这里只在迁移窗口内兜底)。
            cursor.execute(
                "UPDATE memories_semantic SET session_id = 'default' "
                "WHERE session_id IS NULL"
            )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_semantic_session_created "
            "ON memories_semantic(session_id, created_at DESC)"
        )
        conn.commit()

        # FTS5 独立虚拟表：结构检测/损坏自愈（database.ensure_semantic_fts_schema）
        # + 幂等回填（覆盖绕过本类直接写主表的行，如 evolution 晋升）
        if ensure_semantic_fts_schema(conn):
            backfill_semantic_fts(conn, force=True)
        else:
            backfill_semantic_fts(conn)

    def save(
        self,
        content: str,
        summary: Optional[str] = None,
        tags: Optional[List[str]] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """
        保存语义记忆

        Args:
            content: 记忆内容
            summary: 可选的摘要
            tags: 可选的标签列表
            session_id: 可选的关联会话 ID

        Returns:
            生成的记忆 ID
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        memory_id = str(uuid.uuid4())
        now = int(time.time() * 1000)

        # 生成摘要
        if summary is None:
            summary = self._generate_summary(content)

        # 处理标签
        tags_json = json.dumps(tags or [], ensure_ascii=False)

        # 插入主表
        cursor.execute(
            """
            INSERT INTO memories_semantic
            (id, content, summary, tags, session_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (memory_id, content, summary, tags_json, session_id, now),
        )

        # 显式同步 FTS 索引（单一事实来源：Python 侧维护，不使用触发器，
        # 详见 backend.data.database.ensure_semantic_fts_schema 的根因说明）
        self._sync_fts_row(cursor, memory_id)

        conn.commit()
        return memory_id

    def _sync_fts_row(self, cursor: sqlite3.Cursor, memory_id: str) -> None:
        """重建指定记忆的 FTS 索引行（按 rowid 先删后插，与主表行对齐）。

        FTS 索引为辅助路径：同步失败只记 warning，不中断主表写入；
        搜索可回退 LIKE 路径，且下次 init_db 会幂等回填补齐。
        """
        try:
            row = cursor.execute(
                "SELECT rowid, content, summary, tags FROM memories_semantic WHERE id = ?",
                (memory_id,),
            ).fetchone()
            if row is None:
                return
            cursor.execute(
                "DELETE FROM memories_semantic_fts WHERE rowid = ?", (row["rowid"],)
            )
            cursor.execute(
                "INSERT INTO memories_semantic_fts (rowid, content, summary, tags) "
                "VALUES (?, ?, ?, ?)",
                (row["rowid"],) + fts_row_texts(row["content"], row["summary"], row["tags"]),
            )
        except sqlite3.DatabaseError as exc:
            logger.warning("FTS 索引同步失败 (memory_id=%s): %s", memory_id, exc)

    def _generate_summary(self, content: str, max_length: int = 150) -> str:
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
        tags: Optional[List[str]] = None,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        搜索语义记忆

        优先走 FTS5 全文索引（jieba 分词后 MATCH）；命中为空或 FTS 查询异常时
        回退 LIKE+jieba 路径（_search_like），保证任何情况下搜索可用。
        importance/标签过滤、排序（created_at DESC）、limit 语义与原实现一致。

        Args:
            query: 搜索关键词
            limit: 返回数量限制
            tags: 可选，按标签筛选

        Returns:
            匹配的记忆列表
        """
        if not query or query.strip() == "":
            return self.get_recent(limit, session_id=session_id)

        fts_results = self._search_fts(query, limit, tags, session_id=session_id)
        if fts_results:
            return fts_results

        # FTS 无命中（如索引尚未回填）或异常 → 回退 LIKE+jieba
        return self._search_like(query, limit, tags, session_id=session_id)

    def _search_fts(
        self,
        query: str,
        limit: int = 10,
        tags: Optional[List[str]] = None,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        走 FTS5 全文索引搜索（jieba 分词 + OR MATCH）。

        查询串由 _prepare_fts_query 生成：每个词双引号包裹（内部引号翻倍转义，
        防 FTS 语法注入）后 OR 连接。FTS 索引行通过 rowid 与主表对齐。

        Args:
            query: 原始查询
            limit: 返回数量限制
            tags: 可选，按标签筛选（主表 tags JSON 上做 LIKE 过滤，与 LIKE 路径一致）

        Returns:
            匹配的记忆列表；查询异常或无命中时返回 []，由调用方回退 LIKE 路径
        """
        match_expr = self._prepare_fts_query(query)
        if not match_expr or match_expr == '""':
            return []

        sql_parts = [
            "SELECT ms.* FROM memories_semantic ms",
            "JOIN memories_semantic_fts ON memories_semantic_fts.rowid = ms.rowid",
            "WHERE memories_semantic_fts MATCH ?",
        ]
        params: List[Any] = [match_expr]

        if session_id is not None:
            sql_parts.append("AND ms.session_id = ?")
            params.append(session_id)

        # 标签过滤
        if tags:
            tag_conditions = []
            for tag in tags:
                tag_conditions.append("ms.tags LIKE ?")
                params.append(f'%"{tag}"%')
            sql_parts.append(f"AND ({' OR '.join(tag_conditions)})")

        sql_parts.append("ORDER BY ms.created_at DESC LIMIT ?")
        params.append(limit)

        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute(" ".join(sql_parts), params)
            return self._rows_to_memories(cursor.fetchall())
        except sqlite3.DatabaseError as exc:
            logger.warning("FTS5 搜索失败，回退 LIKE 路径: %s", exc)
            return []

    def _prepare_fts_query(self, query: str) -> str:
        """
        准备 FTS5 查询字符串（使用 jieba 分词）

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
        tags: Optional[List[str]] = None,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        LIKE + jieba 回退搜索（FTS 索引不可用或无命中时使用）

        Args:
            query: 搜索关键词
            limit: 返回数量限制
            tags: 可选，按标签筛选

        Returns:
            匹配的记忆列表
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # jieba 分词，将查询拆分为多个搜索词
        tokens = [t.strip() for t in tokenize(query).split() if t.strip()]
        if not tokens:
            return self.get_recent(limit, session_id=session_id)

        # 构建 LIKE OR 条件
        like_conditions = []
        params: List[Any] = []
        for token in tokens:
            like_conditions.append("(content LIKE ? OR summary LIKE ?)")
            params.extend([f"%{token}%", f"%{token}%"])

        sql_parts = [
            "SELECT * FROM memories_semantic",
            f"WHERE ({' OR '.join(like_conditions)})",
        ]

        if session_id is not None:
            sql_parts.append("AND session_id = ?")
            params.append(session_id)

        # 标签过滤
        if tags:
            tag_conditions = []
            for tag in tags:
                tag_conditions.append("tags LIKE ?")
                params.append(f'%"{tag}"%')
            sql_parts.append(f"AND ({' OR '.join(tag_conditions)})")

        sql_parts.append("ORDER BY created_at DESC LIMIT ?")
        params.append(limit)

        cursor.execute(" ".join(sql_parts), params)
        return self._rows_to_memories(cursor.fetchall())

    @staticmethod
    def _rows_to_memories(rows: List[sqlite3.Row]) -> List[Dict[str, Any]]:
        """将数据库行转换为记忆字典列表（解析 tags JSON）。"""
        results = []
        for row in rows:
            memory = dict(row)
            if memory.get("tags"):
                try:
                    memory["tags"] = json.loads(memory["tags"])
                except json.JSONDecodeError:
                    memory["tags"] = []
            results.append(memory)
        return results

    def get_recent(
        self, limit: int = 20, session_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        获取最近的语义记忆

        Args:
            limit: 返回数量限制

        Returns:
            记忆列表
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        if session_id is None:
            cursor.execute(
                """
                SELECT * FROM memories_semantic
                ORDER BY created_at DESC
                LIMIT ?
            """,
                (limit,),
            )
        else:
            cursor.execute(
                """
                SELECT * FROM memories_semantic
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """,
                (session_id, limit),
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

    def get_all(self) -> List[Dict[str, Any]]:
        """
        获取所有语义记忆

        Returns:
            所有记忆列表
        """
        return self.get_recent(limit=10000)

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
            SELECT * FROM memories_semantic
            WHERE id = ?
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
            return memory
        return None

    def delete(self, memory_id: str) -> bool:
        """
        删除语义记忆

        Args:
            memory_id: 记忆 ID

        Returns:
            是否删除成功
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # 删除前取 rowid，用于同步删除 FTS 索引行
        row = cursor.execute(
            "SELECT rowid FROM memories_semantic WHERE id = ?", (memory_id,)
        ).fetchone()
        cursor.execute("DELETE FROM memories_semantic WHERE id = ?", (memory_id,))
        deleted = cursor.rowcount > 0

        if row is not None:
            try:
                cursor.execute(
                    "DELETE FROM memories_semantic_fts WHERE rowid = ?", (row["rowid"],)
                )
            except sqlite3.DatabaseError as exc:
                logger.warning("FTS 索引删除失败 (memory_id=%s): %s", memory_id, exc)

        conn.commit()
        return deleted

    def count(self) -> int:
        """
        获取记忆总数

        Returns:
            记忆数量
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM memories_semantic")
        return cursor.fetchone()[0]

    def update_tags(self, memory_id: str, tags: List[str]) -> bool:
        """
        更新记忆标签

        FTS 索引由本方法显式同步（单一事实来源，不使用触发器，见 _sync_fts_row）。

        Args:
            memory_id: 记忆 ID
            tags: 新的标签列表

        Returns:
            是否更新成功
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        tags_json = json.dumps(tags, ensure_ascii=False)

        cursor.execute(
            """
            UPDATE memories_semantic
            SET tags = ?
            WHERE id = ?
        """,
            (tags_json, memory_id),
        )
        updated = cursor.rowcount > 0

        if updated:
            self._sync_fts_row(cursor, memory_id)

        conn.commit()
        return updated
