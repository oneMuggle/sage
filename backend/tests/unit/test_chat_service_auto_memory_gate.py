"""ChatService auto_memory gating (Task 2 — Gap B).

When ChatService.memory exposes ``is_auto_memory_enabled()`` (i.e. it is
wrapped by MemoryLifecycleManager), the run should:
- skip _extract_and_store_memory and compress when the gate is False
- still call them when the gate is True

When the memory attribute is a plain MemoryPort (legacy path), the gate
must not change behavior.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from backend.application.services.chat_service import ChatService
from backend.domain.memory import MemoryContext
from backend.domain.message import Message, Role
from backend.ports.memory import MemoryPort

pytestmark = pytest.mark.unit


def _build_chat_service(memory_obj):
    """Build a ChatService with the given memory object (lifecycle wrapper or Mock)."""
    llm = Mock()
    llm.chat = AsyncMock(
        return_value=Message(
            role=Role.ASSISTANT,
            content=(
                "好的,我理解您想吃火锅。成都确实有很多不错的火锅店,"
                "海底捞是一个很好的选择,服务一流,人均150元。"
            ),
        )
    )
    tools = Mock()
    tools.list_tools = Mock(return_value=[])
    storage = Mock()
    storage.append_message = AsyncMock()
    storage.get_messages = AsyncMock(return_value=[])
    metrics = Mock()
    metrics.counter = Mock()
    metrics.histogram = Mock()
    metrics.gauge = Mock()
    events = Mock()
    events.emit = Mock()
    return ChatService(
        llm=llm,
        tools=tools,
        skills=None,
        storage=storage,
        metrics=metrics,
        events=events,
        memory=memory_obj,
    )


@pytest.mark.asyncio()
async def test_chat_service_skips_extraction_when_auto_memory_disabled():
    """When lifecycle.is_auto_memory_enabled() returns False, no store/compress happens."""
    memory = Mock(spec=MemoryPort)
    memory.is_auto_memory_enabled = AsyncMock(return_value=False)
    memory.retrieve = AsyncMock(return_value=MemoryContext(working=[], episodic=[], semantic=[]))
    memory.store = AsyncMock(return_value="memory-id")
    memory.compress = AsyncMock()

    svc = _build_chat_service(memory)
    user_message = Message(role=Role.USER, content="测试消息")
    await svc.run_turn("session-1", user_message)

    memory.is_auto_memory_enabled.assert_awaited()
    memory.store.assert_not_called()
    memory.compress.assert_not_called()


@pytest.mark.asyncio()
async def test_chat_service_runs_extraction_when_auto_memory_enabled():
    """When lifecycle.is_auto_memory_enabled() returns True, compress happens (extraction is content-gated)."""
    memory = Mock(spec=MemoryPort)
    memory.is_auto_memory_enabled = AsyncMock(return_value=True)
    memory.retrieve = AsyncMock(return_value=MemoryContext(working=[], episodic=[], semantic=[]))
    memory.store = AsyncMock(return_value="memory-id")
    memory.compress = AsyncMock()

    svc = _build_chat_service(memory)
    user_message = Message(role=Role.USER, content="测试")
    await svc.run_turn("session-1", user_message)

    memory.is_auto_memory_enabled.assert_awaited()
    memory.compress.assert_awaited_once_with("session-1")


@pytest.mark.asyncio()
async def test_chat_service_legacy_memory_path_is_unchanged():
    """When memory has no is_auto_memory_enabled, gate is bypassed entirely."""
    # Plain MemoryPort mock — no is_auto_memory_enabled attribute.
    memory = Mock(spec=MemoryPort)
    # Explicitly ensure the attr does NOT exist (Mock(spec=...) honors the spec).
    assert not hasattr(memory, "is_auto_memory_enabled")
    memory.retrieve = AsyncMock(return_value=MemoryContext(working=[], episodic=[], semantic=[]))
    memory.store = AsyncMock(return_value="memory-id")
    memory.compress = AsyncMock()

    svc = _build_chat_service(memory)
    user_message = Message(role=Role.USER, content="测试")
    await svc.run_turn("session-1", user_message)

    # Legacy path: compress still called every turn (was true before T2 too).
    memory.compress.assert_awaited_once_with("session-1")


@pytest.mark.asyncio()
async def test_chat_service_gate_read_failure_falls_open():
    """If is_auto_memory_enabled() raises, treat as True (don't break ChatService)."""
    memory = Mock(spec=MemoryPort)
    memory.is_auto_memory_enabled = AsyncMock(side_effect=RuntimeError("db locked"))
    memory.retrieve = AsyncMock(return_value=MemoryContext(working=[], episodic=[], semantic=[]))
    memory.store = AsyncMock(return_value="memory-id")
    memory.compress = AsyncMock()

    svc = _build_chat_service(memory)
    user_message = Message(role=Role.USER, content="测试")
    await svc.run_turn("session-1", user_message)

    # compress should still run (fail-open).
    memory.compress.assert_awaited_once_with("session-1")