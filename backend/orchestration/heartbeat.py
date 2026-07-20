"""
Heartbeat monitoring system for detecting stalled lanes.

Periodically scans running lanes and detects:
- Stalled lanes (no heartbeat for too long)
- Transport dead lanes (agent process died)

Triggers recovery policies when issues are detected.
"""

import asyncio
import contextlib
import time
from typing import Callable
from typing import Optional

from backend.orchestration.models import HeartbeatStatus, LaneStatus


class HeartbeatMonitor:
    """Monitors lane heartbeats and detects stalled executions."""

    def __init__(
        self,
        lane_registry,
        check_interval: float = 30.0,
        stalled_after: float = 300.0,
        dead_after: float = 600.0,
        on_stalled: Optional[Callable] = None,
        on_dead: Optional[Callable] = None,
    ):
        """
        Initialize heartbeat monitor.

        Args:
            lane_registry: LaneRegistry instance to monitor
            check_interval: Seconds between heartbeat checks (default 30s)
            stalled_after: Seconds without heartbeat before marking stalled (default 5min)
            dead_after: Seconds without heartbeat before marking dead (default 10min)
            on_stalled: Callback when lane becomes stalled
            on_dead: Callback when lane becomes dead
        """
        self.lane_registry = lane_registry
        self.check_interval = check_interval
        self.stalled_after = stalled_after
        self.dead_after = dead_after
        self.on_stalled = on_stalled
        self.on_dead = on_dead
        self._monitor_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the heartbeat monitor background task."""
        if self._monitor_task is None:
            self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def stop(self):
        """Stop the heartbeat monitor background task."""
        if self._monitor_task is not None:
            self._monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor_task
            self._monitor_task = None

    async def _monitor_loop(self):
        """Main monitoring loop."""
        try:
            while True:
                await self.check_heartbeats()
                await asyncio.sleep(self.check_interval)
        except asyncio.CancelledError:
            raise

    async def check_heartbeats(self):
        """Check all running lanes for heartbeat health."""
        running_lanes = self.lane_registry.list_lanes_by_status(LaneStatus.RUNNING)

        now = time.time()
        for lane in running_lanes:
            if lane.heartbeat is None:
                continue

            age = now - lane.heartbeat.last_ping_at

            # Check if transport is dead
            if not lane.heartbeat.transport_alive:
                lane.heartbeat.status = HeartbeatStatus.TRANSPORT_DEAD
                self.lane_registry.update_lane(lane)
                if self.on_dead:
                    await self.on_dead(lane)
                continue

            # Check if dead (no heartbeat for too long)
            if age > self.dead_after:
                lane.heartbeat.status = HeartbeatStatus.TRANSPORT_DEAD
                self.lane_registry.update_lane(lane)
                if self.on_dead:
                    await self.on_dead(lane)
                continue

            # Check if stalled (no heartbeat for a while)
            if age > self.stalled_after:
                lane.heartbeat.status = HeartbeatStatus.STALLED
                self.lane_registry.update_lane(lane)
                if self.on_stalled:
                    await self.on_stalled(lane)
                continue

            # Healthy
            lane.heartbeat.status = HeartbeatStatus.HEALTHY
            self.lane_registry.update_lane(lane)
