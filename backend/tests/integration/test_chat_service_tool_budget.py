"""M2 显式限制 — ChatService 工具调用预算守卫。

- 一次 run_turn 中 tool_call 数量超 ``policy.max_tool_calls_per_run`` → 提前停止并发
  ``run_end(status="tool_budget_exceeded")``。
- 不超额 → 正常 ``run_end(status="ok")``。
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
from backend.domain.tool_policy import ToolPolicy

pytestmark = pytest.mark.integration


class _RecordingEvents:
    def __init__(self) -> None:
        self.calls: List[Tuple[str, dict]] = []

    def emit(self, event_type: str, payload: dict) -> None:
        self.calls.append((event_type, payload))

    def lifecycle(self) -> List[Tuple[str, dict]]:
        return [(t, p) for t, p in self.calls if isinstance(p, dict) and "run_id" in p]


def _make_service(events, tool_calls_per_response, policy: ToolPolicy):
    """构造 ChatService，LLM 一次返回 N 个 tool_calls。"""
    tool_call_msg = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[
            ToolCall(name=f"echo_{i}", args={"text": str(i)}, id=f"call-{i}")
            for i in range(tool_calls_per_response)
        ],
    )
    mock_tool = MagicMock()
    mock_tool.execute.return_value = MagicMock(success=True, output="ok", error=None)
    mock_registry = MagicMock()
    mock_registry.list.return_value = []
    mock_registry.get.return_value = mock_tool
    return ChatService(
        llm=MockLLMAdapter(responses=[tool_call_msg]),
        tools=InprocToolAdapter(registry=mock_registry, policy=policy),
        skills=MagicMock(),
        storage=MemoryStorageAdapter(),
        metrics=NoopMetricAdapter(),
        events=events,
        tool_policy=policy,
    )


@pytest.mark.asyncio()
async def test_tool_budget_exceeded_stops_execution_and_emits_status():
    """5 个 tool_calls + max_tool_calls_per_run=3 → 仅执行 3 次 + run_end status=tool_budget_exceeded。"""
    events = _RecordingEvents()
    policy = ToolPolicy(max_tool_calls_per_run=3)
    svc = _make_service(events, tool_calls_per_response=5, policy=policy)

    sid = await svc.create_session()
    await svc.run_turn(sid, Message(role=Role.USER, content="go"))

    lc = events.lifecycle()
    types = [t for t, _ in lc]
    # 最后一条 lifecycle 事件应为 run_end
    assert types[-1] == "run_end"
    # run_end payload status 字段为 tool_budget_exceeded
    last_payload = lc[-1][1]
    assert last_payload["status"] == "tool_budget_exceeded"
    # tool_result 事件的数量 == 3（预算上限），不再有第 4/5 次
    tool_results = [p for t, p in lc if t == "tool_result"]
    assert len(tool_results) == 3


@pytest.mark.asyncio()
async def test_tool_budget_not_exceeded_normal_status_ok():
    """2 个 tool_calls + max_tool_calls_per_run=3 → 正常 + run_end status=ok。"""
    events = _RecordingEvents()
    policy = ToolPolicy(max_tool_calls_per_run=3)
    svc = _make_service(events, tool_calls_per_response=2, policy=policy)

    sid = await svc.create_session()
    await svc.run_turn(sid, Message(role=Role.USER, content="go"))

    lc = events.lifecycle()
    last_payload = lc[-1][1]
    assert last_payload["status"] == "ok"
    tool_results = [p for t, p in lc if t == "tool_result"]
    assert len(tool_results) == 2


@pytest.mark.asyncio()
async def test_tool_budget_zero_blocks_all_tool_calls():
    """max_tool_calls_per_run=0 → 一次 tool_call 也不执行，run_end status=tool_budget_exceeded。"""
    events = _RecordingEvents()
    policy = ToolPolicy(max_tool_calls_per_run=0)
    svc = _make_service(events, tool_calls_per_response=2, policy=policy)

    sid = await svc.create_session()
    await svc.run_turn(sid, Message(role=Role.USER, content="go"))

    lc = events.lifecycle()
    last_payload = lc[-1][1]
    assert last_payload["status"] == "tool_budget_exceeded"
    tool_results = [p for t, p in lc if t == "tool_result"]
    assert len(tool_results) == 0
