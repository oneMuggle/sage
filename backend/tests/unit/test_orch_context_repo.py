"""Tests for backend.data.orch_context_repo.

The autouse ``setup_test_db`` fixture in conftest.py creates a per-test
temporary SQLite database, so we just instantiate ``OrchestrationContextRepository``
directly and exercise CRUD + lifecycle transitions.

``orch_context_messages`` has two FOREIGN KEY constraints (database.py DDL):

- ``run_id`` REFERENCES ``orch_runs(run_id)``
- ``task_id`` REFERENCES ``orch_tasks(task_id)``

So every test that calls ``repo.create`` must first seed parent rows. The
autouse ``_seed_parents`` fixture below inserts ``run-1`` + ``task-1`` once
per test; tests that need non-default IDs call ``_seed_run_and_task``
explicitly *instead*.
"""

from __future__ import annotations

import pytest

from backend.data.database import get_database
from backend.data.orch_context_repo import (
    ContextMessage,
    OrchestrationContextError,
    OrchestrationContextRepository,
)


@pytest.fixture()
def repo():
    return OrchestrationContextRepository()


def _seed_run_and_task(run_id: str, task_id: str) -> None:
    """Insert FK parent rows for an arbitrary (run_id, task_id) pair."""
    conn = get_database().get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO orch_runs "
        "(run_id, session_id, status, created_at, plan_json) "
        "VALUES (?, 'session-1', 'running', 1700000000000, '{}')",
        (run_id,),
    )
    conn.execute(
        "INSERT OR IGNORE INTO orch_tasks "
        "(task_id, run_id, agent_id, goal, status) "
        "VALUES (?, ?, 'agent-1', 'do the thing', 'running')",
        (task_id, run_id),
    )
    conn.commit()


@pytest.fixture(autouse=True)
def _seed_parents():
    """Seed the default (run-1, task-1) parent rows for every test."""
    _seed_run_and_task("run-1", "task-1")


# -------------------------------------------------------------------------- create


def test_create_returns_pending_row(repo) -> None:
    msg = repo.create(
        run_id="run-1",
        task_id="task-1",
        source="parent_agent",
        message_type="clarification",
        content_redacted="clarify target format",
        apply_mode="next_boundary",
        expected_task_revision=3,
        created_by="user-42",
    )

    assert isinstance(msg, ContextMessage)
    assert msg.status == "pending"
    assert msg.run_id == "run-1"
    assert msg.task_id == "task-1"
    assert msg.source == "parent_agent"
    assert msg.message_type == "clarification"
    assert msg.apply_mode == "next_boundary"
    assert msg.expected_task_revision == 3
    assert msg.created_by == "user-42"
    assert msg.context_id.startswith("ctx-")


def test_create_persists_and_round_trips_via_get(repo) -> None:
    msg = repo.create(
        run_id="run-1",
        task_id="task-1",
        source="user",
        message_type="correction",
        content_redacted="no, use v2 API",
    )

    fetched = repo.get(msg.context_id)
    assert fetched is not None
    assert fetched.content_redacted == "no, use v2 API"
    assert fetched.status == "pending"
    assert fetched.expected_task_revision is None
    assert fetched.created_by is None


def test_create_rejects_invalid_source(repo) -> None:
    with pytest.raises(OrchestrationContextError, match="invalid source"):
        repo.create(
            run_id="run-1", task_id="task-1", source="attacker",
            message_type="clarification", content_redacted="x",
        )


def test_create_rejects_invalid_message_type(repo) -> None:
    with pytest.raises(OrchestrationContextError, match="invalid message_type"):
        repo.create(
            run_id="run-1", task_id="task-1", source="user",
            message_type="do_anything", content_redacted="x",
        )


def test_create_rejects_invalid_apply_mode(repo) -> None:
    with pytest.raises(OrchestrationContextError, match="invalid apply_mode"):
        repo.create(
            run_id="run-1", task_id="task-1", source="user",
            message_type="clarification", content_redacted="x",
            apply_mode="immediately",
        )


def test_create_rejects_empty_content(repo) -> None:
    with pytest.raises(OrchestrationContextError, match="empty"):
        repo.create(
            run_id="run-1", task_id="task-1", source="user",
            message_type="clarification", content_redacted="   ",
        )


def test_create_rejects_content_over_8kb(repo) -> None:
    big = "x" * (8 * 1024 + 1)
    with pytest.raises(OrchestrationContextError, match="8192"):
        repo.create(
            run_id="run-1", task_id="task-1", source="user",
            message_type="clarification", content_redacted=big,
        )


def test_create_accepts_exactly_8kb_content(repo) -> None:
    # Multi-byte UTF-8: each 中 is 3 bytes → 2730 * 3 = 8190 ≤ 8192
    content = "中" * 2730
    msg = repo.create(
        run_id="run-1", task_id="task-1", source="user",
        message_type="reference", content_redacted=content,
    )
    assert msg.content_redacted == content


def test_create_default_apply_mode_is_next_boundary(repo) -> None:
    msg = repo.create(
        run_id="run-1", task_id="task-1", source="system",
        message_type="constraint", content_redacted="limit tool scope",
    )
    assert msg.apply_mode == "next_boundary"


# --------------------------------------------------------------------------- reads


def test_list_pending_filters_by_task_id(repo) -> None:
    # Use run-1 as parent run; create two tasks under it, then two messages.
    _seed_run_and_task("run-1", "task-A")
    _seed_run_and_task("run-1", "task-B")
    repo.create(
        run_id="run-1", task_id="task-A", source="user",
        message_type="clarification", content_redacted="a",
    )
    repo.create(
        run_id="run-1", task_id="task-B", source="user",
        message_type="clarification", content_redacted="b",
    )

    pending = repo.list_pending("task-A")
    assert len(pending) == 1
    assert pending[0].task_id == "task-A"


def test_list_pending_ordered_by_created_at_ascending(repo) -> None:
    first = repo.create(
        run_id="run-1", task_id="task-1", source="user",
        message_type="clarification", content_redacted="first",
    )
    second = repo.create(
        run_id="run-1", task_id="task-1", source="user",
        message_type="correction", content_redacted="second",
    )

    pending = repo.list_pending("task-1")
    assert [m.context_id for m in pending] == [first.context_id, second.context_id]


def test_list_pending_excludes_non_pending(repo) -> None:
    msg = repo.create(
        run_id="run-1", task_id="task-1", source="user",
        message_type="clarification", content_redacted="x",
    )
    repo.mark_delivered(msg.context_id)

    assert repo.list_pending("task-1") == []


def test_list_pending_filters_by_apply_mode(repo) -> None:
    repo.create(
        run_id="run-1", task_id="task-1", source="user",
        message_type="clarification", content_redacted="boundary",
        apply_mode="next_boundary",
    )
    repo.create(
        run_id="run-1", task_id="task-1", source="user",
        message_type="clarification", content_redacted="followup",
        apply_mode="new_followup",
    )

    boundary_only = repo.list_pending("task-1", apply_mode="next_boundary")
    followup_only = repo.list_pending("task-1", apply_mode="new_followup")
    assert len(boundary_only) == 1
    assert boundary_only[0].content_redacted == "boundary"
    assert len(followup_only) == 1
    assert followup_only[0].content_redacted == "followup"


def test_list_for_task_returns_all_statuses_newest_first(repo) -> None:
    first = repo.create(
        run_id="run-1", task_id="task-1", source="user",
        message_type="clarification", content_redacted="first",
    )
    second = repo.create(
        run_id="run-1", task_id="task-1", source="user",
        message_type="correction", content_redacted="second",
    )
    repo.mark_delivered(second.context_id)

    rows = repo.list_for_task("task-1")
    assert [m.context_id for m in rows] == [second.context_id, first.context_id]


def test_get_returns_none_for_unknown_id(repo) -> None:
    assert repo.get("ctx-does-not-exist") is None


# ----------------------------------------------------------------------- lifecycle


def test_mark_delivered_transitions_pending_only(repo) -> None:
    msg = repo.create(
        run_id="run-1", task_id="task-1", source="user",
        message_type="clarification", content_redacted="x",
    )

    assert repo.mark_delivered(msg.context_id, applied_step_id="step-7") is True
    # Second call no-ops (no longer pending)
    assert repo.mark_delivered(msg.context_id) is False

    fetched = repo.get(msg.context_id)
    assert fetched is not None
    assert fetched.status == "delivered"
    assert fetched.applied_step_id == "step-7"
    assert fetched.applied_at is not None


def test_mark_acknowledged_requires_delivered(repo) -> None:
    msg = repo.create(
        run_id="run-1", task_id="task-1", source="user",
        message_type="clarification", content_redacted="x",
    )
    # Cannot skip straight from pending to acknowledged
    assert repo.mark_acknowledged(msg.context_id) is False

    repo.mark_delivered(msg.context_id)
    assert repo.mark_acknowledged(msg.context_id) is True

    fetched = repo.get(msg.context_id)
    assert fetched.status == "acknowledged"


def test_mark_rejected_from_pending(repo) -> None:
    msg = repo.create(
        run_id="run-1", task_id="task-1", source="user",
        message_type="clarification", content_redacted="x",
    )
    assert repo.mark_rejected(msg.context_id) is True
    fetched = repo.get(msg.context_id)
    assert fetched.status == "rejected"
    assert fetched.applied_at is not None


def test_mark_rejected_from_delivered(repo) -> None:
    msg = repo.create(
        run_id="run-1", task_id="task-1", source="user",
        message_type="clarification", content_redacted="x",
    )
    repo.mark_delivered(msg.context_id)
    assert repo.mark_rejected(msg.context_id) is True
    fetched = repo.get(msg.context_id)
    assert fetched.status == "rejected"


def test_mark_rejected_no_ops_from_terminal_states(repo) -> None:
    msg = repo.create(
        run_id="run-1", task_id="task-1", source="user",
        message_type="clarification", content_redacted="x",
    )
    repo.mark_delivered(msg.context_id)
    repo.mark_acknowledged(msg.context_id)
    # Already acknowledged → cannot reject
    assert repo.mark_rejected(msg.context_id) is False


def test_mark_rejected_unknown_id_returns_false(repo) -> None:
    assert repo.mark_rejected("ctx-nope") is False


# --------------------------------------------------------------------- to_dict shape


def test_to_dict_includes_all_fields(repo) -> None:
    msg = repo.create(
        run_id="run-1", task_id="task-1", source="parent_agent",
        message_type="reference", content_redacted="see §3.4",
        apply_mode="next_boundary", expected_task_revision=2,
        created_by="agent-007",
    )
    d = msg.to_dict()
    for key in (
        "context_id", "run_id", "task_id", "source", "message_type",
        "content_redacted", "apply_mode", "expected_task_revision",
        "created_at", "created_by", "status", "applied_at", "applied_step_id",
    ):
        assert key in d
    assert d["expected_task_revision"] == 2
    assert d["status"] == "pending"
