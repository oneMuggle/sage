"""Wave 2 Task 3 — task_review NDJSON 事件契约 + 顺手项（0-parse fail-skip / MAX_ITERATIONS）。

- ``_run_review`` 末尾推 ``task_review`` 事件（spec §5.2）到 entry_queue
- 0-parse（reviewer 未产出可解析 assertion）→ verdict=fail（消除 vacuous pass）
- ``[FACT]`` → pass；``[NEGATIVE_EVIDENCE]`` confidence≥0.7 → fail
- ``_BrokenReview`` fake 改真 async gen（yield 一次后 raise，不触发 RuntimeWarning）
- ``_run_subagent`` 防御性 max-iteration guard（一直 retrying → RuntimeError）
"""
from __future__ import annotations

import asyncio
import warnings
from unittest.mock import AsyncMock, patch

import pytest

from backend.orchestration.chat_dispatcher import ChatDispatcher


def _dispatcher() -> ChatDispatcher:
    return ChatDispatcher(
        stream_id="s1",
        entry_queue=asyncio.Queue(),
        run_id="orch-test",
    )


@pytest.mark.asyncio()
async def test_run_review_emits_task_review_event():
    """_run_review 末尾 push task_review NDJSON 事件到 entry_queue。"""
    dispatcher = _dispatcher()
    # mock 掉 _run_review 内 lane/executor 调用，直接调底层逻辑。
    with patch.object(dispatcher, "_parse_assertions", return_value=[]), patch(
        "backend.orchestration.chat_dispatcher.run_lane_with_retry",
        new=AsyncMock(return_value={
            "status": "succeeded",
            "result": {"output": ""},
        }),
    ):
        # 0 assertion → verdict=fail,note="reviewer 未产出"
        await dispatcher._run_review("aggregated content")

    events: list[dict] = []
    while not dispatcher.entry_queue.empty():
        events.append(dispatcher.entry_queue.get_nowait())
    review_events = [e for e in events if e.get("state") == "task_review"]
    assert len(review_events) == 1
    e = review_events[0]
    assert e["run_id"] == "orch-test"
    assert e["verdict"] == "fail"
    assert e["assertion_count"] == 0
    assert "未产出" in e["summary"]


@pytest.mark.asyncio()
async def test_zero_assertion_parse_triggers_fail():
    """0-parse → verdict=fail + summary 含'未产出'。"""
    dispatcher = _dispatcher()
    with patch.object(dispatcher, "_parse_assertions", return_value=[]), patch(
        "backend.orchestration.chat_dispatcher.run_lane_with_retry",
        new=AsyncMock(return_value={
            "status": "succeeded",
            "result": {"output": ""},
        }),
    ):
        result = await dispatcher._run_review("content")
    assert result["verdict"] == "fail"
    assert "未产出" in result["block"]


@pytest.mark.asyncio()
async def test_review_pass_with_fact_assertion():
    """[FACT] 类断言 → verdict=pass。"""
    from backend.orchestration.chat_dispatcher import Assertion, AssertionType

    dispatcher = _dispatcher()
    fake = [Assertion(type=AssertionType.FACT, statement="ok", confidence=0.9)]
    with patch.object(dispatcher, "_parse_assertions", return_value=fake), patch(
        "backend.orchestration.chat_dispatcher.run_lane_with_retry",
        new=AsyncMock(return_value={
            "status": "succeeded",
            "result": {"output": ""},
        }),
    ):
        result = await dispatcher._run_review("content")
    assert result["verdict"] == "pass"


@pytest.mark.asyncio()
async def test_review_fail_with_negative_evidence_high_confidence():
    """[NEGATIVE_EVIDENCE] confidence>=0.7 → verdict=fail。"""
    from backend.orchestration.chat_dispatcher import Assertion, AssertionType

    dispatcher = _dispatcher()
    fake = [
        Assertion(
            type=AssertionType.NEGATIVE_EVIDENCE,
            statement="bad",
            confidence=0.8,
        )
    ]
    with patch.object(dispatcher, "_parse_assertions", return_value=fake), patch(
        "backend.orchestration.chat_dispatcher.run_lane_with_retry",
        new=AsyncMock(return_value={
            "status": "succeeded",
            "result": {"output": ""},
        }),
    ):
        result = await dispatcher._run_review("content")
    assert result["verdict"] == "fail"


def test_broken_review_yields_then_raises():
    """_BrokenReview fake 改真 async gen — yield 一次后 raise，不触发 RuntimeWarning。"""
    from backend.tests.unit.test_chat_dispatcher import _BrokenReview

    gen = _BrokenReview(RuntimeError("boom"))
    agen = gen.run_loop()
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        # 第一次 __anext__ 拿到 yield 值（启动 async gen），不触发 RuntimeWarning
        first = asyncio.run(agen.__anext__())
        assert first["state"] == "task_review_partial"
        # 第二次 __anext__ 触发 raise
        with pytest.raises(RuntimeError, match="boom"):
            asyncio.run(agen.__anext__())


@pytest.mark.asyncio()
async def test_max_lane_iterations_guard_returns_failure():
    """executor 一直返回 retrying → MAX_LANE_ITERATIONS 后 raise RuntimeError。"""
    from backend.orchestration.chat_dispatcher import ChatTaskState

    dispatcher = _dispatcher()
    state = ChatTaskState(task_id="t1", agent_id="primary", goal="g")

    with patch(
        "backend.orchestration.chat_dispatcher.run_lane_with_retry",
        new=AsyncMock(return_value={"status": "retrying"}),
    ), patch(
        "backend.orchestration.chat_dispatcher.MAX_LANE_ITERATIONS", 3
    ), pytest.raises(RuntimeError) as exc_info:
        await dispatcher._run_subagent(state)
    msg = str(exc_info.value)
    assert "MAX_ITERATIONS_EXCEEDED" in msg or "retry loop exceeded" in msg
