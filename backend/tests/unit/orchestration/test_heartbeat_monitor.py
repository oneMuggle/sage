"""R116 — HeartbeatMonitor 单元测试（车道心跳健康监控）。

覆盖：健康/stalled/dead/transport_dead 四路径、回调触发、monitor 生命周期、
lane_registry 交互。全部用 fake registry 和 SimpleNamespace lane 替身。
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from backend.orchestration.heartbeat import HeartbeatMonitor
from backend.orchestration.models import HeartbeatStatus, LaneStatus

pytestmark = pytest.mark.unit


def _make_lane(lane_id="lane-1", ping_offset_s=0.0, transport_alive=True, status=LaneStatus.RUNNING):
    """创建带心跳的 fake lane。"""
    return SimpleNamespace(
        id=lane_id,
        status=status,
        heartbeat=SimpleNamespace(
            last_ping_at=int((time.time() + ping_offset_s) * 1000),
            transport_alive=transport_alive,
            status=HeartbeatStatus.HEALTHY,
        ),
    )


class _FakeRegistry:
    def __init__(self, lanes=None):
        self._lanes = lanes or []
        self.updated = []

    def list_lanes_by_status(self, status):
        return [ln for ln in self._lanes if ln.status == status]

    def update_lane(self, lane):
        self.updated.append(lane)
        return True


@pytest.fixture()
def callbacks():
    return {"stalled": [], "dead": []}


@pytest.fixture()
def make_monitor(callbacks):
    def _make(lanes, **kwargs):
        return HeartbeatMonitor(
            _FakeRegistry(lanes),
            check_interval=0.1,
            stalled_after=300.0,
            dead_after=600.0,
            on_stalled=lambda lane: callbacks["stalled"].append(lane),
            on_dead=lambda lane: callbacks["dead"].append(lane),
            **kwargs,
        )
    return _make


@pytest.mark.asyncio()
async def test_healthy_lane_stays_healthy(make_monitor, callbacks):
    """心跳新鲜 → HEALTHY，无回调触发。"""
    fresh = _make_lane(ping_offset_s=0)
    monitor = make_monitor([fresh], stalled_after=300.0, dead_after=600.0)
    await monitor.check_heartbeats()
    assert fresh.heartbeat.status == HeartbeatStatus.HEALTHY
    assert callbacks["stalled"] == []
    assert callbacks["dead"] == []


@pytest.mark.asyncio()
async def test_stalled_lane_triggers_on_stalled(make_monitor, callbacks):
    """心跳超过 stalled_after 但未超过 dead_after → STALLED + 回调。"""
    stale = _make_lane(ping_offset_s=-400)  # 400s 前 ping
    monitor = HeartbeatMonitor(
        _FakeRegistry([stale]),
        stalled_after=300.0,
        dead_after=600.0,
        on_stalled=lambda lane: callbacks["stalled"].append(lane),
        on_dead=lambda lane: callbacks["dead"].append(lane),
    )
    await monitor.check_heartbeats()
    assert stale.heartbeat.status == HeartbeatStatus.STALLED
    assert len(callbacks["stalled"]) == 1
    assert callbacks["dead"] == []


@pytest.mark.asyncio()
async def test_dead_lane_triggers_on_dead(make_monitor, callbacks):
    """心跳超过 dead_after → TRANSPORT_DEAD + on_dead 回调。"""
    dead = _make_lane(ping_offset_s=-700)
    monitor = HeartbeatMonitor(
        _FakeRegistry([dead]),
        stalled_after=300.0,
        dead_after=600.0,
        on_dead=lambda lane: callbacks["dead"].append(lane),
    )
    await monitor.check_heartbeats()
    assert dead.heartbeat.status == HeartbeatStatus.TRANSPORT_DEAD
    assert len(callbacks["dead"]) == 1
    assert callbacks["stalled"] == []


@pytest.mark.asyncio()
async def test_transport_dead_immediately_triggers_on_dead(make_monitor, callbacks):
    """transport_alive=False → 立即标记 TRANSPORT_DEAD。"""
    dead_transport = _make_lane(transport_alive=False)
    monitor = HeartbeatMonitor(
        _FakeRegistry([dead_transport]),
        stalled_after=300.0,
        dead_after=600.0,
        on_dead=lambda lane: callbacks["dead"].append(lane),
    )
    await monitor.check_heartbeats()
    assert dead_transport.heartbeat.status == HeartbeatStatus.TRANSPORT_DEAD
    assert len(callbacks["dead"]) == 1


@pytest.mark.asyncio()
async def test_no_heartbeat_skipped(make_monitor, callbacks):
    """heartbeat=None 的 lane 被跳过不报错。"""
    lane_no_hb = _make_lane()
    lane_no_hb.heartbeat = None
    monitor = make_monitor([lane_no_hb], stalled_after=300.0, dead_after=600.0)
    await monitor.check_heartbeats()  # 不应抛错
    assert lane_no_hb.heartbeat is None


@pytest.mark.asyncio()
async def test_mixed_lanes_each_get_correct_status(make_monitor, callbacks):
    """多种状态混合 → 各自正确标记。"""
    healthy = _make_lane("h", ping_offset_s=0)
    stalled = _make_lane("s", ping_offset_s=-400)
    dead = _make_lane("d", ping_offset_s=-700)
    monitor = HeartbeatMonitor(
        _FakeRegistry([healthy, stalled, dead]),
        stalled_after=300.0,
        dead_after=600.0,
        on_stalled=lambda lane: callbacks["stalled"].append(lane),
        on_dead=lambda lane: callbacks["dead"].append(lane),
    )
    await monitor.check_heartbeats()
    assert healthy.heartbeat.status == HeartbeatStatus.HEALTHY
    assert stalled.heartbeat.status == HeartbeatStatus.STALLED
    assert dead.heartbeat.status == HeartbeatStatus.TRANSPORT_DEAD


@pytest.mark.asyncio()
async def test_non_running_lanes_not_checked(make_monitor, callbacks):
    """非 RUNNING 状态的 lane 不参与检查。"""
    done_lane = _make_lane(status=LaneStatus.COMPLETED)
    registry = _FakeRegistry([done_lane])
    monitor = HeartbeatMonitor(
        registry,
        stalled_after=300.0,
        dead_after=600.0,
    )
    await monitor.check_heartbeats()
    # LaneStatus.COMPLETED 不在 RUNNING 中 → list_lanes_by_status 返回空 → 无变化
    assert done_lane.heartbeat.status == HeartbeatStatus.HEALTHY  # 初始值不变


@pytest.mark.asyncio()
async def test_monitor_start_stop_lifecycle():
    """start/stop 正确管理 background task。"""
    registry = _FakeRegistry([])
    monitor = HeartbeatMonitor(registry, check_interval=0.05)
    assert monitor._monitor_task is None

    await monitor.start()
    assert monitor._monitor_task is not None

    await monitor.stop()
    assert monitor._monitor_task is None

    # 重复 start 不创建多个 task
    await monitor.start()
    task1 = monitor._monitor_task
    await monitor.start()
    assert monitor._monitor_task is task1
    await monitor.stop()


@pytest.mark.asyncio()
async def test_stop_on_never_started_is_safe():
    """stop() 在从未 start 时安全（不应抛错）。"""
    monitor = HeartbeatMonitor(_FakeRegistry([]))
    await monitor.stop()  # must not raise
