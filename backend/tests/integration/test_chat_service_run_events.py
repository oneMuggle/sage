"""M1 结构化可观测性 — ChatService run-lifecycle 事件序列。

一次 run_turn 应产出 run_start → turn_start → (tool_result*) → run_end，
共享同一 run_id，seq 单调递增。
"""

from __future__ import annotations

from typing import List, Tuple
from unittest.mock import MagicMock

import pytest
from sage_core import Message, Role, ToolCall

from backend.adapters.out.llm.mock_adapter import MockLLMAdapter
from backend.adapters.out.metric.noop_adapter import NoopMetricAdapter
from backend.adapters.out.storage.memory_adapter import MemoryStorageAdapter
from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter
from backend.application.services.chat_service import ChatService

pytestmark = pytest.mark.integration


class _RecordingEvents:
    def __init__(self) -> None:
        self.calls: List[Tuple[str, dict]] = []

    def emit(self, event_type: str, payload: dict) -> None:
        self.calls.append((event_type, payload))

    def lifecycle(self) -> List[Tuple[str, dict]]:
        """只取带 run_id 的 run-lifecycle 事件。"""
        return [(t, p) for t, p in self.calls if isinstance(p, dict) and "run_id" in p]


def _make_service(events, llm_responses, tool_success=True):
    mock_tool = MagicMock()
    mock_tool.execute.return_value = MagicMock(
        success=tool_success, output="ok", error=None if tool_success else "boom"
    )
    mock_registry = MagicMock()
    mock_registry.list.return_value = []
    mock_registry.get.return_value = mock_tool
    return ChatService(
        llm=MockLLMAdapter(responses=llm_responses),
        tools=InprocToolAdapter(registry=mock_registry),
        skills=MagicMock(),
        storage=MemoryStorageAdapter(),
        metrics=NoopMetricAdapter(),
        events=events,
    )


@pytest.mark.asyncio()
async def test_run_turn_emits_run_start_turn_start_run_end():
    events = _RecordingEvents()
    svc = _make_service(events, [Message(role=Role.ASSISTANT, content="hi")])

    sid = await svc.create_session()
    await svc.run_turn(sid, Message(role=Role.USER, content="hello"))

    lc = events.lifecycle()
    types = [t for t, _ in lc]
    assert types[0] == "run_start"
    assert "turn_start" in types
    assert types[-1] == "run_end"

    # 同一 run_id
    run_ids = {p["run_id"] for _, p in lc}
    assert len(run_ids) == 1
    # seq 单调递增
    seqs = [p["seq"] for _, p in lc]
    assert seqs == sorted(seqs)
    assert seqs[0] == 0


@pytest.mark.asyncio()
async def test_run_turn_emits_tool_result_with_run_id():
    events = _RecordingEvents()
    tool_call_msg = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[ToolCall(name="echo", args={"text": "hi"}, id="call-1")],
    )
    svc = _make_service(events, [tool_call_msg])

    sid = await svc.create_session()
    await svc.run_turn(sid, Message(role=Role.USER, content="trigger"))

    lc = events.lifecycle()
    types = [t for t, _ in lc]
    assert "tool_result" in types
    # tool_result 带 run_id + 工具名
    tr = next(p for t, p in lc if t == "tool_result")
    assert tr["tool"] == "echo"
    assert tr["success"] is True
    assert "run_id" in tr
