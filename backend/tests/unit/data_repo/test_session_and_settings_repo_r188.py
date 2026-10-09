# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""R188 contract unit tests for SessionRepository, SessionEventRepository & SettingsRepository."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from backend.data.database import Database
from backend.data.session_event_repo import (
    EVENT_COMPACTION_PERFORMED,
    EVENT_MESSAGE_APPENDED,
    SessionEventRepository,
)
from backend.data.session_repo import SessionRepository
from backend.data.settings_repo import SettingsRepository


@pytest.fixture
def temp_db(tmp_path: Path) -> Database:
    db = Database(db_path=tmp_path / "test_r188.db")
    db.init_db()
    return db


def test_session_repo_crud_pin_archive_and_stale_recovery(temp_db: Database) -> None:
    with patch("backend.data.session_repo.get_database", return_value=temp_db):
        repo = SessionRepository()
        s1 = repo.create(title="Alpha Session")
        s2 = repo.create(title="Beta Session", parent_id=s1.id)

        fetched = repo.get(s1.id)
        assert fetched is not None
        assert fetched.title == "Alpha Session"
        assert repo.get("missing-id") is None

        # Search by title
        hits = repo.search("Alpha")
        assert [h.id for h in hits] == [s1.id]

        # Pinning orders pinned first
        assert repo.pin(s1.id, True) is True
        listed = repo.list()
        assert listed[0].id == s1.id
        assert listed[0].is_pinned is True

        # Run status update does not mutate title, and recover_stale_run_states marks running -> failed
        assert repo.update_run_status(s2.id, "running") is True
        assert repo.get(s2.id).run_status == "running"
        recovered = repo.recover_stale_run_states()
        assert recovered == 1
        s2_after = repo.get(s2.id)
        assert s2_after.run_status == "failed"
        assert s2_after.last_error == "应用重启，运行中断"

        # Archive & purge_archived
        assert repo.archive(s2.id) is True
        assert [s.id for s in repo.list()] == [s1.id]
        purged = repo.purge_archived()
        assert purged == 1
        assert repo.get(s2.id) is None

        # Delete
        assert repo.delete(s1.id) is True
        assert repo.get(s1.id) is None


def test_session_event_repo_append_and_monotonic_sequence(temp_db: Database) -> None:
    with patch("backend.data.session_repo.get_database", return_value=temp_db), patch(
        "backend.data.session_event_repo.get_database", return_value=temp_db
    ):
        s_repo = SessionRepository()
        e_repo = SessionEventRepository()
        s = s_repo.create(title="Event Log Session")

        assert e_repo.latest_seq(s.id) == 0
        assert e_repo.count_by_session(s.id) == 0

        seq1 = e_repo.append(
            s.id,
            EVENT_MESSAGE_APPENDED,
            payload={"id": "m1", "role": "user", "content": "hello"},
        )
        seq2 = e_repo.append(
            s.id,
            EVENT_COMPACTION_PERFORMED,
            payload={"deleted_ids": ["m0"], "removed_count": 1},
            surface_op={"op": "compact"},
        )
        assert (seq1, seq2) == (1, 2)
        assert e_repo.latest_seq(s.id) == 2
        assert e_repo.count_by_session(s.id) == 2

        events = e_repo.get_by_session(s.id)
        assert [e.seq for e in events] == [1, 2]
        assert events[0].type == EVENT_MESSAGE_APPENDED
        assert events[0].payload == {"id": "m1", "role": "user", "content": "hello"}
        assert events[1].surface_op == {"op": "compact"}


def test_settings_repo_whitelist_crud_and_json_roundtrip(temp_db: Database) -> None:
    with patch("backend.data.settings_repo.get_database", return_value=temp_db):
        repo = SettingsRepository(db=temp_db)

        # Reject non-whitelisted keys
        with pytest.raises(ValueError, match="not in whitelist"):
            repo.set("not_allowed_key", "1")

        # String get/set/delete
        assert repo.get("theme_mode") is None
        repo.set("theme_mode", "light", category="appearance")
        assert repo.get("theme_mode") == "light"
        assert repo.list_by_category("appearance") == {"theme_mode": "light"}

        # JSON roundtrip
        repo.set_json("permission_rules", [{"tool": "bash", "allow": True}], category="security")
        assert repo.get_json("permission_rules") == [{"tool": "bash", "allow": True}]

        # Delete
        repo.delete("theme_mode")
        assert repo.get("theme_mode") is None
