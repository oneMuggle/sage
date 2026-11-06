"""Session Lineage - 压缩谱系 (Round 4, 对标 hermes-agent session lineage)

压缩（compaction）此前就地删除旧消息前缀，原文永久丢失。本模块在
删除前把前缀消息归档进一个派生会话（is_archived=1，不混入正常列表），
并记录 parent/child 谱系 —— 压缩前的完整对话永远可溯。

2026-11-05 非破坏性压缩后，主会话原文不再删除（``compacted_at`` 标记
保留展示），归档退化为兼容入口；启动迁移 ``restore_compacted_history``
把旧式「已删除」压缩的历史从归档回填回主会话（幂等，``needs_restore``）。

事务语义: 归档与压缩标记在同一事务（由 replace_prefix_with_continuation
的 cursor 驱动）——「历史已删、归档未写」与「历史已删、摘要未写」
同样是不可接受的永久丢失窗口（M4 CRITICAL-1 同哲学）。
"""

from __future__ import annotations

import json
import logging
import sqlite3
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
                -- 2026-11-05: 1 = 该归档来自旧式破坏性压缩，需回填主会话；
                -- 0 = 新式非破坏压缩（原文仍在主会话），或已回填完成。
                needs_restore INTEGER DEFAULT 1,
                created_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_session_lineage_parent "
            "ON session_lineage(parent_id, created_at)"
        )
        # 老库补列（双进程防御：并发 ALTER 后到者吞 duplicate column）
        try:
            cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(session_lineage)").fetchall()
            }
            if "needs_restore" not in cols:
                conn.execute(
                    "ALTER TABLE session_lineage "
                    "ADD COLUMN needs_restore INTEGER DEFAULT 1"
                )
        except sqlite3.OperationalError:  # noqa: BLE001 — 列已存在/并发迁移
            pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("session_lineage 建表失败: %s", exc)


def archive_prefix_in_transaction(
    cursor: Any,
    session_id: str,
    compacted_message_ids: List[str],
    reason: str = "compaction",
    now_ms: Optional[int] = None,
    *,
    needs_restore: bool,
) -> Optional[str]:
    """在**当前事务**内把待压缩的前缀消息归档进派生会话。

    必须在压缩标记写入前调用（复用同一 cursor/事务）。失败抛异常由
    调用方整体回滚 —— 与压缩同生共死。

    Args:
        needs_restore: True = 旧式破坏性压缩（原文已从主会话删除，启动
            回填需要它）；False = 新式非破坏压缩（原文仍在主会话），
            回填迁移跳过该归档，避免重复复制。

    Returns:
        归档会话 id；compacted_message_ids 为空时返回 None（无事可归档）。
    """
    if not compacted_message_ids:
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
    placeholders = ",".join("?" for _ in compacted_message_ids)
    cursor.execute(
        "SELECT COUNT(*), MIN(created_at), MAX(created_at) FROM messages "
        f"WHERE id IN ({placeholders})",
        tuple(compacted_message_ids),
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

    # 逐条复制消息行 —— **新消息 id**（旧式压缩中原 id 随后会被 DELETE，
    # 若复用主键，DELETE 会连带删掉归档副本）；保留原 created_at 保序。
    for message_id in compacted_message_ids:
        src = cursor.execute(
            "SELECT session_id, role, content, model, provider, tool_calls, "
            "tool_call_id, reasoning_content, step_index, created_at, client_meta "
            "FROM messages WHERE id = ?",
            (message_id,),
        ).fetchone()
        if src is None:
            continue
        cursor.execute(
            """
            INSERT INTO messages (id, session_id, role, content, model, provider,
                                  tool_calls, tool_call_id, reasoning_content, step_index, created_at, client_meta)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                src[8],  # step_index —— 2026-09 step-by-step：保留以便归档视图按步骤渲染
                src[9],  # created_at 原样保留 → 归档内 ORDER BY created_at 保序
                src[10],  # client_meta —— 用户消息引用信息随归档保留
            ),
        )

    # 谱系记录（needs_restore=0 表示无需启动回填：原文仍在主会话）
    ensure_lineage_schema(cursor)
    cursor.execute(
        "INSERT INTO session_lineage (child_id, parent_id, reason, needs_restore, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (archive_session_id, session_id, reason, 0 if not needs_restore else 1, now),
    )
    logger.info(
        "压缩归档: %s 条消息 → 归档会话 %s (parent=%s)",
        msg_count,
        archive_session_id,
        session_id,
    )
    return archive_session_id


def restore_compacted_history(db: Any) -> int:
    """把旧式破坏性压缩的归档前缀回填回主会话（启动迁移，幂等）。

    2026-11-05 之前的压缩会物理删除前缀（原文只存在于归档会话），
    会话页面因此看不到完整记录。本函数在启动迁移中把 ``needs_restore=1``
    的归档消息复制回父会话：

    - 新 id、保留原 ``created_at`` 保序；
    - ``compacted_at`` 记为谱系创建时间 —— 仅用于展示，不进入 LLM 上下文；
    - 不写 ``message.appended`` 事件：这些行不是模型可见历史，事件投影
      仍按 ``compaction.performed.deleted_ids`` 折叠原 id；
    - 回填后重算父会话 ``message_count`` 并置 ``needs_restore=0``。

    Args:
        db: ``Database`` 实例或 sqlite3 连接。

    Returns:
        实际回填的消息条数（重复调用返回 0）。
    """
    conn = db.get_connection() if hasattr(db, "get_connection") else db
    ensure_lineage_schema(conn)
    try:
        rows = conn.execute(
            "SELECT l.id, l.parent_id, l.child_id, l.created_at "
            "FROM session_lineage l "
            "JOIN sessions p ON p.id = l.parent_id "
            "WHERE l.reason = 'compaction' AND COALESCE(l.needs_restore, 0) = 1 "
            "ORDER BY l.created_at ASC"
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 — 回填是增强能力
        logger.warning("压缩回填扫描失败: %s", exc)
        return 0

    restored_total = 0
    for lineage_id, parent_id, child_id, lineage_created_at in rows:
        try:
            archived = conn.execute(
                "SELECT role, content, model, provider, tool_calls, tool_call_id, "
                "reasoning_content, step_index, created_at, client_meta "
                "FROM messages WHERE session_id = ? "
                "ORDER BY created_at ASC, rowid ASC",
                (child_id,),
            ).fetchall()
            restored_now = 0
            for m in archived:
                conn.execute(
                    "INSERT INTO messages (id, session_id, role, content, model, "
                    "provider, tool_calls, tool_call_id, reasoning_content, "
                    "step_index, created_at, client_meta, compacted_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"msg-{uuid.uuid4().hex[:12]}",
                        parent_id,
                        m[0],  # role
                        m[1],  # content
                        m[2],  # model
                        m[3],  # provider
                        m[4],  # tool_calls
                        m[5],  # tool_call_id
                        m[6],  # reasoning_content
                        m[7],  # step_index
                        m[8],  # created_at（原样保留 → 回到压缩前位置）
                        m[9],  # client_meta
                        lineage_created_at,
                    ),
                )
                restored_now += 1
            conn.execute(
                "UPDATE sessions SET message_count = "
                "(SELECT COUNT(*) FROM messages WHERE session_id = ?) WHERE id = ?",
                (parent_id, parent_id),
            )
            conn.execute(
                "UPDATE session_lineage SET needs_restore = 0 WHERE id = ?",
                (lineage_id,),
            )
            conn.commit()
            restored_total += restored_now
        except Exception as exc:  # noqa: BLE001 — 单条失败不阻断启动
            conn.rollback()
            logger.warning("压缩回填失败 (lineage=%s): %s", lineage_id, exc)
    if restored_total:
        logger.info("压缩历史回填完成: %s 条消息", restored_total)
    return restored_total


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
