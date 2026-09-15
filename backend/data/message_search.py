"""消息全文索引 - 跨会话对话检索 (Round 2, 对标 hermes session search)

为 messages 表建立独立 FTS5 虚拟表 ``messages_fts``，让 agent 能检索
历史对话原文（"上次我们怎么解决那个构建报错"）——记忆库只存抽取后的
条目，原始对话此前没有检索入口。

设计约束:
- 独立 FTS5 表 + Python 侧显式同步（jieba 分词入库），**不用**
  external-content 触发器 —— 与 memories_semantic_fts 同一模式，
  规避历史 malformed 根因。
- 写入路径 (session_repo) 挂钩 ``index_message``，幂等（先删后插）。
- 查询: FTS MATCH 优先（tokenize_for_search 分词 + OR 连接），
  异常/无命中回退 LIKE。
- 非关键路径: 任何索引故障只 warning，绝不阻塞消息写入。
"""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any, Dict, List, Optional

from backend.memory.chinese_tokenizer import tokenize_for_search

logger = logging.getLogger(__name__)

MESSAGES_FTS_TABLE = "messages_fts"

#: LIKE 回退时的单条内容采样上限（避免超长工具输出拖慢扫描）
_CONTENT_SAMPLE_CHARS = 4000


def ensure_messages_fts_schema(conn: sqlite3.Connection) -> None:
    """确保 messages_fts 为健康的独立 FTS5 虚拟表（幂等，永不抛出）。

    结构残留（非虚拟表 / external-content 旧结构）→ drop 重建；
    完整性探测失败（malformed）→ drop 重建。失败仅 warning。
    """
    try:
        cursor = conn.cursor()
        row = cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (MESSAGES_FTS_TABLE,),
        ).fetchone()
        if row is not None:
            schema_sql = (row[0] or "").replace(" ", "").lower()
            if "virtualtable" not in schema_sql or "content=" in schema_sql:
                logger.warning("messages_fts 为旧结构，drop 重建为独立 FTS5 表")
                cursor.execute(f"DROP TABLE IF EXISTS {MESSAGES_FTS_TABLE}")
            else:
                try:
                    cursor.execute(f"SELECT count(*) FROM {MESSAGES_FTS_TABLE}")
                    cursor.fetchone()
                except sqlite3.DatabaseError as exc:
                    logger.warning("messages_fts 损坏（%s），drop 重建", exc)
                    cursor.execute(f"DROP TABLE IF EXISTS {MESSAGES_FTS_TABLE}")
        cursor.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {MESSAGES_FTS_TABLE} "
            "USING fts5(content, message_id UNINDEXED, session_id UNINDEXED, "
            "role UNINDEXED, created_at UNINDEXED)"
        )
        conn.commit()
    except Exception as exc:  # noqa: BLE001 — 索引为增强能力, 不阻塞启动
        logger.warning("messages_fts 初始化失败（消息全文检索不可用）: %s", exc)


class MessageSearchIndex:
    """messages 表的 FTS5 全文索引（跨会话对话检索）"""

    def __init__(self, db: Any) -> None:
        self.db = db
        conn = self.db.get_connection()
        ensure_messages_fts_schema(conn)

    @property
    def _available(self) -> bool:
        """索引表可用性探测（未初始化/损坏时降级 LIKE）"""
        try:
            self.db.get_connection().execute(
                f"SELECT count(*) FROM {MESSAGES_FTS_TABLE}"
            ).fetchone()
            return True
        except Exception:
            return False

    def index_message(
        self,
        message_id: str,
        session_id: str,
        role: str,
        content: str,
        created_at: Optional[int] = None,
    ) -> bool:
        """索引（或重新索引）一条消息。幂等；失败仅 warning。

        空白内容（纯工具占位消息）跳过 —— 无检索价值。
        """
        if not content or not content.strip():
            return False
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                f"DELETE FROM {MESSAGES_FTS_TABLE} WHERE message_id = ?",
                (message_id,),
            )
            cursor.execute(
                f"INSERT INTO {MESSAGES_FTS_TABLE} "
                "(content, message_id, session_id, role, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    tokenize_for_search(content[:_CONTENT_SAMPLE_CHARS]),
                    message_id,
                    session_id,
                    role,
                    int(created_at) if created_at is not None else int(time.time()),
                ),
            )
            conn.commit()
            return True
        except Exception as exc:  # noqa: BLE001 — 索引故障不拖垮写入路径
            logger.warning("消息索引失败 (message_id=%s): %s", message_id, exc)
            return False

    def remove_message(self, message_id: str) -> None:
        """从索引移除一条消息（消息删除路径调用；best-effort）"""
        try:
            conn = self.db.get_connection()
            conn.execute(
                f"DELETE FROM {MESSAGES_FTS_TABLE} WHERE message_id = ?",
                (message_id,),
            )
            conn.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("消息索引移除失败 (message_id=%s): %s", message_id, exc)

    def search(
        self,
        query: str,
        session_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """跨会话检索历史对话

        FTS MATCH 优先（jieba 分词 + OR 连接，语义同 memories_semantic_fts），
        异常或无命中时回退 LIKE。命中回连 messages 主表取原始内容并做
        Python 侧摘要窗口。

        Returns:
            [{message_id, session_id, role, created_at, excerpt}] 按相关度/
            新近度排序，最多 limit 条；索引不可用时返回 []。
        """
        if not query or not query.strip():
            return []
        try:
            limit = max(1, min(int(limit), 50))
        except (TypeError, ValueError):
            limit = 10

        results: List[Dict[str, Any]] = []
        if self._available:
            results = self._search_fts(query, session_id, limit)
        if not results:
            results = self._search_like(query, session_id, limit)

        # 回连主表取原始内容 → 摘要窗口（FTS 行的 content 是分词文本）
        conn = self.db.get_connection()
        final: List[Dict[str, Any]] = []
        for row in results:
            try:
                msg = conn.execute(
                    "SELECT id, session_id, role, content, created_at "
                    "FROM messages WHERE id = ?",
                    (row["message_id"],),
                ).fetchone()
            except Exception:  # noqa: BLE001 — 单条回连失败跳过
                msg = None
            if msg is None:
                continue
            final.append(
                {
                    "message_id": msg[0],
                    "session_id": msg[1],
                    "role": msg[2],
                    "created_at": msg[4],
                    "excerpt": _excerpt(msg[3] or "", query),
                }
            )
        return final

    def _search_fts(
        self, query: str, session_id: Optional[str], limit: int
    ) -> List[Dict[str, Any]]:
        try:
            conn = self.db.get_connection()
            match_query = tokenize_for_search(query)
            if not match_query.strip():
                return []
            sql = (
                f"SELECT message_id, session_id FROM {MESSAGES_FTS_TABLE} "
                f"WHERE {MESSAGES_FTS_TABLE} MATCH ? AND role IN "
                "('user', 'assistant')"
            )
            params: List[Any] = [match_query]
            if session_id:
                sql += " AND session_id = ?"
                params.append(session_id)
            sql += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return [
                {"message_id": r[0], "session_id": r[1]}
                for r in rows
            ]
        except Exception as exc:  # noqa: BLE001 — FTS 故障回退 LIKE
            logger.warning("messages_fts MATCH 失败，回退 LIKE: %s", exc)
            return []

    def _search_like(
        self, query: str, session_id: Optional[str], limit: int
    ) -> List[Dict[str, Any]]:
        """LIKE + jieba 分词回退（FTS 不可用或无命中时）"""
        try:
            conn = self.db.get_connection()
            from backend.memory.chinese_tokenizer import tokenize

            tokens = [t for t in tokenize(query).split() if len(t.strip()) >= 2]
            if not tokens:
                tokens = [query.strip()]
            # 通配符转义（与 /search/messages 原 LIKE 路径同约定）
            escaped = [
                f"%{t.replace('!', '!!').replace('%', '!%').replace('_', '!_')}%"
                for t in tokens
            ]
            conditions = " OR ".join(["content LIKE ? ESCAPE '!'" for _ in tokens])
            params: List[Any] = escaped
            sql = (
                "SELECT id, session_id FROM messages "
                f"WHERE role != 'tool' AND ({conditions})"
            )
            if session_id:
                sql += " AND session_id = ?"
                params.append(session_id)
            sql += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return [{"message_id": r[0], "session_id": r[1]} for r in rows]
        except Exception as exc:  # noqa: BLE001
            logger.warning("消息 LIKE 搜索失败: %s", exc)
            return []

    def rebuild_all(self) -> int:
        """全量重建索引（读 messages 主表回填）。返回索引条数。"""
        conn = self.db.get_connection()
        ensure_messages_fts_schema(conn)
        try:
            conn.execute(f"DELETE FROM {MESSAGES_FTS_TABLE}")
            conn.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("messages_fts 清空失败: %s", exc)
            return 0
        count = 0
        try:
            rows = conn.execute(
                "SELECT id, session_id, role, content, created_at FROM messages"
            ).fetchall()
        except Exception as exc:  # noqa: BLE001
            logger.warning("messages 全量读取失败: %s", exc)
            return 0
        for r in rows:
            if self.index_message(r[0], r[1] or "", r[2], r[3] or "", r[4]):
                count += 1
        logger.info("messages_fts 全量重建完成: %d 条", count)
        return count


def _excerpt(content: str, query: str, window: int = 120) -> str:
    """取查询词首次命中位置附近的原文窗口作为摘要"""
    text = content[:_CONTENT_SAMPLE_CHARS]
    pos = -1
    for token in query.split():
        pos = text.find(token)
        if pos >= 0:
            break
    if pos < 0:
        # 分词后再试
        from backend.memory.chinese_tokenizer import tokenize

        for token in tokenize(query).split():
            pos = text.find(token)
            if pos >= 0:
                break
    if pos < 0:
        return text[:window] + ("…" if len(text) > window else "")
    start = max(0, pos - window // 3)
    end = min(len(text), start + window)
    return ("…" if start > 0 else "") + text[start:end] + ("…" if end < len(text) else "")


# --------------------------------------------------------------------------- #
# 全局单例（与 get_review_queue 同模式）
# --------------------------------------------------------------------------- #

_message_search_index: Optional[MessageSearchIndex] = None


def get_message_search_index() -> MessageSearchIndex:
    """返回全局 MessageSearchIndex 单例（惰性，基于 get_database()）"""
    global _message_search_index
    if _message_search_index is None:
        from backend.data.database import get_database

        _message_search_index = MessageSearchIndex(get_database())
    return _message_search_index


def reset_message_search_index() -> None:
    """重置单例（测试环境按用例重绑 Database 时调用，与 reset_wake_store 同理）"""
    global _message_search_index
    _message_search_index = None
