"""Tests for the SQLite-backed orchestration event repository."""

from __future__ import annotations

from backend.data.orch_events_repo import OrchEventRepository
from backend.data.orch_run_repo import OrchRun, OrchRunRepository
from backend.domain.orch_events import make_event


def _seed_run(run_id: str) -> None:
    OrchRunRepository().upsert(
        OrchRun(run_id=run_id, session_id="session-1", status="running", created_at=1, plan_json="{}")
    )


def test_append_and_list_after_seq_roundtrip(tmp_db_path, monkeypatch) -> None:
    monkeypatch.setenv("SAGE_DB_PATH", tmp_db_path)
    repo = OrchEventRepository()
    _seed_run("run-1")
    event = make_event(
        run_id="run-1", seq=1, event_type="run.created", producer="test",
        entity={"task_id": "task-1"}, payload={"value": 3}, command_id="cmd-1",
    )

    repo.append(event)
    rows = repo.list_after("run-1", after_seq=0)

    assert len(rows) == 1
    assert rows[0] == event
    assert repo.list_after("run-1", after_seq=1) == []


def test_append_is_idempotent_by_event_id(tmp_db_path, monkeypatch) -> None:
    monkeypatch.setenv("SAGE_DB_PATH", tmp_db_path)
    repo = OrchEventRepository()
    _seed_run("run-1")
    event = make_event(run_id="run-1", seq=1, event_type="progress", producer="test")

    repo.append(event)
    repo.append(event)

    assert len(repo.list_after("run-1")) == 1


def test_append_ignores_command_and_sequence_conflicts(tmp_db_path, monkeypatch) -> None:
    monkeypatch.setenv("SAGE_DB_PATH", tmp_db_path)
    repo = OrchEventRepository()
    _seed_run("run-1")
    first = make_event(run_id="run-1", seq=1, event_type="first", producer="test", command_id="cmd-1")
    second = make_event(run_id="run-1", seq=1, event_type="retry", producer="test", command_id="cmd-1")

    repo.append(first)
    repo.append(second)

    assert repo.list_after("run-1") == [first]


    monkeypatch.setenv("SAGE_DB_PATH", tmp_db_path)
    repo = OrchEventRepository()
    for run_id in ("run-1", "run-2"):
        _seed_run(run_id)
    for run_id, seq in (("run-1", 2), ("run-1", 1), ("run-2", 1)):
        repo.append(make_event(run_id=run_id, seq=seq, event_type="progress", producer="test"))

    assert [event.seq for event in repo.list_after("run-1")] == [1, 2]
    assert [event.seq for event in repo.list_after("run-1", after_seq=1)] == [2]
