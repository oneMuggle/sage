"""Tests for idempotent upsert in TaskRepository and LaneRepository.

Verifies that ``INSERT OR REPLACE`` semantics prevent UNIQUE constraint
errors when callers create tasks/lanes with deterministic IDs multiple
times (e.g. the review step uses ``task-review-{run_id}``).

Regression test for: "UNIQUE constraint failed: orchestration_tasks.task_id"
"""

from __future__ import annotations

import pytest

from backend.data.orchestration_repo import LaneRepository, TaskRepository
from backend.orchestration.models import (
    Lane,
    Task,
)


@pytest.fixture()
def task_repo(tmp_path, monkeypatch):
    """TaskRepository backed by a temp SQLite DB."""
    from backend.data import database as db_mod

    monkeypatch.setenv("SAGE_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(db_mod, "_db", None)
    db = db_mod.get_database()
    db.init_db()
    return TaskRepository()


@pytest.fixture()
def lane_repo(tmp_path, monkeypatch):
    """LaneRepository backed by a temp SQLite DB."""
    from backend.data import database as db_mod

    monkeypatch.setenv("SAGE_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(db_mod, "_db", None)
    db = db_mod.get_database()
    db.init_db()
    return LaneRepository()


class TestTaskRepositoryIdempotentCreate:
    def test_create_twice_same_id_does_not_raise(self, task_repo):
        """Second create() with the same task_id overwrites, not errors."""
        task = Task(
            task_id="task-review-run-abc",
            name="Review run-abc",
            description="first attempt",
        )
        task_repo.create(task)

        # Second call with same ID must not raise IntegrityError.
        task_v2 = Task(
            task_id="task-review-run-abc",
            name="Review run-abc",
            description="retry after failure",
        )
        result = task_repo.create(task_v2)

        assert result.task_id == "task-review-run-abc"
        # Verify the row was updated (not the stale first version).
        fetched = task_repo.get("task-review-run-abc")
        assert fetched is not None
        assert fetched.description == "retry after failure"


class TestLaneRepositoryIdempotentCreate:
    def test_create_twice_same_id_does_not_raise(self, task_repo, lane_repo):
        """Second create() with the same lane_id overwrites, not errors."""
        # Lanes have a FK to orchestration_tasks, so create the parent first.
        parent_task = Task(
            task_id="task-parent-1",
            name="parent",
            description="parent task",
        )
        task_repo.create(parent_task)

        lane = Lane(
            lane_id="lane-review-run-abc",
            task_id="task-parent-1",
            worktree="/tmp/ws",
            metadata={"attempt": 1},
        )
        lane_repo.create(lane)

        lane_v2 = Lane(
            lane_id="lane-review-run-abc",
            task_id="task-parent-1",
            worktree="/tmp/ws",
            metadata={"attempt": 2},
        )
        result = lane_repo.create(lane_v2)

        assert result.lane_id == "lane-review-run-abc"
        fetched = lane_repo.get("lane-review-run-abc")
        assert fetched is not None
        assert fetched.metadata.get("attempt") == 2
