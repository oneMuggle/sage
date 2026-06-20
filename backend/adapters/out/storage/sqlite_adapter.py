"""SQLite 存储 adapter（生产实现）。

把现有 ``backend.data.session_repo`` 包装为 ``StoragePort`` 协议实现，
完成 ``domain.Message`` ↔ 持久化层 ``data.Message``（带 id/timestamps）互转。

设计要点
--------

- **不改持久化层**：保留 ``SessionRepository`` / ``MessageRepository`` 与
  ``Database`` 不动；adapter 只做翻译 + 装配 id/timestamps。
- **直接调用同步方法**而不额外套 ``asyncio.to_thread``：FastAPI handler 已经
  处于事件循环，SQLite 同步调用在线程内非阻塞且不耗 IO 等待；为追求透明、未来
  切到线程池或 async driver 时再换。
- **tool_calls 持久化格式**：list → JSON 字符串（与既有 messages.tool_calls
  TEXT 字段一致），读取时反序列化。
- **list_sessions**：返回 ``[{"id", "title", "message_count", ...}]`` 形式字典
  列表；与 ``MemoryStorageAdapter`` 的 dict 形状对齐。
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from backend.data.session_repo import (
    Message as _DataMessage,
    MessageRepository,
    SessionRepository,
)
from sage_core import Message, Role, ToolCall
from sage_core.repositories import StoragePort  # noqa: F401  (structural typing target)

_DEFAULT_TITLE = "新对话"


# ============================================================================
# 双向转换辅助
# ============================================================================


def _serialize_tool_calls(tool_calls: list[ToolCall]) -> str | None:
    """``[ToolCall, ...]`` → JSON 字符串（与 messages.tool_calls TEXT 列兼容）。"""
    if not tool_calls:
        return None
    return json.dumps(
        [{"name": tc.name, "args": tc.args, "id": tc.id} for tc in tool_calls],
        ensure_ascii=False,
    )


def _deserialize_tool_calls(raw: str | None) -> list[ToolCall]:
    """messages.tool_calls JSON 字符串 → ``[ToolCall, ...]``；非法 JSON 降级为 ``[]``。"""
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(items, list):
        return []
    out: list[ToolCall] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        out.append(
            ToolCall(
                name=str(it.get("name", "")),
                args=dict(it.get("args", {})) if isinstance(it.get("args"), dict) else {},
                id=it.get("id"),
            )
        )
    return out


def _domain_to_data_message(session_id: str, msg: Message) -> _DataMessage:
    """``domain.Message`` → 持久化层 ``data.Message``（自动补 id/timestamp）。"""
    role = msg.role.value if isinstance(msg.role, Role) else str(msg.role)
    return _DataMessage(
        id=str(uuid.uuid4()),
        session_id=session_id,
        role=role,
        content=msg.content,
        created_at=int(time.time() * 1000),
        tool_calls=_serialize_tool_calls(msg.tool_calls),
        tool_call_id=msg.tool_call_id,
    )


def _data_to_domain_message(row: _DataMessage) -> Message:
    """持久化层 ``data.Message`` → ``domain.Message``。"""
    try:
        role = Role(row.role)
    except ValueError:
        role = Role.ASSISTANT
    return Message(
        role=role,
        content=row.content or "",
        tool_calls=_deserialize_tool_calls(row.tool_calls),
        tool_call_id=row.tool_call_id,
    )


# ============================================================================
# Adapter
# ============================================================================


class SqliteStorageAdapter:
    """``StoragePort`` 的 SQLite 实现（生产）。

    采用结构化子类型（structural typing）：不显式继承 ``StoragePort``，
    仅通过方法签名匹配来满足协议。与 LLM 适配器保持一致。
    """

    def __init__(
        self,
        session_repo: SessionRepository | None = None,
        message_repo: MessageRepository | None = None,
    ) -> None:
        # 默认使用全局仓储（向后兼容）；依赖注入便于单测替换。
        self._sessions: SessionRepository = session_repo or SessionRepository()
        self._messages: MessageRepository = message_repo or MessageRepository()

    # ----- 会话 -----

    async def create_session(self, title: str = "") -> str:
        """创建新会话，返回会话 ID。

        备注：``SessionRepository.create`` 不接受空字符串标题，这里统一
        替换为 ``"新对话"`` 默认值。
        """
        safe_title = title if title else _DEFAULT_TITLE
        session = self._sessions.create(title=safe_title)
        # 显式 str()：SessionRepository 在非 strict 模块，session.id 被推断为 Any
        return str(session.id)

    async def list_sessions(self) -> list[dict[str, Any]]:
        """列出当前所有会话（已过滤归档），返回 dict 列表。"""
        sessions = self._sessions.list(limit=1000, offset=0)
        return [
            {
                "id": s.id,
                "title": s.title,
                "message_count": s.message_count,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
                "is_pinned": bool(s.is_pinned),
            }
            for s in sessions
        ]

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """按 ID 取单个会话;不存在返 ``None``。"""
        s = self._sessions.get(session_id)
        if s is None:
            return None
        return {
            "id": s.id,
            "title": s.title,
            "message_count": s.message_count,
            "created_at": s.created_at,
            "updated_at": s.updated_at,
            "is_pinned": bool(s.is_pinned),
        }

    async def update_session(self, session_id: str, **fields: Any) -> int:
        """局部更新;返受影响行数(0=不存在,1=已更新)。

        ``is_pinned`` 字段是 bool,持久化层需要 0/1 int,这里做转换。
        其他字段(如 ``title``)原样转发。
        """
        kwargs: dict[str, Any] = {}
        if "title" in fields and fields["title"] is not None:
            kwargs["title"] = fields["title"]
        if "is_pinned" in fields and fields["is_pinned"] is not None:
            kwargs["is_pinned"] = 1 if fields["is_pinned"] else 0
        if not kwargs:
            # 没有任何字段要更新:走一遍 get 让调用方拿到当前快照,但返 1
            # (语义:会话存在,所以"更新请求"被受理;若不存在,get 返 None)
            return 1 if self._sessions.get(session_id) is not None else 0
        return 1 if self._sessions.update(session_id, **kwargs) else 0

    async def delete_session(self, session_id: str) -> int:
        """按 ID 删除会话;返受影响行数(0=不存在,1=已删除)。"""
        return 1 if self._sessions.delete(session_id) else 0

    # ----- 消息 -----

    async def append_message(self, session_id: str, message: Message) -> None:
        """向会话追加一条消息（自动补 id/timestamp）。"""
        row = _domain_to_data_message(session_id, message)
        self._messages.save(row)

    async def get_messages(
        self,
        session_id: str,
        limit: int = 50,
    ) -> list[Message]:
        """按时间正序获取会话的最新若干条消息。

        实现：先取全部历史，然后取尾部 ``limit`` 条并保持时间正序。
        """
        if limit <= 0:
            return []
        # 先用较大窗口把会话消息取回来（按 created_at ASC 升序）
        history = self._messages.get_by_session(session_id, limit=10_000, offset=0)
        if len(history) > limit:
            history = history[-limit:]
        return [_data_to_domain_message(row) for row in history]
