"""Unit tests for the file-backed iteration message store."""
from __future__ import annotations

from backend.design.messages_store import MessageStore


def test_append_and_list_round_trip(tmp_path):
    store = MessageStore(tmp_path)
    first = store.append("p1", "user", "make it calmer")
    second = store.append(
        "p1", "assistant", "applied",
        artifact_version=2, artifact_id="a2",
    )
    messages = store.list("p1")
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[0].id == first.id
    assert messages[1].artifact_version == 2
    assert messages[1].artifact_id == "a2"
    assert second.created_at


def test_list_unknown_project_is_empty(tmp_path):
    assert MessageStore(tmp_path).list("missing") == []


def test_list_corrupt_file_returns_empty(tmp_path):
    project_dir = tmp_path / "p1"
    project_dir.mkdir()
    (project_dir / "messages.json").write_text("{not json", encoding="utf-8")
    assert MessageStore(tmp_path).list("p1") == []


def test_list_skips_invalid_entries(tmp_path):
    project_dir = tmp_path / "p1"
    project_dir.mkdir()
    (project_dir / "messages.json").write_text(
        '[{"id": "ok", "role": "user", "content": "hi",'
        ' "artifact_id": null, "artifact_version": null,'
        ' "created_at": "2026-11-19T12:00:00+00:00"},'
        ' {"id": "bad", "role": "robot"}]',
        encoding="utf-8",
    )
    messages = MessageStore(tmp_path).list("p1")
    assert [m.id for m in messages] == ["ok"]


def test_projects_are_isolated(tmp_path):
    store = MessageStore(tmp_path)
    store.append("p1", "user", "one")
    store.append("p2", "user", "two")
    assert [m.content for m in store.list("p1")] == ["one"]
    assert [m.content for m in store.list("p2")] == ["two"]
