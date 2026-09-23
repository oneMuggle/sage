# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""会话事件日志仓储（DSH 对标 R1，SE1）。

append-only 的会话事实源：``session_events`` 表只增不删（对标
deepseek-harness "Model-visible ⟺ logged"——凡进模型请求的内容必须
能从日志重建）。``messages`` 表是可变投影（compaction 会就地删行），
事件日志才是不可变底层。

事件词表（SE1 子集，见 docs/plans/2026-09-23_dsh-opt-round1-eventlog.md）：

- ``message.appended``：一条消息写入 messages 表（含投影所需全字段）；
- ``compaction.performed``：一次前缀压缩（deleted_ids + 续接消息）。

两种写入入口：

- :meth:`SessionEventRepository.append` —— 独立事务（适合离线补写）；
- :meth:`SessionEventRepository.append_with_cursor` —— **同事务**追加
  （传入调用方已有 cursor，与业务写同一 commit；session_repo 三咽喉点
  双写走这里，保证事件与消息同生共死）。

读取入口投影侧只用 :meth:`get_by_session`（按 seq 升序全量回放）。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from backend.data.database import get_database

logger = logging.getLogger(__name__)

# ---- 事件词表 ---------------------------------------------------------------

#: 一条消息写入 messages 表。payload 携带投影所需全字段：
#: ``{id, role, content, subtype, segment_id, tool_calls, created_at}``
EVENT_MESSAGE_APPENDED = "message.appended"

#: 一次前缀压缩。payload：
#: ``{deleted_ids: [str], continuation_id: str, removed_count: int, reason: str}``
EVENT_COMPACTION_PERFORMED = "compaction.performed"

#: 一条消息从 messages 表删除（含段回退删除的 separator）。
#: payload：``{id: str, reason: str}``（reason: "message_delete" / "segment_retreat"）。
#: 已知边界（SE2 收口）：``delete_by_session`` 与 fork_session 的
#: 原始 SQL 路径本轮不落事件。
EVENT_MESSAGE_DELETED = "message.deleted"


@dataclass
class SessionEvent:
    """session_events 行的内存表示。"""

    id: int
    session_id: str
    seq: int
    type: str
    payload: Optional[Dict[str, Any]]
    surface_op: Optional[Dict[str, Any]]
    created_at: int

    @classmethod
    def from_row(cls, row: Any) -> SessionEvent:
        def _load_json(raw: Any) -> Optional[Dict[str, Any]]:
            if raw is None:
                return None
            try:
                value = json.loads(raw)
            except (ValueError, TypeError):
                return None
            return value if isinstance(value, dict) else None

        return cls(
            id=row["id"],
            session_id=row["session_id"],
            seq=row["seq"],
            type=row["type"],
            payload=_load_json(row["payload"]),
            surface_op=_load_json(row["surface_op"]),
            created_at=row["created_at"],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "seq": self.seq,
            "type": self.type,
            "payload": self.payload,
            "surface_op": self.surface_op,
            "created_at": self.created_at,
        }


class SessionEventRepository:
    """会话事件日志仓储（append-only）。

    仓储层**不提供** delete / update —— append-only 是本表的契约，
    删除入口不存在，调用方想删也删不到。
    """

    def __init__(self):
        self.db = get_database()

    # ---- 同事务写入（session_repo 双写钩子走这里） --------------------------

    @staticmethod
    def append_with_cursor(
        cursor: Any,
        session_id: str,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        surface_op: Optional[Dict[str, Any]] = None,
        created_at: Optional[int] = None,
    ) -> int:
        """在调用方的**未提交事务**里追加一条事件，返回分配的 seq。

        seq = 该会话当前最大 seq + 1；SQLite 单写者语义下同事务内
        读-改-写不会被并发插入撕开（messages 写入本就串行提交）。
        任何 SQL 失败向上抛 —— 由调用方决定降级（session_repo 钩子
        捕获后仅告警，不阻断业务写）。
        """
        now_ms = int(created_at if created_at is not None else time.time() * 1000)
        cursor.execute(
            "SELECT COALESCE(MAX(seq), 0) AS max_seq FROM session_events "
            "WHERE session_id = ?",
            (session_id,),
        )
        row = cursor.fetchone()
        max_seq = row["max_seq"] if row is not None else 0
        cursor.execute(
            "INSERT INTO session_events (session_id, seq, type, payload, surface_op, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                session_id,
                max_seq + 1,
                event_type,
                _dump_json(payload),
                _dump_json(surface_op),
                now_ms,
            ),
        )
        return max_seq + 1

    # ---- 独立事务写入 -------------------------------------------------------

    def append(
        self,
        session_id: str,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        surface_op: Optional[Dict[str, Any]] = None,
        created_at: Optional[int] = None,
    ) -> int:
        """独立事务追加一条事件（离线补写 / 测试用）。返回分配的 seq。"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            seq = self.append_with_cursor(
                cursor,
                session_id,
                event_type,
                payload=payload,
                surface_op=surface_op,
                created_at=created_at,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return seq

    # ---- 读取（投影侧唯一入口） ---------------------------------------------

    def get_by_session(self, session_id: str, limit: int = 100000) -> List[SessionEvent]:
        """按 seq 升序取会话全部事件（默认上限 10 万条，与
        MessageRepository.get_by_session 同量级口径）。"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, session_id, seq, type, payload, surface_op, created_at "
            "FROM session_events WHERE session_id = ? ORDER BY seq ASC LIMIT ?",
            (session_id, limit),
        )
        return [SessionEvent.from_row(row) for row in cursor.fetchall()]

    def count_by_session(self, session_id: str) -> int:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) AS n FROM session_events WHERE session_id = ?",
            (session_id,),
        )
        row = cursor.fetchone()
        return int(row["n"]) if row is not None else 0

    def latest_seq(self, session_id: str) -> int:
        """会话当前最大 seq；无事件返回 0。"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COALESCE(MAX(seq), 0) AS max_seq FROM session_events "
            "WHERE session_id = ?",
            (session_id,),
        )
        row = cursor.fetchone()
        return int(row["max_seq"]) if row is not None else 0


def _dump_json(value: Optional[Dict[str, Any]]) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


__all__ = [
    "EVENT_COMPACTION_PERFORMED",
    "EVENT_MESSAGE_APPENDED",
    "SessionEvent",
    "SessionEventRepository",
]
