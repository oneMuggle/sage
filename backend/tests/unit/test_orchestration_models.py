"""
Unit tests for orchestration data models.

Tests cover:
- Task state transitions and validation
- Lane state transitions and validation
- Team state transitions
- TaskPacket configuration
- Dependency relationships (blocks/blocked_by)
"""
import pytest

from backend.orchestration.models import (
    EscalationPolicy,
    HeartbeatStatus,
    Lane,
    LaneHeartbeat,
    LaneStatus,
    RecoveryPolicy,
    Task,
    TaskPacket,
    TaskStatus,
    Team,
    TeamStatus,
)


class TestTaskStatus:
    """Test Task state machine."""

    def test_terminal_states(self):
        """COMPLETED, FAILED, STOPPED are terminal."""
        assert TaskStatus.COMPLETED.is_terminal()
        assert TaskStatus.FAILED.is_terminal()
        assert TaskStatus.STOPPED.is_terminal()
        assert not TaskStatus.CREATED.is_terminal()
        assert not TaskStatus.RUNNING.is_terminal()
        assert not TaskStatus.BLOCKED.is_terminal()


class TestTask:
    """Test Task model."""

    def test_create_task(self):
        """Task creation with defaults."""
        task = Task(task_id="task-123", name="test", description="desc")
        assert task.task_id == "task-123"
        assert task.name == "test"
        assert task.status == TaskStatus.CREATED
        assert task.priority == 0
        assert task.blocks == []
        assert task.blocked_by == []

    def test_mark_running(self):
        """Task can transition from CREATED to RUNNING."""
        task = Task(task_id="task-123", name="test", description="desc")
        task.mark_running()
        assert task.status == TaskStatus.RUNNING
        assert task.started_at is not None

    def test_mark_running_invalid_state(self):
        """Cannot mark RUNNING from non-CREATED state."""
        task = Task(task_id="task-123", name="test", description="desc")
        task.mark_running()
        with pytest.raises(ValueError, match="Cannot mark running"):
            task.mark_running()

    def test_mark_completed(self):
        """Task can transition from RUNNING to COMPLETED."""
        task = Task(task_id="task-123", name="test", description="desc")
        task.mark_running()
        task.mark_completed(result={"output": "success"})
        assert task.status == TaskStatus.COMPLETED
        assert task.completed_at is not None
        assert task.result == {"output": "success"}

    def test_mark_completed_invalid_state(self):
        """Cannot complete from non-RUNNING state."""
        task = Task(task_id="task-123", name="test", description="desc")
        with pytest.raises(ValueError, match="Cannot complete"):
            task.mark_completed()

    def test_mark_failed(self):
        """Task can transition from RUNNING to FAILED."""
        task = Task(task_id="task-123", name="test", description="desc")
        task.mark_running()
        task.mark_failed(error="timeout")
        assert task.status == TaskStatus.FAILED
        assert task.parameters["error"] == "timeout"

    def test_mark_blocked(self):
        """Task can transition from CREATED to BLOCKED."""
        task = Task(task_id="task-123", name="test", description="desc")
        task.mark_blocked()
        assert task.status == TaskStatus.BLOCKED

    def test_mark_stopped(self):
        """Task can be stopped from non-terminal state."""
        task = Task(task_id="task-123", name="test", description="desc")
        task.mark_stopped()
        assert task.status == TaskStatus.STOPPED
        assert task.completed_at is not None

    def test_mark_stopped_invalid_state(self):
        """Cannot stop from terminal state."""
        task = Task(task_id="task-123", name="test", description="desc")
        task.mark_running()
        task.mark_completed()
        with pytest.raises(ValueError, match="Cannot stop"):
            task.mark_stopped()

    def test_dependency_fields(self):
        """Task tracks blocks and blocked_by relationships."""
        task1 = Task(task_id="task-1", name="t1", description="d1")
        task2 = Task(task_id="task-2", name="t2", description="d2", blocked_by=["task-1"])

        assert task2.blocked_by == ["task-1"]
        assert task1.blocks == []  # Not automatically updated


class TestTaskPacket:
    """Test TaskPacket configuration."""

    def test_create_packet(self):
        """TaskPacket creation with defaults."""
        packet = TaskPacket(objective="Analyze code")
        assert packet.objective == "Analyze code"
        assert packet.permission_profile == "workspace-write"
        assert packet.timeout_secs == 600
        assert isinstance(packet.recovery_policy, RecoveryPolicy)
        assert isinstance(packet.escalation_policy, EscalationPolicy)

    def test_recovery_policy(self):
        """RecoveryPolicy configuration."""
        policy = RecoveryPolicy(on_failure="retry", max_retries=3)
        assert policy.on_failure == "retry"
        assert policy.max_retries == 3
        assert len(policy.retry_backoff_secs) == 3

    def test_escalation_policy(self):
        """EscalationPolicy configuration."""
        policy = EscalationPolicy(
            after_retries="notify-human",
            notify_channels=["discord", "email"]
        )
        assert policy.after_retries == "notify-human"
        assert len(policy.notify_channels) == 2


class TestLaneStatus:
    """Test Lane state machine."""

    def test_terminal_states(self):
        """SUCCEEDED, FAILED, STOPPED are terminal."""
        assert LaneStatus.SUCCEEDED.is_terminal()
        assert LaneStatus.FAILED.is_terminal()
        assert LaneStatus.STOPPED.is_terminal()
        assert not LaneStatus.CREATED.is_terminal()
        assert not LaneStatus.RUNNING.is_terminal()


class TestLane:
    """Test Lane model."""

    def test_create_lane(self):
        """Lane creation with defaults."""
        lane = Lane(lane_id="lane-123", task_id="task-456")
        assert lane.lane_id == "lane-123"
        assert lane.task_id == "task-456"
        assert lane.status == LaneStatus.CREATED
        assert lane.agent_id is None

    def test_bind_agent(self):
        """Agent can be bound to CREATED lane."""
        lane = Lane(lane_id="lane-123", task_id="task-456")
        lane.bind_agent("agent-primary")
        assert lane.agent_id == "agent-primary"

    def test_bind_agent_invalid_state(self):
        """Cannot bind agent to non-CREATED lane."""
        lane = Lane(lane_id="lane-123", task_id="task-456")
        lane.mark_ready()
        with pytest.raises(ValueError, match="Cannot bind agent"):
            lane.bind_agent("agent-primary")

    def test_lifecycle_transitions(self):
        """Lane follows CREATED -> READY -> RUNNING -> SUCCEEDED."""
        lane = Lane(lane_id="lane-123", task_id="task-456")

        lane.mark_ready()
        assert lane.status == LaneStatus.READY

        lane.mark_running()
        assert lane.status == LaneStatus.RUNNING
        assert lane.heartbeat is not None
        assert lane.started_at is not None

        lane.mark_succeeded()
        assert lane.status == LaneStatus.SUCCEEDED
        assert lane.completed_at is not None

    def test_mark_failed(self):
        """Lane can fail with error message."""
        lane = Lane(lane_id="lane-123", task_id="task-456")
        lane.mark_ready()
        lane.mark_running()
        lane.mark_failed(error="timeout")
        assert lane.status == LaneStatus.FAILED
        assert lane.error == "timeout"


class TestLaneHeartbeat:
    """Test LaneHeartbeat model."""

    def test_create_heartbeat(self):
        """Heartbeat creation with defaults."""
        hb = LaneHeartbeat(last_ping_at=1719398400000)
        assert hb.last_ping_at == 1719398400000
        assert hb.transport_alive is True
        assert hb.status == HeartbeatStatus.HEALTHY

    def test_update_ping(self):
        """Update ping timestamp and reset status."""
        hb = LaneHeartbeat(last_ping_at=1719398400000)
        hb.status = HeartbeatStatus.STALLED
        hb.update_ping()
        assert hb.last_ping_at > 1719398400000
        assert hb.status == HeartbeatStatus.HEALTHY


class TestTeam:
    """Test Team model."""

    def test_create_team(self):
        """Team creation with defaults."""
        team = Team(team_id="team-123", name="analysis")
        assert team.team_id == "team-123"
        assert team.name == "analysis"
        assert team.status == TeamStatus.CREATED
        assert team.task_ids == []

    def test_add_task(self):
        """Add task to team."""
        team = Team(team_id="team-123", name="analysis")
        team.add_task("task-1")
        team.add_task("task-2")
        assert len(team.task_ids) == 2
        assert "task-1" in team.task_ids

    def test_add_duplicate_task(self):
        """Adding duplicate task is idempotent."""
        team = Team(team_id="team-123", name="analysis")
        team.add_task("task-1")
        team.add_task("task-1")
        assert len(team.task_ids) == 1

    def test_remove_task(self):
        """Remove task from team."""
        team = Team(team_id="team-123", name="analysis")
        team.add_task("task-1")
        team.add_task("task-2")
        team.remove_task("task-1")
        assert len(team.task_ids) == 1
        assert "task-1" not in team.task_ids

    def test_team_status_transitions(self):
        """Team follows CREATED -> RUNNING -> COMPLETED."""
        team = Team(team_id="team-123", name="analysis")

        team.mark_running()
        assert team.status == TeamStatus.RUNNING

        team.mark_completed()
        assert team.status == TeamStatus.COMPLETED

    def test_mark_cancelled(self):
        """Team can be cancelled from non-terminal state."""
        team = Team(team_id="team-123", name="analysis")
        team.mark_cancelled()
        assert team.status == TeamStatus.CANCELLED

    def test_mark_cancelled_invalid_state(self):
        """Cannot cancel from terminal state."""
        team = Team(team_id="team-123", name="analysis")
        team.mark_running()
        team.mark_completed()
        with pytest.raises(ValueError, match="Cannot cancel"):
            team.mark_cancelled()
