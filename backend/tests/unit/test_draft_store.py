"""Unit tests for SkillDraftStore CRUD operations."""
import sqlite3

import pytest

from backend.skills.draft_store import SkillDraftStore
from backend.skills.review_service import SkillDraft

pytestmark = pytest.mark.unit

# SQL to create the skill_drafts table (mirrors backend/data/database.py schema)
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS skill_drafts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    when_to_use TEXT NOT NULL,
    content TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    source_session_id TEXT,
    source_context TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at INTEGER NOT NULL,
    reviewed_at INTEGER,
    reviewed_by_user_id TEXT
)
"""


def _make_draft(**overrides) -> SkillDraft:
    """Create a SkillDraft with sensible defaults, overridable."""
    defaults = {
        "id": "draft-001",
        "name": "test-skill",
        "description": "A test skill",
        "when_to_use": "When testing",
        "content": "# Test\n\n## Steps\n\n1. Test",
        "trigger_type": "complex_turn",
        "source_session_id": "session_1",
        "source_context": {"tool_calls": ["grep", "read"]},
        "status": "pending",
        "created_at": 1_000_000,
    }
    defaults.update(overrides)
    return SkillDraft(**defaults)


@pytest.fixture()
def store(tmp_path):
    """Return a SkillDraftStore backed by a temp database with the table created."""
    db_path = str(tmp_path / "test.db")
    with sqlite3.connect(db_path) as conn:
        conn.execute(_CREATE_TABLE_SQL)
    return SkillDraftStore(db_path)


# ── insert + get ──────────────────────────────────────────────


class TestInsertAndGet:
    def test_insert_and_get_draft(self, store):
        """Insert a draft, then retrieve it by ID."""
        draft = _make_draft()
        store.insert(draft)

        retrieved = store.get("draft-001")
        assert retrieved is not None
        assert retrieved.id == "draft-001"
        assert retrieved.name == "test-skill"
        assert retrieved.description == "A test skill"
        assert retrieved.when_to_use == "When testing"
        assert retrieved.content == "# Test\n\n## Steps\n\n1. Test"
        assert retrieved.trigger_type == "complex_turn"
        assert retrieved.source_session_id == "session_1"
        assert retrieved.source_context == {"tool_calls": ["grep", "read"]}
        assert retrieved.status == "pending"
        assert retrieved.created_at == 1_000_000

    def test_get_nonexistent_returns_none(self, store):
        """get() returns None when the draft ID does not exist."""
        assert store.get("does-not-exist") is None

    def test_insert_preserves_complex_source_context(self, store):
        """source_context with nested structures survives JSON round-trip."""
        ctx = {
            "tool_calls": [{"name": "grep", "args": {"pattern": "foo"}}],
            "turn_count": 42,
            "nested": {"deep": True},
        }
        draft = _make_draft(id="ctx-draft", source_context=ctx)
        store.insert(draft)

        retrieved = store.get("ctx-draft")
        assert retrieved is not None
        assert retrieved.source_context == ctx


# ── list ──────────────────────────────────────────────────────


class TestList:
    def test_list_by_status_default_pending(self, store):
        """list() defaults to status='pending'."""
        store.insert(_make_draft(id="d1", created_at=100))
        store.insert(_make_draft(id="d2", created_at=200))
        store.insert(_make_draft(id="d3", created_at=300, status="approved"))

        results = store.list()
        assert len(results) == 2
        ids = [d.id for d in results]
        assert "d1" in ids
        assert "d2" in ids
        assert "d3" not in ids

    def test_list_ordered_by_created_at_desc(self, store):
        """Results are ordered newest-first."""
        store.insert(_make_draft(id="old", created_at=100))
        store.insert(_make_draft(id="new", created_at=300))
        store.insert(_make_draft(id="mid", created_at=200))

        results = store.list()
        assert [d.id for d in results] == ["new", "mid", "old"]

    def test_list_empty_returns_empty(self, store):
        """list() returns [] when no drafts match."""
        assert store.list() == []

    def test_list_with_explicit_status(self, store):
        """list() respects a non-default status filter."""
        store.insert(_make_draft(id="d1", status="approved"))
        store.insert(_make_draft(id="d2", status="approved"))
        store.insert(_make_draft(id="d3", status="pending"))

        results = store.list(status="approved")
        assert len(results) == 2
        assert all(d.status == "approved" for d in results)


# ── update_status ─────────────────────────────────────────────


class TestUpdateStatus:
    def test_update_status_changes_status(self, store):
        """update_status() transitions the draft's status."""
        store.insert(_make_draft(id="u1"))
        store.update_status("u1", "approved", reviewed_by="user_42")

        draft = store.get("u1")
        assert draft is not None
        assert draft.status == "approved"

    def test_update_status_sets_reviewed_by(self, store):
        """update_status() records who reviewed the draft."""
        store.insert(_make_draft(id="u2"))
        store.update_status("u2", "rejected", reviewed_by="admin")

        # Verify directly in DB since SkillDraft dataclass doesn't have reviewed_by
        with sqlite3.connect(store.db_path) as conn:
            row = conn.execute(
                "SELECT reviewed_by_user_id FROM skill_drafts WHERE id = ?", ("u2",)
            ).fetchone()
        assert row[0] == "admin"

    def test_update_status_sets_reviewed_at(self, store):
        """update_status() sets a reviewed_at timestamp."""
        store.insert(_make_draft(id="u3"))
        store.update_status("u3", "approved")

        with sqlite3.connect(store.db_path) as conn:
            row = conn.execute(
                "SELECT reviewed_at FROM skill_drafts WHERE id = ?", ("u3",)
            ).fetchone()
        assert row[0] is not None
        assert row[0] > 0

    def test_update_status_without_reviewed_by(self, store):
        """update_status() works without specifying reviewed_by."""
        store.insert(_make_draft(id="u4"))
        store.update_status("u4", "rejected")

        with sqlite3.connect(store.db_path) as conn:
            row = conn.execute(
                "SELECT reviewed_by_user_id FROM skill_drafts WHERE id = ?", ("u4",)
            ).fetchone()
        assert row[0] is None
