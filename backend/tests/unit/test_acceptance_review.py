"""Round 4 (2026-09-19) 验收闭环——acceptance 结果进复核单测。

覆盖（docs/plans/2026-09-19_orch-acceptance-review-plan.md）：
- review.build_review_goal：含/不含验收区块的组合与聚合文本截断；
- chat_dispatcher.build_acceptance_block：无记录空串 / 全通过仅头部 /
  未通过明细（task_id + check 名 + 摘要截断）；
- dispatcher._run_review 把 acceptance_block 透传 review.run_review；
- executor._run_acceptance 返回摘要 dict（disabled / reviewer → None）；
- 拆解提示词（planner / plan-items）携带"完成定义（验收标准）"。
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from backend.orchestration.acceptance import CheckResult
from backend.orchestration.chat_dispatcher import ChatDispatcher, build_acceptance_block
from backend.orchestration.executor import LaneExecutor
from backend.orchestration.models import Lane
from backend.orchestration.review import (
    ACCEPTANCE_REVIEW_NOTE,
    build_review_goal,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# review.build_review_goal
# ---------------------------------------------------------------------------


def test_build_review_goal_without_block_keeps_legacy_shape():
    goal = build_review_goal("聚合内容", "", max_chars=1000)
    assert goal == "复核以下多 agent 子任务聚合结果，逐条给出 assertion。\n聚合内容"
    assert ACCEPTANCE_REVIEW_NOTE not in goal


def test_build_review_goal_with_block_prepends_and_adds_instruction():
    goal = build_review_goal("聚合内容", "## 验收检查结果\n\n- [t2] 验收未通过：pytest")
    assert goal.startswith("## 验收检查结果")
    assert ACCEPTANCE_REVIEW_NOTE in goal
    assert "NEGATIVE_EVIDENCE" in goal
    assert goal.rstrip().endswith("聚合内容")


def test_build_review_goal_truncates_aggregated_only():
    goal = build_review_goal("x" * 500, "BLOCK", max_chars=50)
    assert "BLOCK" in goal
    assert "x" * 50 in goal
    assert "x" * 51 not in goal


# ---------------------------------------------------------------------------
# chat_dispatcher.build_acceptance_block
# ---------------------------------------------------------------------------


def _state(task_id: str, acceptance=None):
    from backend.orchestration.chat_dispatcher import ChatTaskState

    state = ChatTaskState(task_id=task_id, agent_id="coder", goal="g")
    if acceptance is not None:
        state.acceptance = acceptance
    return state


def test_build_acceptance_block_empty_when_no_records():
    assert build_acceptance_block([]) == ""
    assert build_acceptance_block([_state("t1"), _state("t2")]) == ""


def test_build_acceptance_block_all_passed_header_only():
    block = build_acceptance_block(
        [
            _state("t1", {"all_passed": True, "checks": [
                {"name": "git diff --stat", "passed": True, "skipped": False, "summary": "s"},
            ]}),
        ]
    )
    assert "1 个子任务执行了自动验收" in block
    assert "0 个存在未通过项" in block
    assert "[t1]" not in block  # 全通过无明细行


def test_build_acceptance_block_lists_failed_tasks_with_truncation():
    block = build_acceptance_block(
        [
            _state("t1", {"all_passed": True, "checks": [
                {"name": "diff", "passed": True, "skipped": False, "summary": ""},
            ]}),
            _state(
                "t2",
                {
                    "all_passed": False,
                    "checks": [
                        {
                            "name": "pytest",
                            "passed": False,
                            "skipped": False,
                            "summary": "3 failed：" + "y" * 200,
                        },
                        {"name": "lint-skip", "passed": False, "skipped": True, "summary": ""},
                    ],
                },
            ),
        ]
    )
    assert "2 个子任务执行了自动验收" in block
    assert "1 个存在未通过项" in block
    assert "[t2]" in block
    assert "pytest" in block
    expected_tail = ("3 failed：" + "y" * 200)[:120]
    assert expected_tail in block  # 摘要截断到 120
    assert expected_tail + "y" not in block
    assert "lint-skip" not in block  # skipped 不算未通过


# ---------------------------------------------------------------------------
# dispatcher._run_review 透传
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_run_review_passes_acceptance_block_to_review():
    dispatcher = ChatDispatcher(
        stream_id="s1",
        entry_queue=asyncio.Queue(),
        run_id="orch-test",
    )
    captured: dict = {}

    async def fake_run_review(**kwargs):
        captured.update(kwargs)
        return {"verdict": "pass", "block": "- ok", "assertion_count": 1}

    with patch(
        "backend.orchestration.review.run_review",
        side_effect=fake_run_review,
    ):
        await dispatcher._run_review("聚合内容", acceptance_block="## 验收检查结果")

    assert captured["acceptance_block"] == "## 验收检查结果"
    assert captured["run_id"] == "orch-test"


# ---------------------------------------------------------------------------
# executor._run_acceptance 摘要回传
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_executor_run_acceptance_returns_summary():
    from backend.orchestration.acceptance import AcceptanceReport

    executor = LaneExecutor(
        lane_registry=object(),
        task_registry=object(),
        event_recorder=object(),
        agent_runner=object(),
    )
    lane = Lane(lane_id="l1", task_id="t1", agent_id="coder", worktree="/tmp/wt")

    report = AcceptanceReport(
        checks=[
            CheckResult(name="pytest", passed=False, summary="3 failed"),
            CheckResult(name="worktree", passed=True, skipped=True),
        ]
    )

    with patch(
        "backend.orchestration.executor.run_acceptance_checks",
        return_value=report,
    ) as mock_checks, patch(
        "backend.orchestration.executor.record_acceptance_event"
    ) as mock_record:
        summary = await executor._run_acceptance(lane)

    assert summary == {
        "all_passed": False,
        "checks": [
            {"name": "pytest", "passed": False, "skipped": False, "summary": "3 failed"},
            {"name": "worktree", "passed": True, "skipped": True, "summary": ""},
        ],
    }
    mock_checks.assert_called_once()
    mock_record.assert_called_once()


@pytest.mark.asyncio()
async def test_executor_run_acceptance_none_for_disabled_and_reviewer():
    executor = LaneExecutor(
        lane_registry=object(),
        task_registry=object(),
        event_recorder=object(),
        agent_runner=object(),
        acceptance_enabled=False,
    )
    lane = Lane(lane_id="l1", task_id="t1", agent_id="coder")
    reviewer_lane = Lane(lane_id="l2", task_id="t2", agent_id="reviewer")
    assert await executor._run_acceptance(lane) is None
    assert await executor._run_acceptance(reviewer_lane) is None


# ---------------------------------------------------------------------------
# 提示词：完成定义（验收标准）
# ---------------------------------------------------------------------------


def test_planner_prompt_requires_completion_criteria():
    from unittest.mock import MagicMock

    from backend.orchestration.planner import Planner

    planner = Planner(
        task_registry=MagicMock(),
        team_registry=MagicMock(),
        llm_client=None,
        auto_configure=False,
    )
    prompt = planner._build_decomposition_prompt("目标")
    assert "完成定义（验收标准）" in prompt


def test_plan_items_prompt_requires_completion_criteria():
    from backend.api.orch_routes import _PLAN_ITEMS_PROMPT

    assert "完成定义（验收标准）" in _PLAN_ITEMS_PROMPT
