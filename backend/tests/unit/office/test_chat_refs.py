"""Tests for backend.office.chat_refs (ChatOfficeRef authorization).

Coverage matrix (mirrors task-6-brief §1):
- no-binding + no-refs              -> returns None (legacy fallback)
- no-binding + refs                 -> raises WorkspaceNotBoundError (403)
- active binding + no-refs          -> AuthorizedOfficeRequest(empty scope)
- active binding + matching refs    -> AuthorizedOfficeRequest(scope=set(doc_ids))
- active binding + workspace_path mismatch
                                      -> raises WorkspacePathMismatchError (400)
- active binding + foreign-doc ref  -> raises WorkspaceDocumentNotFoundError (404)
- active binding + unknown-doc ref  -> raises WorkspaceDocumentNotFoundError (404)
- active binding + archived-doc ref -> raises WorkspaceDocumentNotFoundError (404)
- active binding + type mismatch    -> raises WorkspaceDocumentNotFoundError (404)
- active binding + filename mismatch -> raises WorkspaceDocumentNotFoundError (404)
- generation capture                -> AuthorizedOfficeRequest.binding_generation
                                       equals the live binding's generation

The route layer (``legacy_routes.chat_stream_create``) maps each exception
class to its HTTP status code; the authorization function itself only
returns immutable values or raises domain errors.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

import pytest
from pydantic import ValidationError

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
from backend.office.session_workspace import bind_session_workspace
from backend.office.storage import save_document
from backend.office.workspace_errors import (
    WorkspaceDocumentNotFoundError,
    WorkspaceNotBoundError,
    WorkspacePathMismatchError,
    WorkspaceSessionNotFoundError,
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
def work_b(fixture_dir: Path) -> Path:
    ws = fixture_dir / "work-b"
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
    doc_type: OfficeDocType = OfficeDocType.WORD,
    original_filename: Optional[str] = "doc.docx",
    archived_at: Optional[int] = None,
) -> OfficeDocumentSummary:
    return OfficeDocumentSummary(
        id=doc_id,
        workspace_path=workspace_path,
        doc_type=doc_type,
        original_filename=original_filename,
        generated_filename=f"{doc_id}.docx",
        status=OfficeDocStatus.GENERATED,
        created_at=1_700_000_000_000,
        updated_at=1_700_000_000_000,
        metadata=OfficeDocumentMetadata(file_size_bytes=1024),
        archived_at=archived_at,
    )


@pytest.fixture()
def binding_a(conn: sqlite3.Connection, work_a: Path):
    """Active binding for session-a -> work-a, generation=1."""
    _insert_session(conn, "session-a")
    return bind_session_workspace(conn, "session-a", str(work_a), now_ms=1000)


@pytest.fixture()
def doc_a(conn: sqlite3.Connection, work_a: Path) -> OfficeDocumentSummary:
    """A document that lives in workspace A (the binding's canonical path)."""
    return save_document(
        conn,
        _make_doc(
            doc_id="doc-a",
            workspace_path=str(work_a.resolve()),
            doc_type=OfficeDocType.WORD,
            original_filename="a.docx",
        ),
    )


@pytest.fixture()
def doc_b(conn: sqlite3.Connection, work_b: Path) -> OfficeDocumentSummary:
    """A document that lives in workspace B (a different workspace)."""
    return save_document(
        conn,
        _make_doc(
            doc_id="doc-b",
            workspace_path=str(work_b.resolve()),
            doc_type=OfficeDocType.WORD,
            original_filename="b.docx",
        ),
    )


# ──────────────────────────────────────────────────────────────────────
# ChatOfficeRef Pydantic model: strict validation
# ──────────────────────────────────────────────────────────────────────


def test_chatofficeref_accepts_valid_doc_type() -> None:
    """All three doc_type literals are accepted."""
    for t in ("ppt", "word", "excel"):
        ref = ChatOfficeRef(doc_id="x", doc_type=t, filename="x.pptx")  # type: ignore[arg-type]
        assert ref.doc_type == t


def test_chatofficeref_rejects_unknown_doc_type() -> None:
    """Unknown doc_type literal fails with ValidationError."""
    with pytest.raises(ValidationError):
        ChatOfficeRef(doc_id="x", doc_type="pdf", filename="x.pdf")  # type: ignore[arg-type]


def test_chatofficeref_rejects_extra_fields() -> None:
    """Unknown fields are rejected (extra='forbid')."""
    with pytest.raises(ValidationError):
        ChatOfficeRef(doc_id="x", doc_type="word", filename="x.docx", extra="nope")  # type: ignore[call-arg]


def test_chatofficeref_enforces_bounded_strings() -> None:
    """doc_id and filename have bounded length (non-empty)."""
    with pytest.raises(ValidationError):
        ChatOfficeRef(doc_id="", doc_type="word", filename="x.docx")  # empty doc_id
    with pytest.raises(ValidationError):
        ChatOfficeRef(doc_id="x", doc_type="word", filename="")  # empty filename


# ──────────────────────────────────────────────────────────────────────
# authorize_chat_office_request: no-binding cases
# ──────────────────────────────────────────────────────────────────────


def test_authorize_returns_none_when_no_binding_and_no_refs(
    conn: sqlite3.Connection,
) -> None:
    """No binding + no refs -> None (legacy fallback; nothing to authorize)."""
    _insert_session(conn, "session-a")
    result = authorize_chat_office_request(conn, "session-a", None, [])
    assert result is None


def test_authorize_raises_not_bound_when_refs_without_binding(
    conn: sqlite3.Connection,
) -> None:
    """No binding + non-empty refs -> WorkspaceNotBoundError (403)."""
    _insert_session(conn, "session-a")
    refs = [ChatOfficeRef(doc_id="doc-a", doc_type="word", filename="a.docx")]
    with pytest.raises(WorkspaceNotBoundError):
        authorize_chat_office_request(conn, "session-a", None, refs)


def test_authorize_raises_session_not_found_when_no_session(
    conn: sqlite3.Connection,
) -> None:
    """No session row + refs -> WorkspaceSessionNotFoundError (mapped to 404)."""
    refs = [ChatOfficeRef(doc_id="doc-a", doc_type="word", filename="a.docx")]
    with pytest.raises(WorkspaceSessionNotFoundError):
        authorize_chat_office_request(conn, "ghost", None, refs)


# ──────────────────────────────────────────────────────────────────────
# authorize_chat_office_request: active binding happy paths
# ──────────────────────────────────────────────────────────────────────


def test_authorize_returns_empty_scope_when_binding_active_and_no_refs(
    conn: sqlite3.Connection, binding_a
) -> None:
    """Active binding + no refs -> AuthorizedOfficeRequest with empty scope."""
    result = authorize_chat_office_request(conn, "session-a", None, [])
    assert result is not None
    assert isinstance(result, AuthorizedOfficeRequest)
    assert result.session_id == "session-a"
    assert result.office_doc_scope == frozenset()
    assert result.workspace_path == binding_a.workspace_path


def test_authorize_captures_binding_generation(
    conn: sqlite3.Connection, binding_a
) -> None:
    """AuthorizedOfficeRequest.binding_generation matches the live binding."""
    result = authorize_chat_office_request(conn, "session-a", None, [])
    assert result is not None
    assert result.binding_generation == binding_a.generation


def test_authorize_returns_scope_with_matching_ref(
    conn: sqlite3.Connection, binding_a, doc_a
) -> None:
    """Active binding + matching ref -> AuthorizedOfficeRequest with the doc id."""
    refs = [ChatOfficeRef(doc_id=doc_a.id, doc_type="word", filename="a.docx")]
    result = authorize_chat_office_request(conn, "session-a", None, refs)
    assert result is not None
    assert result.office_doc_scope == frozenset({doc_a.id})
    assert result.workspace_path == binding_a.workspace_path


def test_authorize_accepts_request_workspace_path_matching_binding(
    conn: sqlite3.Connection, binding_a, doc_a
) -> None:
    """Caller-supplied workspace_path equal to the binding's canonical path is OK."""
    refs = [ChatOfficeRef(doc_id=doc_a.id, doc_type="word", filename="a.docx")]
    result = authorize_chat_office_request(
        conn,
        "session-a",
        binding_a.workspace_path,
        refs,
    )
    assert result is not None
    assert result.office_doc_scope == frozenset({doc_a.id})


# ──────────────────────────────────────────────────────────────────────
# authorize_chat_office_request: workspace_path mismatch (400)
# ──────────────────────────────────────────────────────────────────────


def test_authorize_raises_path_mismatch_when_request_path_does_not_match(
    conn: sqlite3.Connection, binding_a, doc_a, work_b
) -> None:
    """Active binding + caller-supplied workspace_path that doesn't match -> 400."""
    refs = [ChatOfficeRef(doc_id=doc_a.id, doc_type="word", filename="a.docx")]
    with pytest.raises(WorkspacePathMismatchError):
        authorize_chat_office_request(
            conn,
            "session-a",
            str(work_b.resolve()),
            refs,
        )


# ──────────────────────────────────────────────────────────────────────
# authorize_chat_office_request: scoped document misses (404)
# ──────────────────────────────────────────────────────────────────────


def test_authorize_rejects_doc_from_other_workspace(
    conn: sqlite3.Connection, binding_a, doc_b
) -> None:
    """A doc that lives in workspace B is invisible to a binding for workspace A."""
    refs = [ChatOfficeRef(doc_id=doc_b.id, doc_type="word", filename="b.docx")]
    with pytest.raises(WorkspaceDocumentNotFoundError):
        authorize_chat_office_request(conn, "session-a", None, refs)


def test_authorize_rejects_unknown_doc(
    conn: sqlite3.Connection, binding_a
) -> None:
    """A doc id that doesn't exist in the binding's workspace is rejected."""
    refs = [ChatOfficeRef(doc_id="ghost", doc_type="word", filename="g.docx")]
    with pytest.raises(WorkspaceDocumentNotFoundError):
        authorize_chat_office_request(conn, "session-a", None, refs)


def test_authorize_rejects_archived_doc(
    conn: sqlite3.Connection, binding_a, work_a
) -> None:
    """Archived documents are not visible to authorization."""
    save_document(
        conn,
        _make_doc(
            doc_id="doc-archived",
            workspace_path=str(work_a.resolve()),
            archived_at=1_700_000_000_000,
        ),
    )
    refs = [
        ChatOfficeRef(doc_id="doc-archived", doc_type="word", filename="a.docx"),
    ]
    with pytest.raises(WorkspaceDocumentNotFoundError):
        authorize_chat_office_request(conn, "session-a", None, refs)


def test_authorize_rejects_type_mismatch(
    conn: sqlite3.Connection, binding_a, doc_a
) -> None:
    """doc_type literal in the ref must match the stored doc_type."""
    refs = [ChatOfficeRef(doc_id=doc_a.id, doc_type="ppt", filename="a.pptx")]
    with pytest.raises(WorkspaceDocumentNotFoundError):
        authorize_chat_office_request(conn, "session-a", None, refs)


def test_authorize_rejects_filename_mismatch(
    conn: sqlite3.Connection, binding_a, doc_a
) -> None:
    """filename in the ref must match the stored original_filename."""
    refs = [ChatOfficeRef(doc_id=doc_a.id, doc_type="word", filename="wrong.docx")]
    with pytest.raises(WorkspaceDocumentNotFoundError):
        authorize_chat_office_request(conn, "session-a", None, refs)


# ──────────────────────────────────────────────────────────────────────
# AuthorizedOfficeRequest immutability
# ──────────────────────────────────────────────────────────────────────


def test_authorized_office_request_is_immutable() -> None:
    """AuthorizedOfficeRequest is frozen — attribute assignment raises."""
    req = AuthorizedOfficeRequest(
        session_id="s",
        binding_generation=1,
        office_doc_scope=frozenset(),
        workspace_path="/tmp/ws",
    )
    with pytest.raises((AttributeError, Exception)):
        req.binding_generation = 2  # type: ignore[misc]


def test_authorized_office_request_holds_frozenset_scope() -> None:
    """office_doc_scope is a frozenset (immutable, hashable)."""
    req = AuthorizedOfficeRequest(
        session_id="s",
        binding_generation=1,
        office_doc_scope=frozenset({"a", "b"}),
        workspace_path="/tmp/ws",
    )
    assert isinstance(req.office_doc_scope, frozenset)
    assert req.office_doc_scope == frozenset({"a", "b"})
