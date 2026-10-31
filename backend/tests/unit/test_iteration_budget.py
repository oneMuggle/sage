"""动态迭代预算与进度审计单测（2026-10-31）。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.legacy.agent import SageAgent
from backend.core.legacy.agent_state import AgentEvent, AgentState
from backend.core.legacy.iteration_budget import (
    BudgetConfig,
    StepRecord,
    audit_window,
    build_step_record,
    decide_budget,
    estimate_initial_budget,
    tool_signature,
)
from backend.core.legacy.llm_client import LLMResponse, LLMToolCall

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 初始预算估算
# ---------------------------------------------------------------------------


def test_estimate_simple_task():
    budget, level = estimate_initial_budget("修复 README 的 typo")
    assert level == "simple"
    assert budget == 20


def test_estimate_medium_task_by_keyword():
    budget, level = estimate_initial_budget("实现一个导出按钮")
    assert level == "medium"
    assert budget == 80


def test_estimate_complex_task():
    budget, level = estimate_initial_budget(
        "重构整个项目的编排链路并迁移所有调用方，需要端到端设计"
    )
    assert level == "complex"
    assert budget == 200


def test_estimate_long_task_overrides():
    budget, level = estimate_initial_budget("任意任务", long_task=True)
    assert level == "long"
    assert budget == 400


def test_estimate_profile_floor_does_not_lower_budget():
    budget, _ = estimate_initial_budget("hi", profile_floor=300)
    assert budget == 300


def test_estimate_clamped_to_hard_cap():
    cfg = BudgetConfig(long_budget=5000, hard_cap=1000)
    budget, _ = estimate_initial_budget("长任务", long_task=True, config=cfg)
    assert budget == 1000


# ---------------------------------------------------------------------------
# StepRecord 构建
# ---------------------------------------------------------------------------


def _assistant_tool_call(name: str, arguments: str) -> dict:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }
        ],
    }


def test_build_step_record_counts_file_change_and_new_result():
    seen: set = set()
    messages = [
        _assistant_tool_call("write_file", '{"path": "a.txt", "content": "x"}'),
        {"role": "tool", "tool_call_id": "c1", "content": "ok"},
    ]
    record = build_step_record(0, messages, seen)
    assert record.file_changes == 1
    assert len(record.result_hashes) == 1
    assert record.productive is True


def test_build_step_record_repeated_result_is_not_progress():
    seen: set = set()
    messages = [{"role": "tool", "tool_call_id": "c1", "content": "same"}]
    first = build_step_record(0, messages, seen)
    second = build_step_record(1, messages, seen)
    assert len(first.result_hashes) == 1
    assert second.result_hashes == ()
    assert second.productive is False


def test_build_step_record_marks_error():
    seen: set = set()
    messages = [{"role": "tool", "tool_call_id": "c1", "content": "[错误] boom"}]
    record = build_step_record(0, messages, seen)
    assert record.error_hashes


def test_tool_signature_is_order_insensitive():
    assert tool_signature("f", '{"b": 2, "a": 1}') == tool_signature(
        "f", '{"a": 1, "b": 2}'
    )


def test_iteration_checkpoint_event_serializes_budget_info():
    evt = AgentEvent(
        state=AgentState.ITERATION_CHECKPOINT,
        iteration=3,
        budget_info={"next_budget": 4, "extensions": 1},
    )
    payload = evt.to_dict()
    assert payload["state"] == "iteration_checkpoint"
    assert payload["budget_info"] == {"next_budget": 4, "extensions": 1}


# ---------------------------------------------------------------------------
# 审计与决策
# ---------------------------------------------------------------------------


def _record(index: int, *, sig: str = "", productive: bool = True, error: str = "") -> StepRecord:
    return StepRecord(
        index=index,
        signatures=(sig,) if sig else (),
        result_hashes=(f"h{index}",) if productive else (),
        error_hashes=(error,) if error else (),
        productive=productive,
    )


def test_audit_detects_repeated_signature():
    cfg = BudgetConfig(repeat_soft=2, repeat_hard=4)
    records = [_record(i, sig="same") for i in range(4)]
    audit = audit_window(records, cfg)
    assert audit.max_repeat == 4
    assert audit.stuck_score >= 0.7


def test_audit_detects_cycle():
    cfg = BudgetConfig()
    records = [
        _record(0, sig="a"),
        _record(1, sig="b"),
        _record(2, sig="a"),
        _record(3, sig="b"),
    ]
    audit = audit_window(records, cfg)
    assert audit.cycle_detected is True
    assert audit.stuck_score >= 0.85


def test_audit_detects_no_progress():
    cfg = BudgetConfig(no_progress_threshold=4)
    records = [_record(i, productive=False) for i in range(4)]
    audit = audit_window(records, cfg)
    assert audit.no_progress_steps == 4
    assert audit.stuck_score >= 0.7


def test_decide_extends_when_progressing():
    cfg = BudgetConfig(extension_ratio=0.5, min_extension=10, max_extension=50)
    audit = audit_window([_record(0, sig="a"), _record(1, sig="b")], cfg)
    decision = decide_budget(20, audit, extension_count=0, config=cfg)
    assert decision.action == "extend"
    assert decision.next_budget == 30


def test_decide_stops_when_stuck():
    cfg = BudgetConfig(repeat_soft=2, repeat_hard=3)
    audit = audit_window([_record(i, sig="same") for i in range(3)], cfg)
    decision = decide_budget(20, audit, extension_count=0, config=cfg)
    assert decision.action == "stop"
    assert decision.reason == "stuck"


def test_decide_stops_at_extension_limit():
    cfg = BudgetConfig(max_extensions=1)
    audit = audit_window([_record(0, sig="a"), _record(1, sig="b")], cfg)
    decision = decide_budget(20, audit, extension_count=1, config=cfg)
    assert decision.action == "stop"
    assert decision.reason == "extension_limit"


def test_decide_stops_without_progress_signals():
    cfg = BudgetConfig()
    audit = audit_window([_record(0, productive=False)], cfg)
    decision = decide_budget(20, audit, extension_count=0, config=cfg)
    assert decision.action == "stop"
    assert decision.reason == "no_progress"


def test_decide_stops_at_hard_cap():
    cfg = BudgetConfig(hard_cap=100, extension_ratio=0.5, min_extension=30)
    audit = audit_window([_record(0, sig="a"), _record(1, sig="b")], cfg)
    decision = decide_budget(100, audit, extension_count=0, config=cfg)
    assert decision.action == "stop"
    assert decision.reason == "hard_cap"


# ---------------------------------------------------------------------------
# run_loop 集成
# ---------------------------------------------------------------------------


def _tool_response(expression: str) -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[
            LLMToolCall(
                id=f"call-{expression}",
                name="write_file",
                arguments=f'{{"path": "{expression}.txt", "content": "x"}}',
            )
        ],
    )


def _text_response(content: str) -> LLMResponse:
    return LLMResponse(content=content, tool_calls=[])


def _make_agent(side_effects) -> SageAgent:
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(side_effect=side_effects)
    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(
        return_value=MagicMock(success=True, content={"result": "ok"}, error=None)
    )
    agent.tool_registry.get = MagicMock(return_value=mock_tool)
    return agent


async def _collect(agent):
    return [evt async for evt in agent.run_loop([{"role": "user", "content": "hi"}])]


@pytest.mark.asyncio()
async def test_run_loop_extends_budget_and_completes(monkeypatch):
    """初始预算 2 → 进度审计延长 → 第 3 步完成，不发出 FAILED。"""
    monkeypatch.setenv("SAGE_DYNAMIC_BUDGET_SIMPLE", "2")
    monkeypatch.setenv("SAGE_DYNAMIC_BUDGET_MIN_EXTENSION", "2")
    monkeypatch.setenv("SAGE_DYNAMIC_BUDGET_MAX_EXTENSION", "2")
    agent = _make_agent(
        [
            _tool_response("a"),
            _tool_response("b"),
            _tool_response("c"),
            _text_response("完成"),
        ]
    )
    with patch(
        "backend.orchestration.orch_settings.load_orch_settings",
        return_value=SimpleNamespace(max_iterations=25),
    ):
        events = await _collect(agent)

    assert AgentState.ITERATION_CHECKPOINT in [e.state for e in events]
    assert AgentState.FAILED not in [e.state for e in events]
    assert AgentState.DONE in [e.state for e in events]
    checkpoint = next(e for e in events if e.state == AgentState.ITERATION_CHECKPOINT)
    assert checkpoint.budget_info is not None
    assert checkpoint.budget_info["previous_budget"] == 2
    assert checkpoint.budget_info["next_budget"] == 4


@pytest.mark.asyncio()
async def test_run_loop_stops_when_repeated_calls_stuck(monkeypatch):
    """相同只读调用反复出现 → 审计判定 stuck，停止并带原因。"""
    monkeypatch.setenv("SAGE_DYNAMIC_BUDGET_SIMPLE", "3")
    monkeypatch.setenv("SAGE_DYNAMIC_BUDGET_MIN_EXTENSION", "2")
    monkeypatch.setenv("SAGE_DYNAMIC_BUDGET_MAX_EXTENSION", "2")
    monkeypatch.setenv("SAGE_TOOL_REPEAT_SOFT_LIMIT", "3")
    monkeypatch.setenv("SAGE_TOOL_REPEAT_HARD_LIMIT", "0")
    same = LLMResponse(
        content="",
        tool_calls=[
            LLMToolCall(id="same", name="list_dir", arguments='{"path": "."}')
        ],
    )
    agent = _make_agent([same] * 12)
    with patch(
        "backend.orchestration.orch_settings.load_orch_settings",
        return_value=SimpleNamespace(max_iterations=25),
    ):
        events = await _collect(agent)

    failed = [e for e in events if e.state == AgentState.FAILED]
    assert len(failed) == 1
    assert "reason=stuck" in (failed[0].error or "")


@pytest.mark.asyncio()
async def test_explicit_max_iterations_never_extends(monkeypatch):
    """显式上限是硬上限：即使有进展也不自动延长。"""
    monkeypatch.setenv("SAGE_DYNAMIC_ITERATION_BUDGET", "1")
    agent = _make_agent([_tool_response("a"), _tool_response("b"), _text_response("x")])
    events = [evt async for evt in agent.run_loop(
        [{"role": "user", "content": "hi"}], max_iterations=1
    )]

    assert AgentState.ITERATION_CHECKPOINT not in [e.state for e in events]
    failed = [e for e in events if e.state == AgentState.FAILED]
    assert len(failed) == 1
    assert failed[0].error == "max_iterations_exceeded (limit=1, source=explicit)"
