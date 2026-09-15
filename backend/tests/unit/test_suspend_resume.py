"""A4 Suspend-Resume 联动单元测试。

覆盖三条链路的衔接：

1. ``StreamRegistry.suspend`` —— 活跃流挂起（状态 / 事件 / SENTINEL）；
2. ``ChatService.sleep_for / sleep_until / wake_on`` —— 挂起 API 注册
   wake（WakeStore 落库 + 审计事件 + 指标；未装配时降级 no-op）；
3. ``WakeScheduler.tick / start / stop`` —— 消费到期 wake 并调用
   resumer 恢复会话（fire-once、错误隔离、catch-up）。

全部用例不触网、不起 HTTP：ports 用既有 mock adapter，resumer 用记录器。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from unittest.mock import MagicMock

import pytest

from backend.adapters.out.event.stdout_adapter import StdoutEventAdapter
from backend.adapters.out.llm.mock_adapter import MockLLMAdapter
from backend.adapters.out.metric.noop_adapter import NoopMetricAdapter
from backend.adapters.out.storage.memory_adapter import MemoryStorageAdapter
from backend.api.chat_stream_registry import SENTINEL, StreamRegistry
from backend.application.services.chat_service import ChatService
from backend.application.services.wake_store import WakeStore
from backend.domain.wake import Wake, WakeKind, WakeState, to_utc_iso
from backend.orchestration.wake_scheduler import WakeScheduler

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# 测试替身
# --------------------------------------------------------------------------- #


class RecordingEventAdapter:
    """记录所有 emit 的事件（name, payload），供断言使用。"""

    def __init__(self) -> None:
        self.events: List[tuple] = []

    def emit(self, name: str, payload: dict) -> None:
        self.events.append((name, payload))

    def names(self) -> List[str]:
        return [name for name, _ in self.events]


class RecordingMetricAdapter:
    """记录 counter 调用。"""

    def __init__(self) -> None:
        self.counters: List[tuple] = []

    def counter(self, name: str, labels: dict) -> None:
        self.counters.append((name, dict(labels)))

    def gauge(self, name: str, value: float, labels: dict) -> None:  # noqa: ARG002
        pass

    def histogram(self, name: str, value: float, labels: dict) -> None:  # noqa: ARG002
        pass


class RecordingResumer:
    """记录被恢复的 wake；可选对指定 wake 抛错。"""

    def __init__(self, fail_ids: Optional[set] = None) -> None:
        self.resumed: List[Wake] = []
        self.fail_ids = fail_ids or set()

    async def __call__(self, wake: Wake) -> None:
        if wake.id in self.fail_ids:
            raise RuntimeError(f"resume failed for {wake.id}")
        self.resumed.append(wake)


def _make_service(
    *,
    wake_store: Optional[WakeStore] = None,
    events=None,
    metrics=None,
) -> ChatService:
    return ChatService(
        llm=MockLLMAdapter(responses=[]),
        tools=MagicMock(),  # 挂起路径不使用 tools
        skills=None,
        storage=MemoryStorageAdapter(),
        metrics=metrics or NoopMetricAdapter(),
        events=events or StdoutEventAdapter(verbose=False),
        wake_store=wake_store,
    )


def _past_iso(seconds: float = 1.0) -> str:
    return to_utc_iso(datetime.now(timezone.utc) - timedelta(seconds=seconds))  # noqa: UP017


async def _wait_until(pred, timeout_s: float = 2.0) -> None:
    """轮询等待断言条件，超时 fail（控制异步用例的时序抖动）。"""
    for _ in range(int(timeout_s / 0.02)):
        if pred():
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"condition not met within {timeout_s}s")


# --------------------------------------------------------------------------- #
# 1. StreamRegistry.suspend
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio()
async def test_registry_suspend_sets_state_and_enqueues_event():
    reg = StreamRegistry()

    async def producer(entry) -> None:
        await entry.queue.put({"state": "thinking"})
        ok = await reg.suspend("sid-1", wake_id="wake-abc", note="sleep 30s")
        assert ok is True

    entry = await reg.create("sid-1", queue_maxsize=10, producer=producer, session_id="sess-1")
    await entry.task  # producer 跑完

    assert entry.suspended is True
    assert entry.status == "suspended"  # 不被 _run_producer 的 done 兜底覆盖
    assert entry.session_id == "sess-1"
    assert entry.wake_id == "wake-abc"

    events = []
    while not entry.queue.empty():
        ev = entry.queue.get_nowait()
        if ev is SENTINEL:
            events.append("SENTINEL")
            break
        events.append(ev["state"])
    # suspended 事件先于框架补发的 SENTINEL
    assert events == ["thinking", "suspended", "SENTINEL"]


@pytest.mark.asyncio()
async def test_registry_suspend_unknown_or_finished_stream_returns_false():
    reg = StreamRegistry()
    assert await reg.suspend("nope") is False

    async def quick(entry) -> None:
        return None

    entry = await reg.create("sid-1", queue_maxsize=10, producer=quick)
    await entry.task
    assert entry.status == "done"
    assert await reg.suspend("sid-1") is False  # 已结束的流不可挂起


# --------------------------------------------------------------------------- #
# 2. ChatService 挂起 API
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio()
async def test_sleep_for_registers_timer_wake_with_fire_at_about_now_plus_seconds():
    store = WakeStore()
    events = RecordingEventAdapter()
    metrics = RecordingMetricAdapter()
    service = _make_service(wake_store=store, events=events, metrics=metrics)

    wake = await service.sleep_for("sess-1", 30, note="轮询构建")
    assert wake is not None
    assert wake.kind is WakeKind.TIMER

    persisted = store.get_wake(wake.id)
    assert persisted.session_id == "sess-1"
    fire_at = datetime.fromisoformat(persisted.fire_at)
    expected = datetime.now(timezone.utc) + timedelta(seconds=30)  # noqa: UP017
    assert abs((fire_at - expected).total_seconds()) < 5

    assert "session_suspended" in events.names()
    assert ("sage_wakes_created_total", {"kind": "timer"}) in metrics.counters


@pytest.mark.asyncio()
async def test_sleep_until_accepts_iso_string_and_naive_datetime():
    store = WakeStore()
    service = _make_service(wake_store=store)

    when_iso = "2026-08-01T09:00:00"  # naive → 按 UTC 解释
    w1 = await service.sleep_until("sess-1", when_iso)
    assert w1.fire_at == "2026-08-01T09:00:00+00:00"

    when_dt = datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone(timedelta(hours=8)))
    w2 = await service.sleep_until("sess-1", when_dt)
    assert w2.fire_at == "2026-08-01T02:00:00+00:00"  # +08:00 → UTC


@pytest.mark.asyncio()
async def test_sleep_for_without_wake_store_is_noop():
    service = _make_service(wake_store=None)
    assert await service.sleep_for("sess-1", 30) is None


@pytest.mark.asyncio()
async def test_suspend_api_input_validation():
    service = _make_service(wake_store=WakeStore())

    with pytest.raises(ValueError, match="seconds"):
        await service.sleep_for("s", -1)
    with pytest.raises(ValueError, match="ISO-8601"):
        await service.sleep_until("s", "not-a-timestamp")
    with pytest.raises(TypeError, match="datetime"):
        await service.sleep_until("s", 12345)
    with pytest.raises(ValueError, match="job_id"):
        await service.wake_on("s", "  ")


@pytest.mark.asyncio()
async def test_wake_on_registers_completion_wake():
    store = WakeStore()
    service = _make_service(wake_store=store)

    wake = await service.wake_on("sess-1", "job-42", note="等后台导出")
    assert wake.kind is WakeKind.COMPLETION
    assert store.get_wake(wake.id).job_id == "job-42"
    # 任务未完成 → 不到期
    assert store.get_due_wakes() == []


# --------------------------------------------------------------------------- #
# 3. WakeScheduler
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio()
async def test_tick_resumes_due_wakes_and_marks_fired():
    store = WakeStore()
    wake = store.add_wake(Wake.create("sess-1", WakeKind.TIMER, fire_at=_past_iso()))
    resumer = RecordingResumer()
    scheduler = WakeScheduler(store, resumer, tick_seconds=30.0)

    resumed_count = await scheduler.tick()
    assert resumed_count == 1
    assert [w.id for w in resumer.resumed] == [wake.id]

    persisted = store.get_wake(wake.id)
    assert persisted.state is WakeState.FIRED
    assert persisted.fired_at is not None
    assert store.get_due_wakes() == []


@pytest.mark.asyncio()
async def test_tick_skips_future_timer_wakes():
    store = WakeStore()
    store.add_wake(
        Wake.create(
            "s",
            WakeKind.TIMER,
            fire_at=to_utc_iso(datetime.now(timezone.utc) + timedelta(hours=1)),  # noqa: UP017
        )
    )
    resumer = RecordingResumer()
    assert await WakeScheduler(store, resumer, tick_seconds=30.0).tick() == 0
    assert resumer.resumed == []


@pytest.mark.asyncio()
async def test_tick_resumer_error_is_isolated_and_wake_still_fired():
    store = WakeStore()
    bad = store.add_wake(Wake.create("s1", WakeKind.TIMER, fire_at=_past_iso(10)))
    good = store.add_wake(Wake.create("s2", WakeKind.TIMER, fire_at=_past_iso(1)))
    resumer = RecordingResumer(fail_ids={bad.id})

    resumed_count = await WakeScheduler(store, resumer, tick_seconds=30.0).tick()
    # bad 抛错不计入 resumed，但两条都已消费（fire-once）
    assert resumed_count == 1
    assert [w.id for w in resumer.resumed] == [good.id]
    assert store.get_wake(bad.id).state is WakeState.FIRED
    assert store.get_wake(good.id).state is WakeState.FIRED


@pytest.mark.asyncio()
async def test_completion_wake_flow_via_complete_job():
    store = WakeStore()
    wake = store.add_wake(Wake.create("sess-1", WakeKind.COMPLETION, job_id="job-7"))
    resumer = RecordingResumer()
    scheduler = WakeScheduler(store, resumer, tick_seconds=30.0)

    await scheduler.tick()  # job 未完成 → 无操作
    assert resumer.resumed == []

    store.complete_job("job-7")
    assert await scheduler.tick() == 1
    assert [w.id for w in resumer.resumed] == [wake.id]


@pytest.mark.asyncio()
async def test_start_runs_catchup_then_stop_cancels_loop():
    store = WakeStore()
    store.add_wake(Wake.create("sess-1", WakeKind.TIMER, fire_at=_past_iso()))
    resumer = RecordingResumer()
    scheduler = WakeScheduler(store, resumer, tick_seconds=0.05)

    scheduler.start()
    scheduler.start()  # 幂等
    await _wait_until(lambda: len(resumer.resumed) == 1)
    await scheduler.stop()
    await scheduler.stop()  # 幂等

    # stop 后不再消费新到期的 wake
    store.add_wake(Wake.create("sess-1", WakeKind.TIMER, fire_at=_past_iso()))
    await asyncio.sleep(0.1)
    assert len(resumer.resumed) == 1


# --------------------------------------------------------------------------- #
# 4. 端到端：挂起 → 注册 wake → tick 恢复
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio()
async def test_end_to_end_suspend_then_wake_resumes_session():
    """模拟 producer 自挂起 + scheduler 唤醒的完整链路。"""
    store = WakeStore()
    registry = StreamRegistry()
    service = _make_service(wake_store=store)
    resumer = RecordingResumer()

    async def producer(entry) -> None:
        wake = await service.sleep_for("sess-1", 0, note="马上回来")
        await registry.suspend(entry_stream_id, wake_id=wake.id, note=wake.note)

    entry_stream_id = "stream-e2e"
    entry = await registry.create(
        entry_stream_id, queue_maxsize=10, producer=producer, session_id="sess-1"
    )
    await entry.task

    # 流已挂起，wake 已登记（sleep_for(0) → 立即到期）
    assert entry.suspended is True
    pending = store.pending(session_id="sess-1")
    assert len(pending) == 1

    scheduler = WakeScheduler(store, resumer, tick_seconds=30.0)
    assert await scheduler.tick() == 1
    assert resumer.resumed[0].session_id == "sess-1"
    assert resumer.resumed[0].note == "马上回来"
    assert store.pending(session_id="sess-1") == []
