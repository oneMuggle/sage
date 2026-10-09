"""Unit tests for remaining orchestration & project sub-repositories (R189 / L2).

Completes 19/19 (100%) unit test coverage across ``backend/data/*_repo.py``:
- ``OrchestrationContextRepository`` (``orch_context_repo.py``)
- ``OrchEventRepository`` (``orch_events_repo.py``)
- ``OrchLaneRepository`` & ``OrchLaneEventRepository`` (``orch_lane_repo.py``)
- ``OrchRunRepository`` (``orch_run_repo.py``)
- ``OrchTaskRepository`` (``orch_task_repo.py``)
- ``ProjectConstraintRepository`` (``project_constraint_repo.py``)
- ``ProjectMilestoneRepository`` (``project_milestone_repo.py``)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.data import (
    orch_context_repo,
    orch_events_repo,
    orch_lane_repo,
    orch_run_repo,
    orch_task_repo,
    project_constraint_repo,
    project_milestone_repo,
    project_repo,
)
from backend.data.database import Database
from backend.data.orch_context_repo import (
    OrchestrationContextError,
    OrchestrationContextRepository,
)
from backend.data.orch_events_repo import OrchEventRepository
from backend.data.orch_lane_repo import OrchLaneEventRepository, OrchLaneRepository
from backend.data.orch_run_repo import OrchRun, OrchRunRepository
from backend.data.orch_task_repo import OrchTaskRepository
from backend.data.project_constraint_repo import ProjectConstraintRepository
from backend.data.project_milestone_repo import ProjectMilestoneRepository
from backend.data.project_repo import ProjectRepository
from backend.domain.orch_events import RunEvent
from backend.orchestration.models import Lane, LaneHeartbeat, LaneStatus


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Database:
    """Provide an isolated SQLite database bound to get_database()."""
    db_file = tmp_path / "test_r189.db"
    db = Database(db_path=str(db_file))
    db.init_db()
    for mod in (
        orch_context_repo,
        orch_events_repo,
        orch_lane_repo,
        orch_run_repo,
        orch_task_repo,
        project_constraint_repo,
        project_milestone_repo,
        project_repo,
    ):
        monkeypatch.setattr(mod, "get_database", lambda: db)
    return db


class TestOrchRunAndTaskRepository:
    def test_orch_run_crud_and_lifecycle(self, isolated_db: Database) -> None:
        repo = OrchRunRepository()
        run = OrchRun(
            run_id="orch-run-1",
            session_id="sess-1",
            status="running",
            created_at=1000,
            plan_json='{"tasks": []}',
            original_request="Build feature X",
        )
        repo.upsert(run)

        fetched = repo.get("orch-run-1")
        assert fetched is not None
        assert fetched.session_id == "sess-1"
        assert fetched.status == "running"
        assert fetched.dispatched_at is None
        assert fetched.original_request == "Build feature X"

        # First-dispatch-wins idempotency
        repo.mark_dispatched("orch-run-1", 1500)
        repo.mark_dispatched("orch-run-1", 2500)
        after_dispatch = repo.get("orch-run-1")
        assert after_dispatch is not None
        assert after_dispatch.dispatched_at == 1500

        # List & list_by_session
        assert len(repo.list(limit=10)) == 1
        assert len(repo.list_by_session("sess-1")) == 1
        assert len(repo.list_by_session("other-sess")) == 0

        # Finalize running run -> completed
        repo.finalize("orch-run-1", "completed", "All tasks finished")
        completed = repo.get("orch-run-1")
        assert completed is not None
        assert completed.status == "completed"
        assert completed.final_summary == "All tasks finished"

        # Cancelled run is not overwritten by late finalize
        run2 = OrchRun(
            run_id="orch-run-2",
            session_id="sess-1",
            status="running",
            created_at=2000,
            plan_json="{}",
        )
        repo.upsert(run2)
        repo.update_status("orch-run-2", "cancelled")
        repo.finalize("orch-run-2", "completed", "Late summary")
        cancelled = repo.get("orch-run-2")
        assert cancelled is not None
        assert cancelled.status == "cancelled"
        assert cancelled.final_summary is None

        # Stale running recovery
        run3 = OrchRun(
            run_id="orch-run-3",
            session_id="sess-2",
            status="running",
            created_at=3000,
            plan_json="{}",
        )
        repo.upsert(run3)
        recovered = repo.fail_stale_running_runs()
        assert recovered == 1
        failed = repo.get("orch-run-3")
        assert failed is not None
        assert failed.status == "failed"
        assert failed.final_summary is not None

    def test_orch_task_upsert_and_steer_revision(self, isolated_db: Database) -> None:
        OrchRunRepository().upsert(
            OrchRun(
                run_id="orch-run-1",
                session_id="sess-1",
                status="running",
                created_at=1000,
                plan_json="{}",
            )
        )
        repo = OrchTaskRepository()
        repo.upsert_state(
            task_id="t-1",
            run_id="orch-run-1",
            agent_id="coder",
            goal="Implement repo tests",
            status="queued",
            blocked_by=["t-0"],
            depth=1,
            parent_task_id="t-root",
        )
        t = repo.get("t-1")
        assert t is not None
        assert t.status == "queued"
        assert t.blocked_by == ["t-0"]
        assert t.revision == 0
        assert t.depth == 1
        assert t.parent_task_id == "t-root"

        # Bump revision for steer and verify upsert_state does not reset revision
        assert repo.bump_revision_for_steer("t-1") is True
        assert repo.bump_revision_for_steer("t-1") is True
        assert repo.bump_revision_for_steer("non-existent") is False

        repo.upsert_state(
            task_id="t-1",
            run_id="orch-run-1",
            agent_id="coder",
            goal="Implement repo tests",
            status="done",
            used_tokens=420,
            duration_ms=1200,
            output_preview="Done",
        )
        updated = repo.get("t-1")
        assert updated is not None
        assert updated.status == "done"
        assert updated.revision == 2
        assert updated.used_tokens == 420
        assert updated.duration_ms == 1200

        tasks = repo.list_by_run("orch-run-1")
        assert len(tasks) == 1
        assert tasks[0].task_id == "t-1"


class TestOrchContextAndEventRepository:
    def test_orch_context_lifecycle_and_validation(self, isolated_db: Database) -> None:
        OrchRunRepository().upsert(
            OrchRun(
                run_id="r1",
                session_id="sess-ctx",
                status="running",
                created_at=1000,
                plan_json="{}",
            )
        )
        OrchTaskRepository().upsert_state(
            task_id="t1",
            run_id="r1",
            agent_id="coder",
            goal="Steer target",
            status="running",
        )
        repo = OrchestrationContextRepository()

        # Validation errors
        with pytest.raises(OrchestrationContextError, match="invalid source"):
            repo.create(
                run_id="r1",
                task_id="t1",
                source="hacker",
                message_type="constraint",
                content_redacted="text",
            )
        with pytest.raises(OrchestrationContextError, match="invalid message_type"):
            repo.create(
                run_id="r1",
                task_id="t1",
                source="user",
                message_type="unknown",
                content_redacted="text",
            )
        with pytest.raises(OrchestrationContextError, match="invalid apply_mode"):
            repo.create(
                run_id="r1",
                task_id="t1",
                source="user",
                message_type="constraint",
                content_redacted="text",
                apply_mode="immediate",
            )
        with pytest.raises(OrchestrationContextError, match="empty"):
            repo.create(
                run_id="r1",
                task_id="t1",
                source="user",
                message_type="constraint",
                content_redacted="   ",
            )
        with pytest.raises(OrchestrationContextError, match="byte limit"):
            repo.create(
                run_id="r1",
                task_id="t1",
                source="user",
                message_type="constraint",
                content_redacted="x" * 9000,
            )

        msg1 = repo.create(
            run_id="r1",
            task_id="t1",
            source="user",
            message_type="constraint",
            content_redacted="Keep files under 800 lines",
            apply_mode="next_boundary",
            expected_task_revision=1,
            created_by="alice",
        )
        msg2 = repo.create(
            run_id="r1",
            task_id="t1",
            source="parent_agent",
            message_type="additional_context",
            content_redacted="Check win7 compat",
            apply_mode="new_followup",
        )

        fetched = repo.get(msg1.context_id)
        assert fetched is not None
        assert fetched.to_dict()["content_redacted"] == "Keep files under 800 lines"

        assert len(repo.list_pending("t1")) == 2
        assert len(repo.list_pending("t1", apply_mode="next_boundary")) == 1

        # Pending -> delivered -> acknowledged
        assert repo.mark_delivered(msg1.context_id, applied_step_id="step-2") is True
        assert repo.mark_delivered(msg1.context_id) is False
        assert repo.mark_acknowledged(msg1.context_id) is True

        # Reject msg2 directly from pending
        assert repo.mark_rejected(msg2.context_id) is True
        assert len(repo.list_pending("t1")) == 0
        assert len(repo.list_for_task("t1")) == 2

    def test_orch_events_append_and_cursor_queries(self, isolated_db: Database) -> None:
        run_repo = OrchRunRepository()
        run_repo.upsert(
            OrchRun(
                run_id="orch-ev-1",
                session_id="sess-ev",
                status="running",
                created_at=1000,
                plan_json="{}",
            )
        )
        ev_repo = OrchEventRepository()
        assert ev_repo.max_seq("orch-ev-1") == 0

        e1 = RunEvent(
            event_id="ev-1",
            run_id="orch-ev-1",
            seq=1,
            event_type="run.started",
            occurred_at=1001,
            producer="chat-dispatcher",
            producer_generation=1,
            entity={"task_id": "t-1"},
            payload={"goal": "test"},
            command_id="cmd-1",
        )
        e2 = RunEvent(
            event_id="ev-2",
            run_id="orch-ev-1",
            seq=2,
            event_type="task.started",
            occurred_at=1002,
            producer="chat-dispatcher",
            producer_generation=1,
            entity={"task_id": "t-1", "lane_id": "lane-1"},
            payload={"step": 1},
        )
        ev_repo.append(e1)
        ev_repo.append(e2)

        assert ev_repo.max_seq("orch-ev-1") == 2
        assert "orch-ev-1" in ev_repo.list_runs()

        got = ev_repo.get("ev-1")
        assert got is not None
        assert got.command_id == "cmd-1"
        assert got.entity == {"task_id": "t-1"}

        after_1 = ev_repo.list_after("orch-ev-1", after_seq=1)
        assert len(after_1) == 1
        assert after_1[0].event_id == "ev-2"

        with pytest.raises(ValueError, match="after_seq"):
            ev_repo.list_after("orch-ev-1", after_seq=-1)


class TestOrchLaneAndLaneEventRepository:
    def test_orch_lane_and_lane_event_crud(self, isolated_db: Database) -> None:
        lane_repo = OrchLaneRepository()
        ev_repo = OrchLaneEventRepository()

        lane = Lane(
            lane_id="lane-101",
            task_id="task-101",
            agent_id="agent-alpha",
            status=LaneStatus.CREATED,
            created_at=1000,
            worktree=".worktrees/w1",
            permission_preset="implement",
            metadata={"attempt": 1},
        )
        lane_repo.create(lane)

        fetched = lane_repo.get("lane-101")
        assert fetched is not None
        assert fetched.agent_id == "agent-alpha"
        assert fetched.metadata == {"attempt": 1}

        lane.status = LaneStatus.RUNNING
        lane.started_at = 1100
        lane.heartbeat = LaneHeartbeat(last_ping_at=1150)
        assert lane_repo.update(lane) is True

        hb2 = LaneHeartbeat(last_ping_at=1250)
        assert lane_repo.update_heartbeat("lane-101", hb2) is True
        updated = lane_repo.get("lane-101")
        assert updated is not None
        assert updated.status == LaneStatus.RUNNING
        assert updated.heartbeat is not None
        assert updated.heartbeat.last_ping_at == 1250

        assert len(lane_repo.list_by_task("task-101")) == 1
        assert len(lane_repo.list_by_status(LaneStatus.RUNNING)) == 1
        assert len(lane_repo.list_by_agent("agent-alpha")) == 1
        assert len(lane_repo.list_all()) == 1

        # Lane events
        eid = ev_repo.append(
            event_type="LaneStarted",
            lane_id="lane-101",
            task_id="task-101",
            agent_id="agent-alpha",
            metadata={"info": "ok"},
        )
        assert eid.startswith("evt-")
        by_lane = ev_repo.list_by_lane("lane-101")
        assert len(by_lane) == 1
        assert by_lane[0]["metadata"] == {"info": "ok"}
        assert len(ev_repo.list_by_task("task-101")) == 1

        assert lane_repo.delete("lane-101") is True
        assert lane_repo.get("lane-101") is None


class TestProjectConstraintAndMilestoneRepository:
    def test_project_constraint_crud_templates_and_resolve(
        self, isolated_db: Database, tmp_path: Path
    ) -> None:
        proj = ProjectRepository().register(path=str(tmp_path), project_type="coding")
        repo = ProjectConstraintRepository()

        c1 = repo.create(
            project_id=proj.id,
            category="coding_style",
            content="Use ruff",
            trigger_pattern="*.py",
            priority=8,
            now_ms=1000,
        )
        assert repo.get(c1.id) is not None
        assert c1.to_dict()["priority"] == 8

        imported = repo.import_template(proj.id, "security_basic", now_ms=1100)
        assert len(imported) == 3

        with pytest.raises(ValueError, match="Unknown constraint template"):
            repo.import_template(proj.id, "non_existent_template")

        # Resolve active for a .py file vs a .md file
        active_py = repo.resolve_active(proj.id, current_file="backend/app.py")
        assert any(c.id == c1.id for c in active_py)

        active_md = repo.resolve_active(proj.id, current_file="README.md")
        assert all(c.id != c1.id for c in active_md)
        assert len(active_md) == 3  # security_basic are all "always"

        # Disable c1 and verify enabled_only filtering
        assert repo.update(c1.id, enabled=False, content="Updated content") is True
        assert len(repo.list_by_project(proj.id, enabled_only=True)) == 3
        assert len(repo.list_by_project(proj.id, enabled_only=False)) == 4

        assert repo.delete(c1.id) is True
        assert repo.delete_by_project(proj.id) == 3

    def test_project_milestone_crud_and_status_counts(
        self, isolated_db: Database, tmp_path: Path
    ) -> None:
        proj = ProjectRepository().register(path=str(tmp_path), project_type="coding")
        repo = ProjectMilestoneRepository()

        m1 = repo.create(
            project_id=proj.id,
            title="Design Schema",
            description="Initial schema",
            stage="planning",
            due_date="2026-10-15",
            sort_order=1,
            now_ms=1000,
        )
        m2 = repo.create(
            project_id=proj.id,
            title="Implement API",
            stage="development",
            sort_order=2,
            now_ms=1100,
        )
        assert repo.get(m1.id) is not None
        assert m1.to_dict()["title"] == "Design Schema"

        # Update status -> completed sets completed_at; reverting clears completed_at
        assert repo.update(m1.id, status="completed") is True
        done_m1 = repo.get(m1.id)
        assert done_m1 is not None
        assert done_m1.completed_at is not None

        assert repo.update(m1.id, status="in_progress") is True
        reopened_m1 = repo.get(m1.id)
        assert reopened_m1 is not None
        assert reopened_m1.completed_at is None

        with pytest.raises(ValueError, match="Invalid status"):
            repo.update(m1.id, status="invalid_state")

        assert repo.mark_completed(m2.id, now_ms=2000) is True
        counts = repo.count_by_status(proj.id)
        assert counts["in_progress"] == 1
        assert counts["completed"] == 1
        assert counts["pending"] == 0

        assert len(repo.list_by_project(proj.id, status="completed")) == 1
        assert repo.delete(m1.id) is True
        assert repo.delete_by_project(proj.id) == 1
