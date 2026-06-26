"""
Lane Registry - manages lane lifecycle and heartbeat monitoring.

Provides high-level operations for lane management:
- Create lanes for tasks
- Bind agents to lanes
- Track lane state transitions
- Update heartbeats and detect stalls
- Query lanes by status/task
"""

from __future__ import annotations

import uuid

from backend.data.orchestration_repo import LaneRepository
from backend.orchestration.models import (
    HeartbeatStatus,
    Lane,
    LaneStatus,
)


class LaneRegistry:
    """
    Manages lane lifecycle and heartbeat monitoring.

    Lanes decouple task definition from execution. Each lane is bound to a
    specific agent and tracks execution health via heartbeats.
    """

    def __init__(self, repo: LaneRepository | None = None) -> None:
        self.repo = repo or LaneRepository()

    def create_lane(
        self,
        task_id: str,
        worktree: str | None = None,
    ) -> Lane:
        """
        Create a new lane for a task.

        Args:
            task_id: Task to execute
            worktree: Optional isolated filesystem workspace

        Returns:
            Created Lane object
        """
        lane_id = f"lane-{uuid.uuid4().hex[:12]}"
        lane = Lane(
            lane_id=lane_id,
            task_id=task_id,
            worktree=worktree,
        )

        self.repo.create(lane)
        return lane

    def get_lane(self, lane_id: str) -> Lane | None:
        """Fetch a lane by ID."""
        return self.repo.get(lane_id)

    def bind_agent(self, lane_id: str, agent_id: str) -> bool:
        """Bind an agent to a lane."""
        lane = self.repo.get(lane_id)
        if not lane:
            return False

        try:
            lane.bind_agent(agent_id)
            return self.repo.update(lane)
        except ValueError:
            return False

    def mark_ready(self, lane_id: str) -> bool:
        """Transition lane to READY state."""
        lane = self.repo.get(lane_id)
        if not lane:
            return False

        try:
            lane.mark_ready()
            return self.repo.update(lane)
        except ValueError:
            return False

    def mark_running(self, lane_id: str) -> bool:
        """Transition lane to RUNNING state and initialize heartbeat."""
        lane = self.repo.get(lane_id)
        if not lane:
            return False

        try:
            lane.mark_running()
            return self.repo.update(lane)
        except ValueError:
            return False

    def mark_succeeded(self, lane_id: str) -> bool:
        """Transition lane to SUCCEEDED state."""
        lane = self.repo.get(lane_id)
        if not lane:
            return False

        try:
            lane.mark_succeeded()
            return self.repo.update(lane)
        except ValueError:
            return False

    def mark_failed(self, lane_id: str, error: str | None = None) -> bool:
        """Transition lane to FAILED state."""
        lane = self.repo.get(lane_id)
        if not lane:
            return False

        try:
            lane.mark_failed(error)
            return self.repo.update(lane)
        except ValueError:
            return False

    def mark_blocked(self, lane_id: str) -> bool:
        """Transition lane to BLOCKED state."""
        lane = self.repo.get(lane_id)
        if not lane:
            return False

        try:
            lane.mark_blocked()
            return self.repo.update(lane)
        except ValueError:
            return False

    def mark_stopped(self, lane_id: str) -> bool:
        """Transition lane to STOPPED state (cancelled)."""
        lane = self.repo.get(lane_id)
        if not lane:
            return False

        try:
            lane.mark_stopped()
            return self.repo.update(lane)
        except ValueError:
            return False

    def update_heartbeat(self, lane_id: str) -> bool:
        """Update lane heartbeat timestamp."""
        lane = self.repo.get(lane_id)
        if not lane or not lane.heartbeat:
            return False

        lane.heartbeat.update_ping()
        return self.repo.update_heartbeat(lane_id, lane.heartbeat)

    def list_lanes_by_task(self, task_id: str) -> list[Lane]:
        """List all lanes for a task."""
        return self.repo.list_by_task(task_id)

    def list_lanes_by_agent(self, agent_id: str) -> list[Lane]:
        """List all lanes assigned to an agent."""
        return self.repo.list_by_agent(agent_id)

    def list_lanes_by_status(self, status: LaneStatus, limit: int = 100) -> list[Lane]:
        """List lanes by status."""
        return self.repo.list_by_status(status, limit)

    def list_all_lanes(self) -> list[Lane]:
        """List all lanes."""
        return self.repo.list_all()

    def update_lane(self, lane: Lane) -> bool:
        """Update a lane in the database."""
        return self.repo.update(lane)

    def update_lane_status(self, lane_id: str, status: LaneStatus) -> bool:
        """Update lane status."""
        lane = self.repo.get(lane_id)
        if not lane:
            return False
        lane.status = status
        return self.repo.update(lane)

    def get_stalled_lanes(self, stalled_after_ms: int = 300_000) -> list[Lane]:
        """
        Get lanes with stalled heartbeats.

        Args:
            stalled_after_ms: Threshold in milliseconds (default 5 minutes)

        Returns:
            List of lanes with STALLED or TRANSPORT_DEAD heartbeat status
        """
        import time

        now_ms = int(time.time() * 1000)
        running_lanes = self.repo.list_by_status(LaneStatus.RUNNING)

        stalled = []
        for lane in running_lanes:
            if not lane.heartbeat:
                continue

            age = now_ms - lane.heartbeat.last_ping_at
            if not lane.heartbeat.transport_alive or age > stalled_after_ms * 2:
                lane.heartbeat.status = HeartbeatStatus.TRANSPORT_DEAD
                self.repo.update(lane)
                stalled.append(lane)
            elif age > stalled_after_ms:
                lane.heartbeat.status = HeartbeatStatus.STALLED
                self.repo.update(lane)
                stalled.append(lane)

        return stalled

    def delete_lane(self, lane_id: str) -> bool:
        """Delete a lane."""
        return self.repo.delete(lane_id)
