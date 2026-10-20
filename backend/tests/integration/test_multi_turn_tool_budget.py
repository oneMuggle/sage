"""多轮长时间任务的工具调用预算守卫（回归测试）。

背景：单 run 工具调用总数上限原为 25，长时间多轮任务在第 25 次被提前终止
（``run_end(status="tool_budget_exceeded")``）。默认已提高到 100，且 UI
（OrchSettings）可实时覆盖。此文件锁定四件事：

1. 默认预算下 30 轮多工具任务能完整跑完（不再在 25 处被切）。
2. UI 设置的预算能覆盖"仍是默认值的 policy 快照"——这是魔法哨兵回归：
   曾经用 ``policy_budget == 25`` 判断"是否默认"，默认值一改该判断永远为假，
   UI 里设的预算被静默忽略。
3. 显式设定的 policy 预算不被 UI 覆盖。
4. 0 不是"不限"：UI 侧 0 回落默认值；policy 侧 0 阻断全部工具调用。
"""

from __future__ import annotations

from typing import List, Tuple
from unittest.mock import AsyncMock, MagicMock

import pytest
from sage_core import Message, Role, ToolCall

from backend.adapters.out.llm.mock_adapter import MockLLMAdapter
from backend.adapters.out.metric.noop_adapter import NoopMetricAdapter
from backend.adapters.out.storage.memory_adapter import MemoryStorageAdapter
from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter
from backend.application.services.chat_service import ChatService
from backend.core.legacy.agent import SageAgent
from backend.core.legacy.llm_client import LLMResponse, LLMToolCall
from backend.domain.tool_policy import DEFAULT_MAX_TOOL_CALLS_PER_RUN, ToolPolicy
from backend.orchestration import orch_settings
from backend.orchestration.orch_settings import OrchSettings

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------- 夹具


@pytest.fixture(autouse=True)
def _isolated_budget_sources(monkeypatch):
    """切断 env 与本地 app_settings 的影响，让预算解析只由用例显式控制。"""
    monkeypatch.delenv("SAGE_MAX_TOOL_CALLS_PER_RUN", raising=False)
    monkeypatch.setattr(orch_settings, "load_orch_settings", lambda: OrchSettings())


def _set_orch_budget(monkeypatch, value: int) -> None:
    """把 UI（OrchSettings）侧的预算设成 ``value``。"""
    monkeypatch.setattr(
        orch_settings,
        "load_orch_settings",
        lambda: OrchSettings(max_tool_calls_per_run=value),
    )


class _RecordingEvents:
    def __init__(self) -> None:
        self.calls: List[Tuple[str, dict]] = []

    def emit(self, event_type: str, payload: dict) -> None:
        self.calls.append((event_type, payload))

    def lifecycle(self) -> List[Tuple[str, dict]]:
        return [(t, p) for t, p in self.calls if isinstance(p, dict) and "run_id" in p]


def _make_chat_service(events, tool_calls_per_response: int, policy: ToolPolicy):
    """构造 ChatService，LLM 单次响应返回 ``tool_calls_per_response`` 个 tool_calls。"""
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


# ------------------------------------------------- 1. 默认预算支持长任务


@pytest.mark.asyncio()
async def test_default_budget_completes_long_multi_turn_task():
    """30 轮 × 1 次工具调用（共 30 次 > 旧的 25 上限）在默认预算下跑完。"""
    responses = [
        LLMResponse(
            content="",
            tool_calls=[
                LLMToolCall(id=f"c{i}", name="list_dir", arguments='{"expression": "1+1"}')
            ],
        )
        for i in range(30)
    ]
    responses.append(LLMResponse(content="done"))

    mock_client = MagicMock()
    mock_client.chat = AsyncMock(side_effect=responses)

    agent = SageAgent()
    agent.llm_client = mock_client

    events = []
    async for evt in agent.run_loop(
        [{"role": "user", "content": "x"}],
        max_iterations=50,  # 默认 DEFAULT_MAX_ITERATIONS=10 装不下 30 轮
    ):
        events.append(evt)

    assert events[-1].state.value == "done"
    assert events[-1].content == "done"
    # 31 次 LLM 往返 = 30 轮工具调用 + 1 轮收尾，全部执行而非在 25 处被切
    assert mock_client.chat.await_count == 31


def test_default_budget_is_single_source_of_truth():
    """默认值只有一个来源：ToolPolicy 的公开常量。"""
    assert DEFAULT_MAX_TOOL_CALLS_PER_RUN == 100
    assert ToolPolicy().max_tool_calls_per_run == DEFAULT_MAX_TOOL_CALLS_PER_RUN
    assert OrchSettings().max_tool_calls_per_run == DEFAULT_MAX_TOOL_CALLS_PER_RUN


# ------------------------------------- 2. UI 预算覆盖"仍是默认值的快照"


@pytest.mark.asyncio()
async def test_orch_budget_overrides_default_policy_snapshot(monkeypatch):
    """policy 快照仍是默认值时，UI 设的 200 必须生效（魔法哨兵回归测试）。"""
    _set_orch_budget(monkeypatch, 200)

    events = _RecordingEvents()
    policy = ToolPolicy()  # 默认快照（= 100）
    svc = _make_chat_service(events, tool_calls_per_response=120, policy=policy)

    sid = await svc.create_session()
    await svc.run_turn(sid, Message(role=Role.USER, content="go"))

    lc = events.lifecycle()
    assert lc[-1][1]["status"] == "ok"
    tool_results = [p for t, p in lc if t == "tool_result"]
    assert len(tool_results) == 120


@pytest.mark.asyncio()
async def test_default_policy_snapshot_still_blocks_at_default(monkeypatch):
    """对照组：UI 未配置（回落默认 100）时，第 101 次工具调用被拦下。"""
    _set_orch_budget(monkeypatch, 0)  # 0 = 非法值 → 回落默认

    events = _RecordingEvents()
    policy = ToolPolicy()
    svc = _make_chat_service(events, tool_calls_per_response=120, policy=policy)

    sid = await svc.create_session()
    await svc.run_turn(sid, Message(role=Role.USER, content="go"))

    lc = events.lifecycle()
    assert lc[-1][1]["status"] == "tool_budget_exceeded"
    tool_results = [p for t, p in lc if t == "tool_result"]
    assert len(tool_results) == DEFAULT_MAX_TOOL_CALLS_PER_RUN


# --------------------------------------------- 3. 显式 policy 不被 UI 覆盖


@pytest.mark.asyncio()
async def test_explicit_policy_budget_not_overridden_by_orch(monkeypatch):
    """policy 显式设为 3 时，即使 UI 设了 200 也只执行 3 次。"""
    _set_orch_budget(monkeypatch, 200)

    events = _RecordingEvents()
    policy = ToolPolicy(max_tool_calls_per_run=3)
    svc = _make_chat_service(events, tool_calls_per_response=5, policy=policy)

    sid = await svc.create_session()
    await svc.run_turn(sid, Message(role=Role.USER, content="go"))

    lc = events.lifecycle()
    assert lc[-1][1]["status"] == "tool_budget_exceeded"
    tool_results = [p for t, p in lc if t == "tool_result"]
    assert len(tool_results) == 3


# ----------------------------------------------------- 4. 0 的真实语义


def test_orch_zero_falls_back_to_default_not_unlimited(monkeypatch):
    """UI 侧 0 不是"不限"，而是回落默认预算。"""
    _set_orch_budget(monkeypatch, 0)
    from backend.orchestration.orch_settings import resolve_tool_call_budget

    assert resolve_tool_call_budget() == DEFAULT_MAX_TOOL_CALLS_PER_RUN


@pytest.mark.asyncio()
async def test_policy_zero_blocks_all_tool_calls():
    """policy 侧 0 = 阻断全部工具调用（不是不限）。"""
    events = _RecordingEvents()
    policy = ToolPolicy(max_tool_calls_per_run=0)
    svc = _make_chat_service(events, tool_calls_per_response=2, policy=policy)

    sid = await svc.create_session()
    await svc.run_turn(sid, Message(role=Role.USER, content="go"))

    lc = events.lifecycle()
    assert lc[-1][1]["status"] == "tool_budget_exceeded"
    tool_results = [p for t, p in lc if t == "tool_result"]
    assert len(tool_results) == 0


def test_env_override_wins_over_orch(monkeypatch):
    """env 优先级最高：env=7 覆盖 UI 的 200。"""
    _set_orch_budget(monkeypatch, 200)
    monkeypatch.setenv("SAGE_MAX_TOOL_CALLS_PER_RUN", "7")
    from backend.orchestration.orch_settings import resolve_tool_call_budget

    assert resolve_tool_call_budget() == 7
