"""
End-to-end tests for multi-agent orchestration layer (Phase 2).

Tests the full pipeline:
- Permission checks
- Heartbeat monitor
- Router dispatch
- Planner decomposition
- Registry integration
"""

import asyncio

import pytest

from backend.orchestration.heartbeat import HeartbeatMonitor
from backend.orchestration.models import (
    Agent,
    LaneStatus,
    Task,
    TaskStatus,
    TeamStatus,
)
from backend.orchestration.permission import (
    AgentAction,
    LanePermission,
    PermissionChecker,
    PermissionPreset,
)
from backend.orchestration.planner import Planner
from backend.orchestration.router import DispatchStrategy, Router

# ============================================================================
# Permission System Tests
# ============================================================================


class TestPermissionSystem:
    """Test the permission system end-to-end."""

    def test_audit_preset_blocks_writes(self):
        """AUDIT preset cannot write files."""
        perm = LanePermission(preset=PermissionPreset.AUDIT)
        checker = PermissionChecker(perm)

        # Read should be allowed
        assert checker.can_execute(AgentAction("read_file", "/tmp/test.txt"))
        # Write should be blocked
        assert not checker.can_execute(AgentAction("write_file", "/tmp/test.txt"))
        # Execute should be blocked
        assert not checker.can_execute(AgentAction("execute", "rm -rf /"))

    def test_implement_preset_allows_writes(self):
        """IMPLEMENT preset can write files."""
        perm = LanePermission(preset=PermissionPreset.IMPLEMENT)
        checker = PermissionChecker(perm)

        assert checker.can_execute(AgentAction("write_file", "/tmp/test.txt"))
        assert checker.can_execute(AgentAction("read_file", "/tmp/test.txt"))

    def test_path_restrictions(self):
        """Path restrictions limit file access scope."""
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            allowed_dir = os.path.join(tmpdir, "allowed")
            blocked_dir = os.path.join(tmpdir, "blocked")
            os.makedirs(allowed_dir)
            os.makedirs(blocked_dir)

            perm = LanePermission(preset=PermissionPreset.IMPLEMENT, allowed_paths=[allowed_dir])
            checker = PermissionChecker(perm)

            # Files in allowed dir should pass
            assert checker.can_execute(
                AgentAction("write_file", os.path.join(allowed_dir, "test.txt"))
            )
            # Files in blocked dir should fail
            assert not checker.can_execute(
                AgentAction("write_file", os.path.join(blocked_dir, "test.txt"))
            )

    def test_denied_tools(self):
        """Denied tools are always blocked."""
        perm = LanePermission(preset=PermissionPreset.IMPLEMENT, denied_tools=["shell"])
        checker = PermissionChecker(perm)

        assert not checker.can_execute(AgentAction("shell", "rm -rf /"))
        assert checker.can_execute(AgentAction("read_file", "/tmp/test.txt"))

    def test_assert_permission_raises(self):
        """assert_permission raises PermissionError on violation."""
        perm = LanePermission(preset=PermissionPreset.AUDIT)
        checker = PermissionChecker(perm)

        with pytest.raises(PermissionError):
            checker.assert_permission(AgentAction("write_file", "/tmp/test.txt"))


# ============================================================================
# Heartbeat Monitor Tests
# ============================================================================


class TestHeartbeatMonitor:
    """Test the heartbeat monitoring system."""

    def test_monitor_initialization(self):
        """Monitor can be initialized with custom thresholds."""

        class MockLaneRegistry:
            def list_by_status(self, status, limit=100):
                return []

        monitor = HeartbeatMonitor(
            lane_registry=MockLaneRegistry(),
            check_interval=10.0,
            stalled_after=60.0,
            dead_after=120.0,
        )
        assert monitor.check_interval == 10.0
        assert monitor.stalled_after == 60.0
        assert monitor.dead_after == 120.0
        assert monitor._monitor_task is None  # Not started yet

    def test_monitor_stop_without_start(self):
        """Monitor can be stopped even if never started."""
        from backend.data.orchestration_repo import LaneRepository

        # Use a real LaneRepository (will work even with empty DB)
        monitor = HeartbeatMonitor(
            lane_registry=LaneRepository(),
            check_interval=10.0,
        )
        # Should not raise
        asyncio.run(monitor.stop())


# ============================================================================
# Router Tests
# ============================================================================


class TestRouter:
    """Test the task router."""

    def test_router_initialization(self):
        """Router can be initialized with different strategies."""
        from backend.data.orchestration_repo import LaneRepository

        class MockAgentRegistry:
            def list_agents(self):
                return []

        for strategy in [
            DispatchStrategy.ROUND_ROBIN,
            DispatchStrategy.CAPABILITY_BASED,
            DispatchStrategy.LOAD_BASED,
        ]:
            router = Router(
                lane_registry=LaneRepository(),
                agent_registry=MockAgentRegistry(),
                strategy=strategy,
            )
            assert router.strategy == strategy

    def test_router_no_agents_raises(self):
        """Router raises ValueError when no agents available."""
        from backend.data.orchestration_repo import LaneRepository

        class EmptyAgentRegistry:
            def list_agents(self):
                return []

        router = Router(
            lane_registry=LaneRepository(),
            agent_registry=EmptyAgentRegistry(),
            strategy=DispatchStrategy.CAPABILITY_BASED,
        )

        task = Task(
            task_id="task-1",
            name="test",
            description="test task",
            task_type="coding",
        )

        with pytest.raises(ValueError, match="No agents available"):
            asyncio.run(router.route_task(task))

    def test_router_dispatches_to_capable_agent(self):
        """Router dispatches to agent with matching capability."""
        from backend.orchestration.lane_registry import LaneRegistry

        class MockAgentRegistry:
            def list_agents(self):
                return [
                    Agent(
                        agent_id="coder",
                        name="Coder",
                        capabilities=["coding", "testing"],
                    ),
                    Agent(
                        agent_id="researcher",
                        name="Researcher",
                        capabilities=["research", "analysis"],
                    ),
                ]

        # Use a real LaneRegistry with an in-memory DB
        import tempfile

        from backend.data.database import Database

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            db = Database(db_path=tmp_path)
            db.init_db()
            lane_registry = LaneRegistry()
            # Replace its repo's db with our test db
            lane_registry.repo.db = db

            router = Router(
                lane_registry=lane_registry,
                agent_registry=MockAgentRegistry(),
                strategy=DispatchStrategy.CAPABILITY_BASED,
            )

            task = Task(
                task_id="task-coding",
                name="Write code",
                description="Implement feature X",
                task_type="coding",
            )

            decision = asyncio.run(router.route_task(task))
            assert decision.agent_id == "coder"
            assert decision.strategy_used == DispatchStrategy.CAPABILITY_BASED
        finally:
            import os

            os.unlink(tmp_path)


# ============================================================================
# Planner Tests
# ============================================================================


class TestPlanner:
    """Test the task planner."""

    def test_planner_initialization(self):
        """Planner can be initialized with registries."""
        from backend.orchestration.task_registry import TaskRegistry
        from backend.orchestration.team_registry import TeamRegistry

        planner = Planner(
            task_registry=TaskRegistry(),
            team_registry=TeamRegistry(),
        )
        assert planner.llm_client is None

    def test_planner_validates_acyclic_graph(self):
        """Planner validates that task graphs are acyclic."""
        from backend.orchestration.task_registry import TaskRegistry
        from backend.orchestration.team_registry import TeamRegistry

        planner = Planner(
            task_registry=TaskRegistry(),
            team_registry=TeamRegistry(),
        )

        # Acyclic graph should be valid
        tasks = [
            Task(task_id="task-1", name="t1", description="d1"),
            Task(task_id="task-2", name="t2", description="d2", blocked_by=["task-1"]),
            Task(task_id="task-3", name="t3", description="d3", blocked_by=["task-2"]),
        ]
        assert planner.validate_task_graph(tasks) is True

        # Cyclic graph should be invalid
        cyclic_tasks = [
            Task(task_id="task-a", name="a", description="a", blocked_by=["task-b"]),
            Task(task_id="task-b", name="b", description="b", blocked_by=["task-a"]),
        ]
        assert planner.validate_task_graph(cyclic_tasks) is False


# ============================================================================
# Integration Tests
# ============================================================================


class TestPhase2Integration:
    """Test the full Phase 2 integration."""

    def test_all_models_importable(self):
        """All Phase 2 models can be imported."""
        from backend.orchestration.models import (
            HeartbeatStatus,
        )

        # Verify all enums have expected values
        assert TaskStatus.CREATED.value == "created"
        assert LaneStatus.RUNNING.value == "running"
        assert TeamStatus.RUNNING.value == "running"
        assert HeartbeatStatus.HEALTHY.value == "healthy"

    def test_registry_integration(self):
        """Registries can be instantiated and work together."""
        from backend.orchestration.lane_registry import LaneRegistry
        from backend.orchestration.task_registry import TaskRegistry
        from backend.orchestration.team_registry import TeamRegistry

        # All should instantiate without errors
        TaskRegistry()
        LaneRegistry()
        TeamRegistry()
