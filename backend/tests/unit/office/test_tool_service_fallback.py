"""Tests for the office workspace fallback chain.

Producer-side code (``backend/api/legacy_routes.py``) sets
``binding_generation=0`` for ordinary chat streams that never went
through ``authorize_chat_office_request``. Before the fallback helper
the LLM-side ``office_list`` / ``office_read`` were effectively
workspace-blind for those streams and always returned ``[]`` even when
the session obviously belonged to a project the user had been iterating
on moments earlier.

This file pins the fallback contract:

    1. ``binding_generation == 0`` + session with a historical binding
       (live or revoked) whose workspace still exists on disk ->
       list / read see that workspace.
    2. ``binding_generation == 0`` + session with NO binding but a
       project in the registry whose path exists on disk -> fall through
       to the most-recent project.
    3. ``binding_generation == 0`` + nothing on disk -> empty (no error,
       no path leak).
    4. ``binding_generation > 0`` (a real or stale handle) -> empty, even
       if a recent project / historical binding would otherwise qualify.
       Stale handles must never leak rows from a workspace the caller
       no longer has authorization for.
    5. ``_resolve_workspace_fallback`` filters out bindings / projects
       whose directory has been moved or unlinked since the row was
       written.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from backend.data.database import Database
from backend.office.models import (
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
)
from backend.office.session_workspace import (
    bind_session_workspace,
    revoke_session_workspace,
)
from backend.office.storage import save_document
from backend.office.tool_service import (
    OfficeToolService,
    _path_is_alive,
    _resolve_workspace_fallback,
)

pytestmark = pytest.mark.unit


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _seed_session(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (session_id, "t", 1, 1),
    )
    conn.commit()


def _insert_project(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    path: str,
    name: str,
    created_at: int,
    last_opened_at: int,
) -> None:
    """Insert a project row directly into the test DB.

    Bypasses :class:`ProjectRepository` because it owns its own
    ``get_database()`` reference and would land the row in the global
    production DB instead of the per-test ``tmp_path`` DB that
    ``OfficeToolService`` reads from.
    """
    conn.execute(
        """
        INSERT INTO projects (id, path, name, created_at, last_opened_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (project_id, path, name, created_at, last_opened_at),
    )
    conn.commit()


def _make_doc(
    *,
    doc_id: str,
    workspace_path: str,
    original_filename: str = "doc.docx",
) -> OfficeDocumentSummary:
    return OfficeDocumentSummary(
        id=doc_id,
        workspace_path=workspace_path,
        doc_type=OfficeDocType.WORD,
        original_filename=original_filename,
        generated_filename=f"{doc_id}.docx",
        status=OfficeDocStatus.GENERATED,
        created_at=1_700_000_000_000,
        updated_at=1_700_000_000_000,
        metadata=OfficeDocumentMetadata(file_size_bytes=1024),
    )


# ──────────────────────────────────────────────────────────────────────
# _path_is_alive — direct unit
# ──────────────────────────────────────────────────────────────────────


def test_path_is_alive_returns_true_for_existing_dir(tmp_path: Path):
    assert _path_is_alive(str(tmp_path)) is True


def test_path_is_alive_returns_false_for_missing(tmp_path: Path):
    assert _path_is_alive(str(tmp_path / "ghost")) is False


def test_path_is_alive_returns_false_for_file(tmp_path: Path):
    f = tmp_path / "x.txt"
    f.write_text("hi")
    assert _path_is_alive(str(f)) is False


# ──────────────────────────────────────────────────────────────────────
# list() — fallback paths (binding_generation == 0)
# ──────────────────────────────────────────────────────────────────────


def test_list_falls_back_to_sessions_last_workspace(tmp_path: Path):
    """binding_generation=0 + historical (revoked) binding -> list sees that ws."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    work = tmp_path / "ws"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-1", str(work), now_ms=1)
    save_document(
        conn, _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path)
    )
    # Revoke — no live binding, but the historical row still names the path.
    revoke_session_workspace(conn, "sess-1", now_ms=2)

    service = OfficeToolService()
    result = service.list(conn, "sess-1", binding_generation=0)
    ids = {r["id"] for r in result}
    assert ids == {"doc-a"}


def test_list_falls_back_to_sessions_live_binding_when_gen_zero(tmp_path: Path):
    """binding_generation=0 + live binding still in place -> use it directly."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    work = tmp_path / "ws"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-1", str(work), now_ms=1)
    save_document(
        conn, _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path)
    )

    service = OfficeToolService()
    result = service.list(conn, "sess-1", binding_generation=0)
    assert {r["id"] for r in result} == {"doc-a"}


def test_list_falls_back_to_most_recent_project(tmp_path: Path):
    """No session binding + project registry entry -> use most recent project."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    # Register a project whose path is on disk; doc lives under it.
    project_path = tmp_path / "proj"
    project_path.mkdir()
    project_path_resolved = str(project_path.resolve())
    _insert_project(
        conn,
        project_id="proj-1",
        path=project_path_resolved,
        name=project_path.name,
        created_at=1,
        last_opened_at=1,
    )
    save_document(
        conn,
        _make_doc(doc_id="doc-p", workspace_path=project_path_resolved, original_filename="P.docx"),
    )

    # No binding ever for this session -> session-history step yields nothing
    # and the project step takes over.
    service = OfficeToolService()
    result = service.list(conn, "sess-1", binding_generation=0)
    assert {r["id"] for r in result} == {"doc-p"}


def test_list_session_history_takes_priority_over_project(tmp_path: Path):
    """When both qualify, the session's last binding wins."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")

    session_ws = tmp_path / "session-ws"
    session_ws.mkdir()
    binding = bind_session_workspace(conn, "sess-1", str(session_ws), now_ms=1)
    revoke_session_workspace(conn, "sess-1", now_ms=2)
    save_document(
        conn, _make_doc(doc_id="from-session", workspace_path=binding.workspace_path)
    )

    project_ws = tmp_path / "project-ws"
    project_ws.mkdir()
    project_ws_resolved = str(project_ws.resolve())
    _insert_project(
        conn,
        project_id="proj-1",
        path=project_ws_resolved,
        name=project_ws.name,
        created_at=10,
        last_opened_at=10,
    )
    save_document(
        conn,
        _make_doc(
            doc_id="from-project", workspace_path=project_ws_resolved, original_filename="Q.docx"
        ),
    )

    service = OfficeToolService()
    result = service.list(conn, "sess-1", binding_generation=0)
    ids = {r["id"] for r in result}
    assert ids == {"from-session"}, "session history must beat recent project"


def test_list_returns_empty_when_no_workspace_on_disk(tmp_path: Path):
    """Fallback chain stops when every candidate's path is missing on disk."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")

    # Register a project whose path is NEVER created on disk.
    ghost = tmp_path / "ghost-proj"
    _insert_project(
        conn,
        project_id="ghost-1",
        path=str(ghost),
        name=ghost.name,
        created_at=1,
        last_opened_at=1,
    )

    service = OfficeToolService()
    result = service.list(conn, "sess-1", binding_generation=0)
    assert result == []


def test_list_skips_workspace_dir_moved_after_register(tmp_path: Path):
    """A workspace that vanished between register and tool call must not appear."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")

    ephemeral = tmp_path / "ephemeral"
    ephemeral.mkdir()
    bind_session_workspace(conn, "sess-1", str(ephemeral), now_ms=1)
    revoke_session_workspace(conn, "sess-1", now_ms=2)
    # Directory is gone now (was a real dir, now unlinked).
    ephemeral.rmdir()

    service = OfficeToolService()
    result = service.list(conn, "sess-1", binding_generation=0)
    assert result == []


def test_list_stale_generation_does_not_trigger_fallback(tmp_path: Path):
    """binding_generation > 0 with a stale handle -> [] (must NOT fall back)."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")

    # A live project with docs — would qualify for the fallback chain.
    project_ws = tmp_path / "ws"
    project_ws.mkdir()
    project_ws_resolved = str(project_ws.resolve())
    _insert_project(
        conn,
        project_id="proj-1",
        path=project_ws_resolved,
        name=project_ws.name,
        created_at=1,
        last_opened_at=1,
    )
    save_document(
        conn,
        _make_doc(doc_id="doc", workspace_path=project_ws_resolved, original_filename="X.docx"),
    )

    # Bumping to generation=5 simulates a stale handle — must NOT see the doc.
    service = OfficeToolService()
    result = service.list(conn, "sess-1", binding_generation=5)
    assert result == []


def test_list_result_does_not_leak_workspace_path(tmp_path: Path):
    """Fallback path must still strip workspace_path from the tool payload."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    work = tmp_path / "ws"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-1", str(work), now_ms=1)
    save_document(
        conn, _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path)
    )

    service = OfficeToolService()
    result = service.list(conn, "sess-1", binding_generation=0)
    assert len(result) == 1
    full_text = json.dumps(result[0], ensure_ascii=False, default=str)
    assert str(work.resolve()) not in full_text


def test_list_filters_apply_in_fallback_path(tmp_path: Path):
    """query / doc_type filters still work via the fallback path."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    work = tmp_path / "ws"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-1", str(work), now_ms=1)
    save_document(
        conn,
        _make_doc(
            doc_id="meeting",
            workspace_path=binding.workspace_path,
            original_filename="MeetingNotes.docx",
        ),
    )
    save_document(
        conn,
        _make_doc(
            doc_id="report",
            workspace_path=binding.workspace_path,
            original_filename="Report.docx",
        ),
    )

    service = OfficeToolService()
    result = service.list(
        conn, "sess-1", binding_generation=0, query="meeting"
    )
    ids = {r["id"] for r in result}
    assert ids == {"meeting"}


# ──────────────────────────────────────────────────────────────────────
# read() — fallback paths (binding_generation == 0)
# ──────────────────────────────────────────────────────────────────────


def test_read_falls_back_to_sessions_last_workspace(tmp_path: Path):
    """read() honors the same fallback as list()."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    work = tmp_path / "ws"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-1", str(work), now_ms=1)
    save_document(
        conn, _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path)
    )
    revoke_session_workspace(conn, "sess-1", now_ms=2)

    service = OfficeToolService()
    result = service.read(conn, "sess-1", binding_generation=0, doc_id="doc-a")
    assert result["success"] is True
    assert "summary" in result["content"]
    assert result["content"]["summary"]["id"] == "doc-a"


def test_read_stale_generation_does_not_trigger_fallback(tmp_path: Path):
    """A non-zero stale generation never widens the lookup."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")

    project_ws = tmp_path / "ws"
    project_ws.mkdir()
    project_ws_resolved = str(project_ws.resolve())
    _insert_project(
        conn,
        project_id="proj-1",
        path=project_ws_resolved,
        name=project_ws.name,
        created_at=1,
        last_opened_at=1,
    )
    save_document(
        conn,
        _make_doc(doc_id="doc-p", workspace_path=project_ws_resolved, original_filename="P.docx"),
    )

    service = OfficeToolService()
    result = service.read(conn, "sess-1", binding_generation=7, doc_id="doc-p")
    assert result["success"] is False
    assert result["error"]["code"] == "document_not_found"


# ──────────────────────────────────────────────────────────────────────
# _resolve_workspace_fallback — direct unit coverage
# ──────────────────────────────────────────────────────────────────────


def test_resolve_fallback_returns_none_for_brand_new_session(tmp_path: Path):
    """Empty DB -> fallback returns None (no candidates at all)."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()

    assert _resolve_workspace_fallback(conn, "sess-new") is None


def test_resolve_fallback_skips_workspace_removed_from_disk(tmp_path: Path):
    """A binding pointing to a moved directory does NOT count as a candidate."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")

    gone = tmp_path / "gone"
    gone.mkdir()
    bind_session_workspace(conn, "sess-1", str(gone), now_ms=1)
    revoke_session_workspace(conn, "sess-1", now_ms=2)
    gone.rmdir()

    assert _resolve_workspace_fallback(conn, "sess-1") is None


def test_resolve_fallback_skips_project_removed_from_disk(tmp_path: Path):
    """A project whose path vanished must not be returned either."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()

    ghost = tmp_path / "ghost-project"
    ghost.mkdir()
    _insert_project(
        conn,
        project_id="ghost-1",
        path=str(ghost.resolve()),
        name=ghost.name,
        created_at=1,
        last_opened_at=1,
    )
    ghost.rmdir()

    assert _resolve_workspace_fallback(conn, "sess-anything") is None
