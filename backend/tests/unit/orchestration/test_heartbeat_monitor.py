"""R116 — HeartbeatMonitor 车道心跳监控单元测试。

覆盖 HEALTHY/STALLED/TRANSPORT_DEAD 状态转换、回调触发、
transport_alive 检查、heartbeat=None 安全跳过、生命周期管理。
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from backend.orchestration.heartbeat import HeartbeatMonitor
from backend.orchestration.models import HeartbeatStatus, LaneStatus

pytestmark = pytest.mark.unit

DAY_S = 86_400


def _make_lane(lane_id="lane-1", ping_ago_s=0.0, transport_alive=True,
               status=LaneStatus.RUNNING):
    """创建带心跳的 fake lane（last_ping_at 用秒，与 time.time() 同单位）。"""
    return SimpleNamespace(
        id=lane_id,
        status=status,
        heartbeat=SimpleNamespace(
            last_ping_at=time.time() - ping_ago_s,
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


def _make_monitor(lanes, **kw):
    stalled = []
    dead = []

    async def on_stalled(lane):
        stalled.append(lane)

    async def on_dead(lane):
        dead.append(lane)

    monitor = HeartbeatMonitor(
        _FakeRegistry(lanes),
        check_interval=kw.pop("check_interval", 0.1),
        stalled_after=kw.pop("stalled_after", 300.0),
        dead_after=kw.pop("dead_after", 600.0),
        on_stalled=on_stalled,
        on_dead=on_dead,
        **kw,
    )
    return monitor, stalled, dead


@pytest.mark.asyncio()
async def test_healthy_lane_stays_healthy():
    fresh = _make_lane(ping_ago_s=0)
    monitor, stalled, dead = _make_monitor([fresh])
    await monitor.check_heartbeats()
    assert fresh.heartbeat.status == HeartbeatStatus.HEALTHY
    assert not stalled
    assert not dead


@pytest.mark.asyncio()
async def test_stalled_lane_triggers_on_stalled():
    stale = _make_lane(ping_ago_s=400)
    monitor, stalled, dead = _make_monitor([stale])
    await monitor.check_heartbeats()
    assert stale.heartbeat.status == HeartbeatStatus.STALLED
    assert len(stalled) == 1
    assert not dead


@pytest.mark.asyncio()
async def test_dead_lane_triggers_on_dead():
    dead_lane = _make_lane(ping_ago_s=700)
    monitor, dead = _make_monitor([dead_lane])
    await monitor.check_heartbeats()
    assert dead_lane.heartbeat.status == HeartbeatStatus.TRANSPORT_DEAD
    assert len(dead) == 1


@pytest.mark.asyncio()
async def test_transport_dead_immediately_triggers_on_dead():
    lane = _make_lane(transport_alive=False)
    monitor, dead = _make_monitor([lane])
    await monitor.check_heartbeats()
    assert lane.heartbeat.status == HeartbeatStatus.TRANSPORT_DEAD
    assert len(dead) == 1


@pytest.mark.asyncio()
async def test_no_heartbeat_skipped():
    lane = _make_lane()
    lane.heartbeat = None
    monitor, _ = _make_monitor([lane])
    await monitor.check_heartbeats()


@pytest.mark.asyncio()
async def test_mixed_lanes_each_get_correct_status():
    healthy = _make_lane("h", ping_ago_s=0)
    stale = _make_lane("s", ping_ago_s=400)
    dead = _make_lane("d", ping_ago_s=700)
    monitor, stalled, dead = _make_monitor([healthy, stale, dead])
    await monitor.check_heartbeats()
    assert healthy.heartbeat.status == HeartbeatStatus.HEALTHY
    assert stale.heartbeat.status == HeartbeatStatus.STALLED
    assert dead.heartbeat.status == HeartbeatStatus.TRANSPORT_DEAD


@pytest.mark.asyncio()
async def test_non_running_lanes_not_checked():
    done = _make_lane(status=LaneStatus.SUCCEEDED)
    monitor, _ = _make_monitor([done])
    await monitor.check_heartbeats()
    assert done.heartbeat.status == HeartbeatStatus.HEALTHY


def test_monitor_start_stop_lifecycle():
    monitor = HeartbeatMonitor(_FakeRegistry([]), check_interval=0.05)
    assert monitor._monitor_task is None
    asyncio.run(monitor.start())
    assert monitor._monitor_task is not None
    task = monitor._monitor_task
    asyncio.run(monitor.start())
    assert monitor._monitor_task is task
    asyncio.run(monitor.stop())
    assert monitor._monitor_task is None


def test_stop_on_never_started_is_safe():
    HeartbeatMonitor(_FakeRegistry([])).stop()
