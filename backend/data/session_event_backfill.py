# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""存量会话事件回填（DSH 对标 R2，SE2）。

SE1 落地前的历史会话没有 ``session_events`` 记录 —— 读取切换
（history_context → 事件投影）会让老会话"失忆"。本模块在启动时把
存量 messages 行补写成 ``message.appended`` 事件，使事件日志对全部
会话成立。

幂等纪律：**会话内有任何事件即整体跳过**（NOT EXISTS 语义）——
回填只服务于"SE1 之前的存量数据"，与运行期双写不交叉。

对调用方 fail-safe：任何失败由调用方决定降级（lifespan 内仅告警，
回填失败不阻断启动）。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from backend.data.database import get_database

logger = logging.getLogger(__name__)


def backfill_session_events(db: Any = None) -> Dict[str, int]:
    """给没有事件的存量会话补写 message.appended 事件。

    Returns:
        ``{"sessions_scanned", "sessions_backfilled", "events_written"}``。
    """
    database = db if db is not None else get_database()
    conn = database.get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT DISTINCT m.session_id AS sid
        FROM messages m
        WHERE NOT EXISTS (
            SELECT 1 FROM session_events e WHERE e.session_id = m.session_id
        )
        """
    )
    session_ids = [row["sid"] for row in cursor.fetchall()]

    written = 0
    backfilled = 0
    failed_sessions = 0
    for sid in session_ids:
        try:
            cursor.execute(
                """
                SELECT id, role, content, tool_calls, segment_id, subtype, created_at
                FROM messages
                WHERE session_id = ?
                ORDER BY created_at ASC, rowid ASC
                """,
                (sid,),
            )
            rows = cursor.fetchall()
            if not rows:
                continue
            backfilled += 1
            for seq, row in enumerate(rows, start=1):
                cursor.execute(
                    "INSERT INTO session_events (session_id, seq, type, payload, created_at) "
                    "VALUES (?, ?, 'message.appended', ?, ?)",
                    (
                        sid,
                        seq,
                        json.dumps(
                            {
                                "id": row["id"],
                                "role": row["role"],
                                "content": row["content"],
                                "subtype": row["subtype"],
                                "segment_id": row["segment_id"],
                                "tool_calls": row["tool_calls"],
                                "created_at": row["created_at"],
                            },
                            ensure_ascii=False,
                            default=str,
                        ),
                        row["created_at"],
                    ),
                )
                written += 1
            conn.commit()
        except Exception:
            # A3: 单会话失败不污染全局事务 —— rollback 当前 session 的未完成写入，
            # 继续处理后续会话。避免 SQLite WAL 模式下未回滚事务持有 RESERVED 锁，
            # 阻塞后续所有数据库操作（database is locked 连锁故障）。
            failed_sessions += 1
            logger.warning(
                "会话事件回填跳过 session_id=%s（%d 条消息），事务已回滚",
                sid,
                len(rows) if "rows" in locals() else 0,
                exc_info=True,
            )
            try:
                conn.rollback()
            except Exception:
                logger.error("rollback failed for session_id=%s", sid, exc_info=True)

    result = {
        "sessions_scanned": len(session_ids),
        "sessions_backfilled": backfilled,
        "events_written": written,
    }
    if backfilled:
        logger.info(
            "会话事件回填完成：%s 个会话 / %s 条事件",
            result["sessions_backfilled"],
            written,
        )
    return result


__all__ = ["backfill_session_events"]
