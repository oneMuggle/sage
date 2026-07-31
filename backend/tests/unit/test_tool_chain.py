"""A19 Tool Chain Tracking — 领域模型 + run_loop 集成单测。

覆盖：
- ``ToolStep`` / ``ToolChain`` 序列化与进度计算（领域纯净：时间戳注入）。
- ``ToolChainTracker`` start/complete 生命周期、错误路径、结果截断。
- ``SageAgent.run_loop`` 在 ACTING/OBSERVING 周围推送 TOOL_CHAIN_UPDATE 事件。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.legacy.agent import SageAgent
from backend.core.legacy.agent_state import AgentState
from backend.core.legacy.llm_client import LLMResponse, LLMToolCall
from backend.domain.tool_chain import (
    ERROR_MESSAGE_LIMIT,
    RESULT_SUMMARY_LIMIT,
    ToolChain,
    ToolChainTracker,
    ToolStep,
    ToolStepStatus,
)

pytestmark = pytest.mark.unit


# ── 领域模型 ──────────────────────────────────────────────


def test_tool_step_to_dict_serializes_status_and_duration():
    step = ToolStep(
        step_id=1,
        tool_name="calculator",
        args={"expression": "1+1"},
        status=ToolStepStatus.DONE,
        result="2",
        duration_ms=12.34,
        started_at=100.0,
        finished_at=100.01234,
    )
    d = step.to_dict()
    assert d == {
        "step_id": 1,
        "tool_name": "calculator",
        "args": {"expression": "1+1"},
        "status": "done",
        "result": "2",
        "duration_ms": 12.3,
        "error_message": "",
    }
    # 单调时间戳不下发前端
    assert "started_at" not in d
    assert "finished_at" not in d


def test_tool_step_is_error_reflects_status():
    step = ToolStep(step_id=1, tool_name="bash", status=ToolStepStatus.ERROR)
    assert step.is_error is True
    step.status = ToolStepStatus.DONE
    assert step.is_error is False


def test_empty_chain_progress_is_zero():
    chain = ToolChain(chain_id="c1")
    assert chain.progress == 0.0
    assert chain.total_steps == 0
    assert chain.completed_steps == 0


def test_chain_to_dict_shape():
    tracker = ToolChainTracker(chain_id="c1", description="Tool Execution")
    step = tracker.start_step("bash", {"command": "ls"}, now=10.0)
    tracker.complete_step(step.step_id, "file1\nfile2", now=10.5)
    d = tracker.chain.to_dict()
    assert d["chain_id"] == "c1"
    assert d["description"] == "Tool Execution"
    assert d["total_steps"] == 1
    assert d["completed_steps"] == 1
    assert d["progress"] == 1.0
    assert d["current_step"] == 0
    assert d["steps"][0]["tool_name"] == "bash"
    assert d["steps"][0]["status"] == "done"
    assert d["steps"][0]["duration_ms"] == 500.0


# ── ToolChainTracker ──────────────────────────────────────


def test_start_step_assigns_incrementing_ids_and_sets_current():
    tracker = ToolChainTracker(chain_id="c1")
    s1 = tracker.start_step("bash", {"command": "ls"}, now=0.0)
    s2 = tracker.start_step("read_file", {"path": "a.txt"}, now=1.0)
    assert s1.step_id == 1
    assert s2.step_id == 2
    assert s1.status is ToolStepStatus.RUNNING
    assert tracker.chain.current_step == 2
    assert tracker.chain.progress == 0.0


def test_start_step_copies_args_to_avoid_mutation():
    tracker = ToolChainTracker(chain_id="c1")
    args = {"command": "ls"}
    step = tracker.start_step("bash", args, now=0.0)
    args["command"] = "rm -rf /"  # 调用方就地修改不得污染快照
    assert step.args == {"command": "ls"}


def test_complete_step_computes_duration_from_injected_timestamps():
    tracker = ToolChainTracker(chain_id="c1")
    step = tracker.start_step("calculator", {}, now=100.0)
    updated = tracker.complete_step(step.step_id, "42", now=100.25)
    assert updated is step
    assert step.status is ToolStepStatus.DONE
    assert step.duration_ms == pytest.approx(250.0)
    assert step.result == "42"
    assert tracker.chain.current_step == 0
    assert tracker.chain.completed_steps == 1
    assert tracker.chain.progress == 1.0


def test_complete_step_error_sets_error_status_and_message():
    tracker = ToolChainTracker(chain_id="c1")
    step = tracker.start_step("bash", {}, now=0.0)
    tracker.complete_step(step.step_id, "command not found", is_error=True, now=0.1)
    assert step.status is ToolStepStatus.ERROR
    assert step.is_error is True
    assert step.error_message == "command not found"
    # ERROR 同样计入已完成步骤
    assert tracker.chain.completed_steps == 1


def test_complete_step_truncates_long_result():
    tracker = ToolChainTracker(chain_id="c1")
    step = tracker.start_step("read_file", {}, now=0.0)
    long_result = "x" * (RESULT_SUMMARY_LIMIT + 100)
    tracker.complete_step(step.step_id, long_result, now=0.1)
    assert len(step.result) == RESULT_SUMMARY_LIMIT + 1  # 截断 + 省略号
    assert step.result.endswith("…")


def test_complete_step_flattens_newlines_in_summary():
    tracker = ToolChainTracker(chain_id="c1")
    step = tracker.start_step("bash", {}, now=0.0)
    tracker.complete_step(step.step_id, "line1\nline2\nline3", now=0.1)
    assert step.result == "line1 line2 line3"


def test_complete_step_truncates_long_error_message():
    tracker = ToolChainTracker(chain_id="c1")
    step = tracker.start_step("bash", {}, now=0.0)
    long_err = "e" * (ERROR_MESSAGE_LIMIT + 50)
    tracker.complete_step(step.step_id, long_err, is_error=True, now=0.1)
    assert len(step.error_message) == ERROR_MESSAGE_LIMIT


def test_complete_step_unknown_id_returns_none():
    tracker = ToolChainTracker(chain_id="c1")
    tracker.start_step("bash", {}, now=0.0)
    assert tracker.complete_step(999, "x", now=1.0) is None
    assert tracker.chain.current_step == 1  # 未受影响


def test_duration_is_never_negative():
    tracker = ToolChainTracker(chain_id="c1")
    step = tracker.start_step("bash", {}, now=10.0)
    tracker.complete_step(step.step_id, "ok", now=9.0)  # 时钟回拨兜底
    assert step.duration_ms == 0.0


def test_progress_with_mixed_statuses():
    tracker = ToolChainTracker(chain_id="c1")
    s1 = tracker.start_step("a", {}, now=0.0)
    tracker.complete_step(s1.step_id, "ok", now=0.1)
    s2 = tracker.start_step("b", {}, now=0.2)
    tracker.complete_step(s2.step_id, "boom", is_error=True, now=0.3)
    tracker.start_step("c", {}, now=0.4)  # 仍在运行
    assert tracker.chain.total_steps == 3
    assert tracker.chain.completed_steps == 2
    assert tracker.chain.progress == pytest.approx(2 / 3)


# ── run_loop 集成 ─────────────────────────────────────────


def _make_response(content: str = "", tool_calls: list = None) -> LLMResponse:
    return LLMResponse(content=content, tool_calls=tool_calls or [])


@pytest.mark.asyncio()
async def test_run_loop_emits_tool_chain_update_around_tool_call():
    """工具调用时 ACTING 后推 running 快照、OBSERVING 后推 done 快照。"""
    tool_call = LLMToolCall(id="call_1", name="calculator", arguments='{"expression": "1+1"}')
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        side_effect=[
            _make_response(tool_calls=[tool_call]),
            _make_response(content="答案是 2"),
        ]
    )
    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(
        return_value=MagicMock(success=True, content={"result": 2}, error=None)
    )
    agent.tool_registry.get = MagicMock(return_value=mock_tool)

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "1+1=?"}]):
        events.append(evt)

    updates = [e for e in events if e.state == AgentState.TOOL_CHAIN_UPDATE]
    assert len(updates) == 2

    # 第一帧：步骤 running
    first = updates[0].tool_chain
    assert first is not None
    assert first["total_steps"] == 1
    assert first["current_step"] == 1
    assert first["progress"] == 0.0
    assert first["steps"][0]["tool_name"] == "calculator"
    assert first["steps"][0]["status"] == "running"
    assert first["steps"][0]["args"] == {"expression": "1+1"}

    # 第二帧：步骤 done，进度 100%
    second = updates[1].tool_chain
    assert second["current_step"] == 0
    assert second["completed_steps"] == 1
    assert second["progress"] == 1.0
    assert second["steps"][0]["status"] == "done"
    assert "2" in second["steps"][0]["result"]

    # 事件顺序：ACTING → UPDATE → OBSERVING → UPDATE
    states = [e.state for e in events]
    acting_idx = states.index(AgentState.ACTING)
    observing_idx = states.index(AgentState.OBSERVING)
    update_idxs = [i for i, s in enumerate(states) if s == AgentState.TOOL_CHAIN_UPDATE]
    assert update_idxs[0] == acting_idx + 1
    assert update_idxs[1] == observing_idx + 1


@pytest.mark.asyncio()
async def test_run_loop_tool_chain_update_carries_agent_id():
    """TOOL_CHAIN_UPDATE 事件携带 agent_id（前端区分主/子 agent）。"""
    tool_call = LLMToolCall(id="call_1", name="calculator", arguments="{}")
    agent = SageAgent()
    agent.agent_id = "sub-agent-1"  # 直接赋值避免构造器读 DB
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        side_effect=[
            _make_response(tool_calls=[tool_call]),
            _make_response(content="done"),
        ]
    )
    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(
        return_value=MagicMock(success=True, content="ok", error=None)
    )
    agent.tool_registry.get = MagicMock(return_value=mock_tool)

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "hi"}]):
        events.append(evt)

    updates = [e for e in events if e.state == AgentState.TOOL_CHAIN_UPDATE]
    assert updates
    assert all(e.agent_id == "sub-agent-1" for e in updates)


@pytest.mark.asyncio()
async def test_run_loop_tool_error_recorded_in_chain():
    """工具执行失败时链快照记录 error 状态。"""
    tool_call = LLMToolCall(id="call_1", name="bash", arguments='{"command": "false"}')
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        side_effect=[
            _make_response(tool_calls=[tool_call]),
            _make_response(content="失败"),
        ]
    )
    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(
        return_value=MagicMock(success=False, content=None, error="exit code 1")
    )
    agent.tool_registry.get = MagicMock(return_value=mock_tool)

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "run"}]):
        events.append(evt)

    last_update = [e for e in events if e.state == AgentState.TOOL_CHAIN_UPDATE][-1]
    step = last_update.tool_chain["steps"][0]
    assert step["status"] == "error"
    assert step["error_message"] == "exit code 1"
    assert last_update.tool_chain["progress"] == 1.0


@pytest.mark.asyncio()
async def test_run_loop_without_tool_calls_emits_no_chain_update():
    """纯文本回复不产生工具链事件。"""
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(return_value=_make_response(content="你好"))

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "hi"}]):
        events.append(evt)

    assert not [e for e in events if e.state == AgentState.TOOL_CHAIN_UPDATE]


@pytest.mark.asyncio()
async def test_run_loop_multi_step_chain_accumulates_steps():
    """多次迭代工具调用累积进同一条链。"""
    call_1 = LLMToolCall(id="call_1", name="calculator", arguments='{"expression": "1+1"}')
    call_2 = LLMToolCall(id="call_2", name="bash", arguments='{"command": "ls"}')
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        side_effect=[
            _make_response(tool_calls=[call_1]),
            _make_response(tool_calls=[call_2]),
            _make_response(content="全部完成"),
        ]
    )
    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(
        return_value=MagicMock(success=True, content="ok", error=None)
    )
    agent.tool_registry.get = MagicMock(return_value=mock_tool)

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "do things"}]):
        events.append(evt)

    updates = [e for e in events if e.state == AgentState.TOOL_CHAIN_UPDATE]
    assert len(updates) == 4  # 两次工具调用 × (start + complete)
    last = updates[-1].tool_chain
    assert last["total_steps"] == 2
    assert last["completed_steps"] == 2
    assert [s["step_id"] for s in last["steps"]] == [1, 2]
    assert [s["tool_name"] for s in last["steps"]] == ["calculator", "bash"]
