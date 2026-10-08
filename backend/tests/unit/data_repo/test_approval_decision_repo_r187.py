# ruff: noqa: UP006, UP007, UP035 — Python 3.8 typing compatibility
"""R187 data repository contract tests for ApprovalDecisionRepository."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from backend.data.approval_decision_repo import (
    ApprovalDecision,
    ApprovalDecisionRepository,
)
from backend.data.database import Database

pytestmark = pytest.mark.unit


@pytest.fixture()
def isolated_repo(tmp_path: Path):
    db = Database(db_path=str(tmp_path / "approval_r187.db"))
    db.init_db()
    with patch("backend.data.approval_decision_repo.get_database", return_value=db):
        yield ApprovalDecisionRepository(), db


def test_append_computes_latency_and_persists_fields(isolated_repo) -> None:
    repo, _ = isolated_repo
    decision = repo.append(
        tool_name="bash",
        approved=True,
        answered_by="gui",
        request_id="req-100",
        session_id="sess-1",
        run_id="run-1",
        task_id="task-1",
        args_summary="ls -la",
        risk="read_only",
        created_at=1_000,
        decided_at=1_250,
    )
    assert isinstance(decision, ApprovalDecision)
    assert decision.id.startswith("apd-")
    assert decision.latency_ms == 250
    assert decision.approved is True

    listed = repo.list(limit=10)
    assert len(listed) == 1
    assert listed[0] == decision


def test_consecutive_gui_approvals_counts_only_unbroken_gui_approvals(isolated_repo) -> None:
    repo, _ = isolated_repo
    # Oldest: denied -> breaks anything earlier
    repo.append(
        tool_name="write_file",
        approved=False,
        answered_by="gui",
        session_id="sess-a",
        decided_at=1_000,
    )
    # Then 3 consecutive GUI approvals
    for ts in (2_000, 3_000, 4_000):
        repo.append(
            tool_name="write_file",
            approved=True,
            answered_by="gui",
            session_id="sess-a",
            decided_at=ts,
        )
    # Different session or tool does not interfere
    repo.append(
        tool_name="write_file",
        approved=False,
        answered_by="gui",
        session_id="sess-other",
        decided_at=5_000,
    )
    assert repo.consecutive_gui_approvals("sess-a", "write_file") == 3
    assert repo.consecutive_gui_approvals("sess-other", "write_file") == 0
    assert repo.consecutive_gui_approvals("", "write_file") == 0
    assert repo.consecutive_gui_approvals("sess-a", "") == 0


def test_consecutive_gui_approvals_stops_on_non_gui_or_same_ms_denial(isolated_repo) -> None:
    repo, _ = isolated_repo
    repo.append(
        tool_name="edit_file",
        approved=True,
        answered_by="gui",
        session_id="sess-b",
        decided_at=1_000,
    )
    # Auto approval in the middle stops consecutive manual GUI count
    repo.append(
        tool_name="edit_file",
        approved=True,
        answered_by="auto",
        session_id="sess-b",
        decided_at=2_000,
    )
    repo.append(
        tool_name="edit_file",
        approved=True,
        answered_by="gui",
        session_id="sess-b",
        decided_at=3_000,
    )
    assert repo.consecutive_gui_approvals("sess-b", "edit_file") == 1

    # Same-millisecond approval followed by denial must deterministic-tiebreak by rowid DESC
    repo.append(
        tool_name="edit_file",
        approved=True,
        answered_by="gui",
        session_id="sess-b",
        decided_at=4_000,
    )
    repo.append(
        tool_name="edit_file",
        approved=False,
        answered_by="gui",
        session_id="sess-b",
        decided_at=4_000,
    )
    assert repo.consecutive_gui_approvals("sess-b", "edit_file") == 0


def test_consecutive_gui_approvals_fails_closed_on_db_error(isolated_repo) -> None:
    repo, db = isolated_repo
    with patch.object(db, "get_connection", side_effect=RuntimeError("db down")):
        assert repo.consecutive_gui_approvals("sess-a", "write_file") == 0
