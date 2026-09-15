"""Session Lineage - 压缩谱系 (Round 4, 对标 hermes-agent session lineage)

压缩（compaction）此前就地删除旧消息前缀，原文永久丢失。本模块在
删除前把前缀消息归档进一个派生会话（is_archived=1，不混入正常列表），
并记录 parent/child 谱系 —— 压缩前的完整对话永远可溯。

事务语义: 归档与删除在同一事务（由 replace_prefix_with_continuation
的 cursor 驱动）——「历史已删、归档未写」与「历史已删、摘要未写」
同样是不可接受的永久丢失窗口（M4 CRITICAL-1 同哲学）。
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def ensure_lineage_schema(conn: Any) -> None:
    """创建谱系表（幂等）。永不抛出 —— 谱系为增强能力。"""
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_lineage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                child_id TEXT NOT NULL UNIQUE,
                parent_id TEXT NOT NULL,
                reason TEXT,
                created_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_session_lineage_parent "
            "ON session_lineage(parent_id, created_at)"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("session_lineage 建表失败: %s", exc)


def archive_prefix_in_transaction(
    cursor: Any,
    session_id: str,
    delete_message_ids: List[str],
    reason: str = "compaction",
    now_ms: Optional[int] = None,
) -> Optional[str]:
    """在**当前事务**内把待删除的前缀消息归档进派生会话。

    必须在 DELETE 执行前调用（复用同一 cursor/事务）。失败抛异常由
    调用方整体回滚 —— 与压缩同生共死。

    Returns:
        归档会话 id；delete_message_ids 为空时返回 None（无事可归档）。
    """
    if not delete_message_ids:
        return None
    now = int(time.time() * 1000) if now_ms is None else now_ms

    # 原会话标题（归档会话命名用）
    row = cursor.execute(
        "SELECT title FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    original_title = row[0] if row else "会话"

    # 归档会话行 —— is_archived=1 使其不混入正常会话列表；
    # metadata 记录 lineage 归属，前端可识别跳转。
    archive_session_id = str(uuid.uuid4())
    placeholders = ",".join("?" for _ in delete_message_ids)
    cursor.execute(
        "SELECT COUNT(*), MIN(created_at), MAX(created_at) FROM messages "
        f"WHERE id IN ({placeholders})",
        tuple(delete_message_ids),
    )
    msg_count, first_at, last_at = cursor.fetchone()

    metadata = json.dumps(
        {"lineage_archive_of": session_id, "reason": reason},
        ensure_ascii=False,
    )
    cursor.execute(
        """
        INSERT INTO sessions (id, title, created_at, updated_at,
                              message_count, metadata, is_archived)
        VALUES (?, ?, ?, ?, ?, ?, 1)
        """,
        (
            archive_session_id,
            f"{original_title} · 压缩归档",
            first_at if first_at is not None else now,
            now,
            msg_count or 0,
            metadata,
        ),
    )

    # 逐条复制消息行 —— **新消息 id**（原 id 随后将在原会话被 DELETE，
    # 若复用主键，DELETE 会连带删掉归档副本）；保留原 created_at 保序。
    for message_id in delete_message_ids:
        src = cursor.execute(
            "SELECT session_id, role, content, model, provider, tool_calls, "
            "tool_call_id, reasoning_content, created_at "
            "FROM messages WHERE id = ?",
            (message_id,),
        ).fetchone()
        if src is None:
            continue
        cursor.execute(
            """
            INSERT INTO messages (id, session_id, role, content, model, provider,
                                  tool_calls, tool_call_id, reasoning_content, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"msg-{uuid.uuid4().hex[:12]}",
                archive_session_id,
                src[1],  # role
                src[2],  # content
                src[3],
                src[4],
                src[5],
                src[6],
                src[7],
                src[8],  # created_at 原样保留 → 归档内 ORDER BY created_at 保序
            ),
        )

    # 谱系记录
    ensure_lineage_schema(cursor)
    cursor.execute(
        "INSERT INTO session_lineage (child_id, parent_id, reason, created_at) "
        "VALUES (?, ?, ?, ?)",
        (archive_session_id, session_id, reason, now),
    )
    logger.info(
        "压缩归档: %s 条消息 → 归档会话 %s (parent=%s)",
        msg_count,
        archive_session_id,
        session_id,
    )
    return archive_session_id


def list_archives(db: Any, session_id: str) -> List[Dict[str, Any]]:
    """列出某会话的全部压缩归档（新→旧）"""
    ensure_lineage_schema(db.get_connection())
    try:
        rows = db.get_connection().execute(
            """
            SELECT s.id, s.title, s.message_count, s.created_at, l.reason
            FROM session_lineage l
            JOIN sessions s ON s.id = l.child_id
            WHERE l.parent_id = ?
            ORDER BY l.created_at DESC
            """,
            (session_id,),
        ).fetchall()
        return [
            {
                "archive_session_id": r[0],
                "title": r[1],
                "message_count": r[2],
                "archived_at": r[3],
                "reason": r[4],
            }
            for r in rows
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("谱系查询失败: %s", exc)
        return []


def get_parent(db: Any, archive_session_id: str) -> Optional[str]:
    """归档会话 → 原会话 id；非归档会话返回 None"""
    try:
        row = db.get_connection().execute(
            "SELECT parent_id FROM session_lineage WHERE child_id = ?",
            (archive_session_id,),
        ).fetchone()
        return row[0] if row else None
    except Exception:  # noqa: BLE001
        return None
