"""Unit tests for PlaybookEventRepository (2026-11-02)."""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest

from backend.data.playbook_event_repo import (
    ALLOWED_EVENTS,
    MAX_EVENTS_PER_PROJECT,
    PlaybookEvent,
    PlaybookEventRepository,
    _row_to_event,
    record_playbook_event,
)


class FakeRow(Dict[str, Any]):
    def __getitem__(self, key):  # type: ignore[override]
        try:
            return super().__getitem__(key)
        except KeyError:
            return None


def test_allowed_events_not_empty() -> None:
    assert "bind" in ALLOWED_EVENTS
    assert "batch_move" in ALLOWED_EVENTS
    assert len(ALLOWED_EVENTS) >= 20


def test_row_to_event_parses_payload() -> None:
    row = FakeRow(
        id=7,
        project_id="proj_abc",
        event="bind",
        stage="planning",
        payload_json=json.dumps({"playbook_id": "coding_project"}),
        created_at=1_700_000_000_000,
    )
    event = _row_to_event(row)
    assert event.id == 7
    assert event.event == "bind"
    assert event.stage == "planning"
    assert event.payload == {"playbook_id": "coding_project"}
    assert event.created_at == 1_700_000_000_000


def test_row_to_event_handles_invalid_payload() -> None:
    row = FakeRow(
        id=1,
        project_id="proj_x",
        event="audit",
        stage=None,
        payload_json="not-json",
        created_at=1,
    )
    event = _row_to_event(row)
    assert event.payload == {}
    assert event.stage is None


def test_row_to_event_rejects_non_dict_payload() -> None:
    row = FakeRow(
        id=1,
        project_id="proj_x",
        event="audit",
        stage=None,
        payload_json="[1,2,3]",
        created_at=1,
    )
    event = _row_to_event(row)
    assert event.payload == {}


def test_repository_record_and_list() -> None:
    repo = PlaybookEventRepository()
    first = repo.record("proj_abc", "bind", payload={"playbook_id": "coding"})
    assert isinstance(first, int)

    second = repo.record(
        "proj_abc", "audit", stage="planning", payload={"issues_count": 3}
    )
    assert second is not None and second > first

    events = repo.list_recent("proj_abc")
    assert [e.event for e in events] == ["audit", "bind"]  # newest first
    assert events[0].payload == {"issues_count": 3}
    assert events[0].stage == "planning"


def test_repository_rejects_unknown_event() -> None:
    repo = PlaybookEventRepository()
    assert repo.record("proj_abc", "not_a_real_event") is None
    assert repo.list_recent("proj_abc") == []


def test_repository_rejects_empty_project_id() -> None:
    repo = PlaybookEventRepository()
    assert repo.record("", "bind") is None


def test_repository_bounded_retention() -> None:
    from backend.data.database import get_database

    repo = PlaybookEventRepository()
    for i in range(MAX_EVENTS_PER_PROJECT + 20):
        repo.record("proj_abc", "audit", payload={"i": i})

    # list_recent clamps at 200 (UI limit), so query the DB directly
    # to verify retention capped at MAX_EVENTS_PER_PROJECT.
    conn = get_database().get_connection()
    count = conn.execute(
        "SELECT COUNT(*) FROM playbook_events WHERE project_id = ?",
        ("proj_abc",),
    ).fetchone()[0]
    assert count == MAX_EVENTS_PER_PROJECT

    # Most recent event survived.
    newest = conn.execute(
        "SELECT payload_json FROM playbook_events "
        "WHERE project_id = ? ORDER BY id DESC LIMIT 1",
        ("proj_abc",),
    ).fetchone()[0]
    import json as _json

    assert _json.loads(newest) == {"i": MAX_EVENTS_PER_PROJECT + 20 - 1}


def test_repository_list_recent_clamps_limit() -> None:
    repo = PlaybookEventRepository()
    repo.record("proj_abc", "bind")
    # Negative limit should clamp to 1, not raise.
    events = repo.list_recent("proj_abc", limit=-5)
    assert len(events) == 1

    events = repo.list_recent("proj_abc", limit=999)
    assert len(events) == 1


def test_repository_aggregate() -> None:
    repo = PlaybookEventRepository()
    repo.record("proj_abc", "bind")
    repo.record("proj_abc", "audit")
    repo.record("proj_abc", "audit")
    repo.record("proj_xyz", "bind")

    counts = repo.aggregate(project_id="proj_abc", days=30)
    assert counts == {"bind": 1, "audit": 2}

    global_counts = repo.aggregate(days=30)
    assert global_counts == {"bind": 2, "audit": 2}


def test_module_level_helper() -> None:
    event_id = record_playbook_event(
        "proj_abc", "export_json", payload={"format": "json"}
    )
    assert isinstance(event_id, int)

    events = PlaybookEventRepository().list_recent("proj_abc")
    assert len(events) == 1
    assert events[0].event == "export_json"


def test_playbook_event_dataclass_is_frozen() -> None:
    event = PlaybookEvent(id=1, project_id="p", event="bind", stage=None)
    with pytest.raises(AttributeError):
        event.id = 2  # type: ignore[misc]
