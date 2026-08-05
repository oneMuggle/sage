"""ChatService memory_retrieval gating (final-review Important-2).

The Settings UI promises a "记忆检索注入" toggle that controls whether
relevant memories are injected into the LLM context. Before this fix the
second toggle shared the ``auto_memory`` IPC key with "自动记忆沉淀", so
flipping it also disabled fact extraction. This test locks the NEW
independent gate:

- with a lifecycle present + ``is_memory_retrieval_enabled()`` False →
  ``memory.retrieve`` is NOT called (no injection),
- with the gate True → ``memory.retrieve`` IS called,
- legacy path (no lifecycle) → retrieval stays enabled (backward compat),
- gate read failure → fail-open (retrieval still runs, never breaks turn).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from backend.application.services.chat_service import ChatService
from backend.domain.memory import MemoryContext
from backend.domain.message import Message, Role
from backend.ports.memory import MemoryPort

pytestmark = pytest.mark.unit


def _build_chat_service(memory_obj, lifecycle=None):
    """Build a ChatService with the given memory object and optional lifecycle."""
    llm = Mock()
    llm.chat = AsyncMock(
        return_value=Message(
            role=Role.ASSISTANT,
            content="好的，我理解了。",
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
        lifecycle=lifecycle,
    )


def _memory_with_retrieve():
    memory = Mock(spec=MemoryPort)
    memory.retrieve = AsyncMock(
        return_value=MemoryContext(working=[], episodic=[], semantic=[])
    )
    memory.store = AsyncMock(return_value="memory-id")
    memory.compress = AsyncMock()
    return memory


def _mock_lifecycle(retrieval_enabled: bool):
    lifecycle = Mock()
    lifecycle.set_current_turn = Mock()
    lifecycle.is_memory_retrieval_enabled = AsyncMock(return_value=retrieval_enabled)
    lifecycle.on_turn_complete = AsyncMock()
    return lifecycle


@pytest.mark.asyncio()
async def test_retrieval_skipped_when_lifecycle_disables_retrieval():
    """memory_retrieval=false → memory.retrieve must NOT be called."""
    memory = _memory_with_retrieve()
    lifecycle = _mock_lifecycle(retrieval_enabled=False)

    svc = _build_chat_service(memory, lifecycle=lifecycle)
    await svc.run_turn("session-1", Message(role=Role.USER, content="hi"))

    lifecycle.is_memory_retrieval_enabled.assert_awaited()
    memory.retrieve.assert_not_called()


@pytest.mark.asyncio()
async def test_retrieval_runs_when_lifecycle_enables_retrieval():
    """memory_retrieval=true (default) → memory.retrieve IS called."""
    memory = _memory_with_retrieve()
    lifecycle = _mock_lifecycle(retrieval_enabled=True)

    svc = _build_chat_service(memory, lifecycle=lifecycle)
    await svc.run_turn("session-1", Message(role=Role.USER, content="hi"))

    lifecycle.is_memory_retrieval_enabled.assert_awaited()
    memory.retrieve.assert_awaited_once()


@pytest.mark.asyncio()
async def test_retrieval_runs_on_legacy_path_without_lifecycle():
    """No lifecycle → retrieval stays enabled (backward compat)."""
    memory = _memory_with_retrieve()

    svc = _build_chat_service(memory, lifecycle=None)
    await svc.run_turn("session-1", Message(role=Role.USER, content="hi"))

    memory.retrieve.assert_awaited_once()


@pytest.mark.asyncio()
async def test_retrieval_gate_read_failure_falls_open():
    """is_memory_retrieval_enabled() raises → the turn must NOT break
    (retrieval is skipped with a warning; the LLM turn completes)."""
    memory = _memory_with_retrieve()
    lifecycle = Mock()
    lifecycle.set_current_turn = Mock()
    lifecycle.is_memory_retrieval_enabled = AsyncMock(
        side_effect=RuntimeError("db locked")
    )
    lifecycle.on_turn_complete = AsyncMock()

    svc = _build_chat_service(memory, lifecycle=lifecycle)
    result = await svc.run_turn("session-1", Message(role=Role.USER, content="hi"))

    # the turn completed and produced an assistant reply (never broken)
    assert len(result) == 2
    assert result[1].role == Role.ASSISTANT
    # the gate failure simply skipped retrieval (warned, not raised)
    lifecycle.is_memory_retrieval_enabled.assert_awaited()
