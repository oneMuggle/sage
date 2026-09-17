"""Tests for MessageRepository segment-aware methods (context-isolation, Task 2)."""

import pytest

from backend.data import database as db_mod
from backend.data.session_repo import MessageRepository

pytestmark = pytest.mark.unit


@pytest.fixture
def db_setup(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db_path))
    monkeypatch.setattr(db_mod, "_db", None)
    db = db_mod.get_database()
    db.init_db()
    return db


def _create_session(db, session_id: str):
    """Create a minimal session row so messages can reference it via FK."""
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) "
        "VALUES (?, 't', ?, ?)",
        (session_id, 1000, 1000),
    )
    conn.commit()


def test_advance_segment_creates_separator(db_setup):
    _create_session(db_setup, "s1")
    repo = MessageRepository()
    repo.insert(session_id="s1", role="user", content="hi", created_at=1)
    repo.insert(session_id="s1", role="assistant", content="hello", created_at=2)

    new_seg = repo.advance_segment("s1")
    assert new_seg == 1

    msgs = repo.get_by_session("s1")
    assert any(m.subtype == "topic_separator" for m in msgs)
    assert msgs[-1].subtype == "topic_separator"
    assert msgs[-1].segment_id == 1


def test_get_active_segment_excludes_old(db_setup):
    _create_session(db_setup, "s1")
    repo = MessageRepository()
    repo.insert(session_id="s1", role="user", content="old", created_at=1)
    repo.advance_segment("s1")
    # Use a timestamp much larger than the separator's (which uses int(time.time() * 1000))
    repo.insert(session_id="s1", role="user", content="new", created_at=9999999999999)

    active = repo.get_active_segment("s1")
    contents = [m.content for m in active]
    assert "new" in contents
    assert "old" not in contents


def test_retreat_segment_undoes_last_separator(db_setup):
    _create_session(db_setup, "s1")
    repo = MessageRepository()
    repo.insert(session_id="s1", role="user", content="msg1", created_at=1)
    repo.advance_segment("s1")
    repo.insert(session_id="s1", role="user", content="msg2", created_at=2)

    assert repo.retreat_segment("s1") is True
    active = repo.get_active_segment("s1")
    assert any(m.content == "msg1" for m in active)
    assert any(m.content == "msg2" for m in active)


def test_retreat_segment_no_separator_returns_false(db_setup):
    repo = MessageRepository()
    assert repo.retreat_segment("s1") is False
