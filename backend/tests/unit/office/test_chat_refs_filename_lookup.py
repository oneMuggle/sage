"""PR-3 filename-fallback tests for chat office reference authorization.

Covers the new path in ``authorize_chat_office_request`` that resolves
``@<filename>`` chat references via :func:`find_document_by_filename`
when the renderer-supplied ``doc_id`` doesn't match any row directly.

The four required cases (per PR-3 brief section "测试"):

1. ``doc_id`` matches an existing row -> 200 OK, scope contains the UUID.
2. ``doc_id`` is unknown but ``filename`` matches -> 200 OK, scope
   contains the resolved UUID (managed id, not the filename).
3. Both ``doc_id`` and ``filename`` unknown -> 404.
4. ``doc_id`` unknown but ``filename`` resolves to a doc whose
   ``doc_type`` differs from the ref's declared type -> 400
   :class:`WorkspacePathMismatchError`.

All tests use ``:memory:`` sqlite and the real ``Database.init_db()``
schema so column names and migrations match production.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

import pytest

from backend.data.database import Database
from backend.office.chat_refs import (
    AuthorizedOfficeRequest,
    ChatOfficeRef,
    authorize_chat_office_request,
)
from backend.office.models import (
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
)
from backend.office.session_workspace import (
    bind_session_workspace,
    find_document_by_filename,
)
from backend.office.storage import save_document
from backend.office.workspace_errors import (
    WorkspaceDocumentNotFoundError,
    WorkspacePathMismatchError,
)

# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture()
def work_a(fixture_dir: Path) -> Path:
    ws = fixture_dir / "work-a"
    ws.mkdir()
    return ws


@pytest.fixture()
def conn() -> sqlite3.Connection:
    db = Database(":memory:")
    db.init_db()
    return db.get_connection()


def _insert_session(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (session_id, "新对话", 1, 1),
    )
    conn.commit()


def _make_doc(
    *,
    doc_id: str,
    workspace_path: str,
    doc_type: OfficeDocType,
    original_filename: Optional[str],
    generated_filename: str,
    archived_at: Optional[int] = None,
    derived_from: Optional[str] = None,
) -> OfficeDocumentSummary:
    return OfficeDocumentSummary(
        id=doc_id,
        workspace_path=workspace_path,
        doc_type=doc_type,
        original_filename=original_filename,
        generated_filename=generated_filename,
        status=OfficeDocStatus.PARSED,
        created_at=1_700_000_000_000,
        updated_at=1_700_000_000_000,
        metadata=OfficeDocumentMetadata(file_size_bytes=2048),
        archived_at=archived_at,
        derived_from=derived_from,
    )


@pytest.fixture()
def binding_a(conn: sqlite3.Connection, work_a: Path):
    """Active binding for session-a -> work-a, generation=1."""
    _insert_session(conn, "session-a")
    return bind_session_workspace(conn, "session-a", str(work_a), now_ms=1000)


# ──────────────────────────────────────────────────────────────────────
# Case 1: doc_id matches an existing row -> 200 OK
# ──────────────────────────────────────────────────────────────────────


def test_authorize_resolves_via_doc_id_when_row_exists(
    conn: sqlite3.Connection, binding_a, work_a
) -> None:
    """doc_id hits an existing row directly -> AuthorizedOfficeRequest with the UUID."""
    doc = save_document(
        conn,
        _make_doc(
            doc_id="uuid-1234",
            workspace_path=str(work_a.resolve()),
            doc_type=OfficeDocType.WORD,
            original_filename="MeetingNotes.docx",
            generated_filename="MeetingNotes.docx",
        ),
    )
    refs = [ChatOfficeRef(doc_id=doc.id, doc_type="word", filename="MeetingNotes.docx")]
    result = authorize_chat_office_request(conn, "session-a", None, refs)
    assert result is not None
    assert isinstance(result, AuthorizedOfficeRequest)
    assert result.office_doc_scope == frozenset({doc.id})


# ──────────────────────────────────────────────────────────────────────
# Case 2: doc_id unknown but filename matches -> 200 OK, scope = UUID
# ──────────────────────────────────────────────────────────────────────


def test_authorize_falls_back_to_filename_when_doc_id_unknown(
    conn: sqlite3.Connection, binding_a, work_a
) -> None:
    """doc_id doesn't match any row but generated_filename does -> 200 OK with the UUID in scope."""
    save_document(
        conn,
        _make_doc(
            doc_id="managed-uuid-aaaa",
            workspace_path=str(work_a.resolve()),
            doc_type=OfficeDocType.WORD,
            original_filename="MeetingNotes.docx",
            generated_filename="MeetingNotes.docx",
        ),
    )
    # Frontend hands us the user-visible filename, not the managed UUID.
    refs = [ChatOfficeRef(doc_id="unknown-uuid", doc_type="word", filename="MeetingNotes.docx")]
    result = authorize_chat_office_request(conn, "session-a", None, refs)
    assert result is not None
    # The scope contains the managed UUID, not the caller's doc_id or
    # the filename — that's the contract the downstream pipeline relies
    # on for tool dispatch.
    assert result.office_doc_scope == frozenset({"managed-uuid-aaaa"})
    assert "unknown-uuid" not in result.office_doc_scope
    assert "MeetingNotes.docx" not in result.office_doc_scope


# ──────────────────────────────────────────────────────────────────────
# Case 3: both doc_id and filename unknown -> 404
# ──────────────────────────────────────────────────────────────────────


def test_authorize_raises_not_found_when_neither_doc_id_nor_filename_match(
    conn: sqlite3.Connection, binding_a, work_a
) -> None:
    """No row matches by id nor by filename -> WorkspaceDocumentNotFoundError (404)."""
    save_document(
        conn,
        _make_doc(
            doc_id="managed-uuid-bbbb",
            workspace_path=str(work_a.resolve()),
            doc_type=OfficeDocType.WORD,
            original_filename="OtherDoc.docx",
            generated_filename="OtherDoc.docx",
        ),
    )
    refs = [ChatOfficeRef(doc_id="unknown-uuid", doc_type="word", filename="NotThere.docx")]
    with pytest.raises(WorkspaceDocumentNotFoundError):
        authorize_chat_office_request(conn, "session-a", None, refs)


# ──────────────────────────────────────────────────────────────────────
# Case 4: filename resolves but doc_type mismatch -> 400
# ──────────────────────────────────────────────────────────────────────


def test_authorize_raises_type_mismatch_400_when_filename_hit_type_differs(
    conn: sqlite3.Connection, binding_a, work_a
) -> None:
    """Filename resolves but the row's doc_type differs from the ref's -> WorkspacePathMismatchError (400)."""
    save_document(
        conn,
        _make_doc(
            doc_id="managed-uuid-cccc",
            workspace_path=str(work_a.resolve()),
            doc_type=OfficeDocType.PPT,  # stored type is PPT
            original_filename="Deck.pptx",
            generated_filename="Deck.pptx",
        ),
    )
    # Caller claims it's a Word doc.
    refs = [ChatOfficeRef(doc_id="unknown-uuid", doc_type="word", filename="Deck.pptx")]
    with pytest.raises(WorkspacePathMismatchError):
        authorize_chat_office_request(conn, "session-a", None, refs)


# ──────────────────────────────────────────────────────────────────────
# Extra coverage: helper isolation + cross-workspace safety
# ──────────────────────────────────────────────────────────────────────


def test_find_document_by_filename_returns_none_for_unknown(
    conn: sqlite3.Connection, work_a
) -> None:
    """find_document_by_filename returns None for unknown filenames."""
    save_document(
        conn,
        _make_doc(
            doc_id="uuid-x",
            workspace_path=str(work_a.resolve()),
            doc_type=OfficeDocType.WORD,
            original_filename="a.docx",
            generated_filename="a.docx",
        ),
    )
    assert find_document_by_filename(conn, str(work_a.resolve()), "ghost.docx") is None


def test_find_document_by_filename_hides_archived(
    conn: sqlite3.Connection, work_a
) -> None:
    """find_document_by_filename returns None for archived rows (chat refs can't see archived docs)."""
    save_document(
        conn,
        _make_doc(
            doc_id="uuid-y",
            workspace_path=str(work_a.resolve()),
            doc_type=OfficeDocType.WORD,
            original_filename="arch.docx",
            generated_filename="arch.docx",
            archived_at=1_700_000_000_000,
        ),
    )
    assert find_document_by_filename(conn, str(work_a.resolve()), "arch.docx") is None


def test_find_document_by_filename_respects_workspace_boundary(
    conn: sqlite3.Connection, work_a, fixture_dir
) -> None:
    """A row in workspace B isn't visible to a lookup scoped to workspace A."""
    work_b = fixture_dir / "work-b"
    work_b.mkdir()
    save_document(
        conn,
        _make_doc(
            doc_id="uuid-z",
            workspace_path=str(work_b.resolve()),
            doc_type=OfficeDocType.WORD,
            original_filename="cross.docx",
            generated_filename="cross.docx",
        ),
    )
    # Scope lookup to work_a — must not find the doc that lives in work_b.
    assert find_document_by_filename(conn, str(work_a.resolve()), "cross.docx") is None
    # But scoping to work_b finds it.
    assert find_document_by_filename(conn, str(work_b.resolve()), "cross.docx") is not None
