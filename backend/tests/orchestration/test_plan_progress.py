import asyncio
import contextlib

import pytest

from backend.orchestration.plan_progress import (
    KIND_HEARTBEAT,
    PLAN_STAGE_SCOUT,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PROGRESS,
    STATUS_SKIPPED,
    emit_plan_progress,
    emit_planning_skipped,
    make_stream_progress_emitter,
    run_planning_stage,
)


def test_emit_plan_progress_nests_payload():
    events = []

    async def emit(event):
        events.append(event)

    asyncio.run(
        emit_plan_progress(
            emit,
            stage=PLAN_STAGE_SCOUT,
            status=STATUS_PROGRESS,
            kind=KIND_HEARTBEAT,
            text="still working",
            elapsed_ms=1200,
        )
    )

    assert len(events) == 1
    assert events[0]["state"] == "plan_progress"
    payload = events[0]["plan_progress"]
    assert payload["stage"] == "scout"
    assert payload["status"] == "progress"
    assert payload["kind"] == "heartbeat"
    assert payload["text"] == "still working"
    assert payload["detail"] == {}
    assert payload["elapsed_ms"] == 1200


def test_emit_plan_progress_truncates_text_and_swallows_emit_error():
    events = []

    async def emit(event):
        events.append(event)

    asyncio.run(
        emit_plan_progress(
            emit, stage=PLAN_STAGE_SCOUT, status=STATUS_DONE, text="x" * 900
        )
    )
    assert len(events[0]["plan_progress"]["text"]) == 500

    async def broken_emit(event):
        raise RuntimeError("queue closed")

    # 不抛异常即为通过
    asyncio.run(
        emit_plan_progress(broken_emit, stage=PLAN_STAGE_SCOUT, status=STATUS_DONE)
    )


def test_emit_planning_skipped_marks_each_stage():
    events = []

    async def emit(event):
        events.append(event)

    asyncio.run(
        emit_planning_skipped(
            emit, stages=[PLAN_STAGE_SCOUT, "scout_deep"], reason="simple task"
        )
    )

    assert [e["plan_progress"]["stage"] for e in events] == ["scout", "scout_deep"]
    assert all(e["plan_progress"]["status"] == STATUS_SKIPPED for e in events)
    assert all(e["plan_progress"]["text"] == "simple task" for e in events)


def test_run_planning_stage_emits_started_and_done():
    events = []

    async def emit(event):
        events.append(event)

    async def runner():
        return "medium"

    result = asyncio.run(
        run_planning_stage(
            emit,
            stage="complexity_classify",
            runner=runner,
            describe_result=lambda value: str(value),
        )
    )

    assert result == "medium"
    statuses = [e["plan_progress"]["status"] for e in events]
    assert statuses[0] == "started"
    assert statuses[-1] == STATUS_DONE
    assert events[-1]["plan_progress"]["text"] == "medium"
    assert isinstance(events[-1]["plan_progress"]["elapsed_ms"], int)


def test_run_planning_stage_emits_heartbeat_then_done():
    events = []

    async def emit(event):
        events.append(event)

    async def runner():
        await asyncio.sleep(0.05)
        return "ok"

    asyncio.run(
        run_planning_stage(
            emit, stage="scout", runner=runner, heartbeat_interval_s=0.01
        )
    )

    kinds = [e["plan_progress"]["kind"] for e in events]
    assert KIND_HEARTBEAT in kinds
    assert events[-1]["plan_progress"]["status"] == STATUS_DONE


def test_run_planning_stage_emits_failed_and_reraises():
    events = []

    async def emit(event):
        events.append(event)

    async def runner():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        asyncio.run(run_planning_stage(emit, stage="scout", runner=runner))

    assert events[-1]["plan_progress"]["status"] == STATUS_FAILED
    assert events[-1]["plan_progress"]["text"] == "boom"


def test_run_planning_stage_cancels_inner_task_on_outer_cancel():
    events = []
    cancelled = {"value": False}

    async def emit(event):
        events.append(event)

    async def runner():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled["value"] = True
            raise

    async def scenario():
        task = asyncio.ensure_future(
            run_planning_stage(
                emit, stage="scout", runner=runner, heartbeat_interval_s=0.01
            )
        )
        await asyncio.sleep(0.03)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    # (b) inner runner task actually ended cancelled
    assert cancelled["value"] is True
    # (a) a failed event with text "已取消" was emitted for the stage
    failed = [e for e in events if e["plan_progress"]["status"] == STATUS_FAILED]
    assert failed
    assert failed[-1]["plan_progress"]["text"] == "已取消"


def test_stream_progress_emitter_throttles_and_flushes():
    """D1 override: 3rd delta crosses char threshold (10 chars) so it flushes.

    Also covers the TIME-based flush branch with a small flush interval.
    """
    events = []

    async def emit(event):
        events.append(event)

    async def scenario():
        on_delta = make_stream_progress_emitter(
            emit, stage="decompose", flush_chars=10, flush_interval_s=10
        )
        await on_delta("reasoning", "12345")
        await on_delta("reasoning", "67890")
        # 3rd delta is 10 chars (crosses flush_chars=10 threshold), kind "message"
        await on_delta("message", "abcdefghij")

    asyncio.run(scenario())

    texts = [e["plan_progress"]["text"] for e in events]
    kinds = [e["plan_progress"]["kind"] for e in events]
    assert texts == ["1234567890", "abcdefghij"]
    assert kinds == ["reasoning", "message"]

    # --- TIME-based flush path: sub-threshold chars, interval elapsed ---
    time_events = []

    async def time_emit(event):
        time_events.append(event)

    async def time_scenario():
        on_delta = make_stream_progress_emitter(
            time_emit, stage="decompose", flush_chars=1000, flush_interval_s=0.05
        )
        # sub-threshold delta stays buffered (no char flush, interval not elapsed)
        await on_delta("reasoning", "abc")
        assert time_events == []
        await asyncio.sleep(0.06)
        # one more small delta flushes the buffer via the time path
        await on_delta("reasoning", "def")

    asyncio.run(time_scenario())

    assert len(time_events) == 1
    assert time_events[0]["plan_progress"]["text"] == "abcdef"
    assert time_events[0]["plan_progress"]["kind"] == "reasoning"
