"""验证 ``MemoryStorageAdapter`` 行为。

覆盖 ``StoragePort`` 的 5 个方法（``create_session`` / ``list_sessions`` /
``delete_session`` / ``append_message`` / ``get_messages``）以及部分边界
场景：空会话、未知会话、limit 截断、tool_calls 序列化等。
"""

from __future__ import annotations

import pytest

from backend.adapters.out.storage.memory_adapter import MemoryStorageAdapter
from backend.domain.message import Message, Role, ToolCall
from backend.ports.storage import StoragePort

pytestmark = pytest.mark.unit


# ============================================================================
# 1) 创建/列出/删除 会话
# ============================================================================


async def test_create_session_returns_unique_id() -> None:
    storage = MemoryStorageAdapter()
    sid1 = await storage.create_session(title="first")
    sid2 = await storage.create_session(title="second")
    assert sid1 != sid2
    # 默认 id 形如 mem-1/mem-2（counter 自增）
    assert sid1.startswith("mem-")
    assert sid2.startswith("mem-")


async def test_create_and_list_session() -> None:
    storage = MemoryStorageAdapter()
    sid = await storage.create_session(title="test session")
    sessions = await storage.list_sessions()
    assert any(s["id"] == sid and s["title"] == "test session" for s in sessions)


async def test_list_sessions_empty() -> None:
    storage = MemoryStorageAdapter()
    sessions = await storage.list_sessions()
    assert sessions == []


async def test_delete_session_removes_from_list() -> None:
    storage = MemoryStorageAdapter()
    sid = await storage.create_session(title="to-delete")
    assert any(s["id"] == sid for s in await storage.list_sessions())
    await storage.delete_session(sid)
    assert all(s["id"] != sid for s in await storage.list_sessions())


async def test_delete_unknown_session_is_noop() -> None:
    storage = MemoryStorageAdapter()
    # 不应抛错
    await storage.delete_session("does-not-exist")


# ============================================================================
# 2) append / get 消息
# ============================================================================


async def test_append_and_get_messages() -> None:
    storage = MemoryStorageAdapter()
    sid = await storage.create_session()
    msg = Message(role=Role.USER, content="hello")
    await storage.append_message(sid, msg)
    msgs = await storage.get_messages(sid)
    assert len(msgs) == 1
    assert msgs[0].content == "hello"
    assert msgs[0].role == Role.USER


async def test_get_messages_limit_returns_most_recent() -> None:
    storage = MemoryStorageAdapter()
    sid = await storage.create_session()
    for i in range(10):
        await storage.append_message(sid, Message(role=Role.USER, content=f"msg{i}"))
    msgs = await storage.get_messages(sid, limit=3)
    assert len(msgs) == 3
    # 末尾 limit 条，按时间正序
    assert [m.content for m in msgs] == ["msg7", "msg8", "msg9"]


async def test_get_messages_unknown_session_returns_empty() -> None:
    storage = MemoryStorageAdapter()
    msgs = await storage.get_messages("nonexistent")
    assert msgs == []


async def test_get_messages_limit_larger_than_history() -> None:
    storage = MemoryStorageAdapter()
    sid = await storage.create_session()
    await storage.append_message(sid, Message(role=Role.USER, content="only"))
    msgs = await storage.get_messages(sid, limit=999)
    assert len(msgs) == 1
    assert msgs[0].content == "only"


async def test_get_messages_limit_zero_returns_empty() -> None:
    storage = MemoryStorageAdapter()
    sid = await storage.create_session()
    await storage.append_message(sid, Message(role=Role.USER, content="x"))
    assert await storage.get_messages(sid, limit=0) == []


async def test_append_to_unknown_session_autocreates() -> None:
    """未显式 create_session 的 session_id 在 append 时自动建空会话。"""
    storage = MemoryStorageAdapter()
    await storage.append_message("ghost", Message(role=Role.USER, content="hi"))
    msgs = await storage.get_messages("ghost")
    assert len(msgs) == 1
    assert msgs[0].content == "hi"


async def test_delete_session_cascades_messages() -> None:
    storage = MemoryStorageAdapter()
    sid = await storage.create_session()
    await storage.append_message(sid, Message(role=Role.USER, content="x"))
    await storage.delete_session(sid)
    assert await storage.get_messages(sid) == []


# ============================================================================
# 3) tool_calls / tool_call_id 往返
# ============================================================================


async def test_append_message_with_tool_calls_preserved() -> None:
    storage = MemoryStorageAdapter()
    sid = await storage.create_session()
    assistant = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[ToolCall(name="search", args={"q": "weather"}, id="call_1")],
    )
    await storage.append_message(sid, assistant)
    tool_msg = Message(
        role=Role.TOOL,
        content="sunny",
        tool_call_id="call_1",
    )
    await storage.append_message(sid, tool_msg)

    msgs = await storage.get_messages(sid)
    assert len(msgs) == 2
    assert msgs[0].role == Role.ASSISTANT
    assert len(msgs[0].tool_calls) == 1
    tc = msgs[0].tool_calls[0]
    assert tc.name == "search"
    assert tc.args == {"q": "weather"}
    assert tc.id == "call_1"
    assert msgs[1].role == Role.TOOL
    assert msgs[1].content == "sunny"
    assert msgs[1].tool_call_id == "call_1"


# ============================================================================
# 4) 结构性子类型（Protocol 契约）
# ============================================================================


def test_satisfies_storage_port_protocol() -> None:
    """``MemoryStorageAdapter`` 必须结构化满足 ``StoragePort``。"""
    storage: StoragePort = MemoryStorageAdapter()
    assert isinstance(storage, MemoryStorageAdapter)
