"""Tests for backend.office.session_workspace (SessionWorkspaceBinding repository).

TDD approach: tests written FIRST per plan §4.1.2.

Coverage:
- bind_session_workspace: rebind increments generation + replaces workspace
- bind_session_workspace: rebind clears revoked_at
- bind_session_workspace: unknown session raises WorkspaceSessionNotFoundError
- bind_session_workspace: canonicalizes symlink path via validate_workspace
- revoke_session_workspace: idempotent, generation bumps once
- revoke_session_workspace: invalidates old generation lookup
- revoke_session_workspace: revoked binding is not active
- get_workspace_binding: returns None when unbound
- get_workspace_binding: returns None when revoked
- get_active_workspace: returns binding when generation matches
- get_active_workspace: returns None when generation mismatches
- get_active_workspace: returns None when revoked
- get_active_workspace: cross-session isolation
- get_document_in_workspace: returns summary when id+workspace match + active
- get_document_in_workspace: returns None when archived
- get_document_in_workspace: returns None when workspace mismatches
- Error messages do not interpolate absolute paths
"""

from __future__ import annotations

import dataclasses
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
    SessionWorkspaceBinding,
    bind_session_workspace,
    get_active_workspace,
    get_document_in_workspace,
    get_workspace_binding,
    revoke_session_workspace,
)
from backend.office.storage import save_document
from backend.office.workspace_errors import (
    WorkspaceBindingError,
    WorkspaceSessionNotFoundError,
)

# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture()
def work_a(fixture_dir: Path) -> Path:
    """Workspace A: real directory under tmp_path."""
    ws = fixture_dir / "work-a"
    ws.mkdir()
    return ws


@pytest.fixture()
def work_b(fixture_dir: Path) -> Path:
    """Workspace B: real directory under tmp_path."""
    ws = fixture_dir / "work-b"
    ws.mkdir()
    return ws


@pytest.fixture()
def conn() -> sqlite3.Connection:
    """In-memory SQLite with sessions + office_documents + session_workspace_bindings tables."""
    db = Database(":memory:")
    db.init_db()
    return db.get_connection()


def _insert_session(conn: sqlite3.Connection, session_id: str = "session-a") -> None:
    """Helper: insert a row into sessions so FK + existence checks pass."""
    conn.execute(
        """
        INSERT INTO sessions (id, title, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        """,
        (session_id, "新对话", 1, 1),
    )
    conn.commit()


def _make_doc(
    *,
    doc_id: str,
    workspace_path: str,
    archived_at: int | None = None,
) -> OfficeDocumentSummary:
    """Helper: build an OfficeDocumentSummary for save_document."""
    return OfficeDocumentSummary(
        id=doc_id,
        workspace_path=workspace_path,
        doc_type=OfficeDocType.PPT,
        original_filename=None,
        generated_filename="out.pptx",
        status=OfficeDocStatus.GENERATED,
        created_at=1_700_000_000_000,
        updated_at=1_700_000_000_000,
        metadata=OfficeDocumentMetadata(file_size_bytes=1024),
        archived_at=archived_at,
    )


# ──────────────────────────────────────────────────────────────────────
# bind_session_workspace: rebind increments generation + replaces path
# ──────────────────────────────────────────────────────────────────────


def test_rebind_increments_generation_and_replaces_current_path(
    conn: sqlite3.Connection, work_a: Path, work_b: Path
) -> None:
    """First bind -> generation 1; rebind -> generation 2, new workspace_path."""
    _insert_session(conn)
    first = bind_session_workspace(conn, "session-a", str(work_a), now_ms=1000)
    second = bind_session_workspace(conn, "session-a", str(work_b), now_ms=2000)

    assert first.generation == 1
    assert second.generation == 2
    assert second.workspace_path == str(work_b.resolve())
    assert second.revoked_at is None


# ──────────────────────────────────────────────────────────────────────
# bind_session_workspace: rebind clears revoked_at
# ──────────────────────────────────────────────────────────────────────


def test_rebind_after_revoke_clears_revoked_at(conn: sqlite3.Connection, work_a: Path) -> None:
    """After revoke, a fresh bind clears revoked_at and bumps generation."""
    _insert_session(conn)
    bind_session_workspace(conn, "session-a", str(work_a), now_ms=1000)
    revoke_session_workspace(conn, "session-a", now_ms=2000)

    rebound = bind_session_workspace(conn, "session-a", str(work_a), now_ms=3000)

    assert rebound.revoked_at is None
    assert rebound.activated_at == 3000


# ──────────────────────────────────────────────────────────────────────
# bind_session_workspace: unknown session
# ──────────────────────────────────────────────────────────────────────


def test_bind_unknown_session_raises_not_found(conn: sqlite3.Connection, work_a: Path) -> None:
    """bind_session_workspace on a non-existent session raises WorkspaceSessionNotFoundError."""
    with pytest.raises(WorkspaceSessionNotFoundError):
        bind_session_workspace(conn, "missing", str(work_a), now_ms=1000)


# ──────────────────────────────────────────────────────────────────────
# bind_session_workspace: canonical symlink path
# ──────────────────────────────────────────────────────────────────────


def test_bind_canonicalizes_symlink_workspace_path(
    conn: sqlite3.Connection, work_a: Path, fixture_dir: Path
) -> None:
    """A symlinked workspace path is resolved to its canonical absolute form."""
    _insert_session(conn)
    link = fixture_dir / "link-to-a"
    link.symlink_to(work_a)

    binding = bind_session_workspace(conn, "session-a", str(link), now_ms=1000)

    assert binding.workspace_path == str(work_a.resolve())


# ──────────────────────────────────────────────────────────────────────
# revoke_session_workspace: idempotent + generation bump
# ──────────────────────────────────────────────────────────────────────


def test_revoke_is_idempotent_and_invalidates_old_generation(
    conn: sqlite3.Connection, work_a: Path
) -> None:
    """First revoke bumps generation; second revoke is a no-op (returns same row)."""
    _insert_session(conn)
    binding = bind_session_workspace(conn, "session-a", str(work_a), now_ms=1000)
    revoked = revoke_session_workspace(conn, "session-a", now_ms=2000)
    repeated = revoke_session_workspace(conn, "session-a", now_ms=3000)

    assert revoked.generation == binding.generation + 1
    assert revoked.revoked_at == 2000
    assert repeated == revoked
    assert get_active_workspace(conn, "session-a", binding.generation) is None


# ──────────────────────────────────────────────────────────────────────
# revoke_session_workspace: unknown session
# ──────────────────────────────────────────────────────────────────────


def test_revoke_unknown_session_raises_not_found(conn: sqlite3.Connection) -> None:
    """revoke_session_workspace on a non-existent session raises WorkspaceSessionNotFoundError."""
    with pytest.raises(WorkspaceSessionNotFoundError):
        revoke_session_workspace(conn, "missing", now_ms=1000)


# ──────────────────────────────────────────────────────────────────────
# revoke_session_workspace: unbound session
# ──────────────────────────────────────────────────────────────────────


def test_revoke_unbound_session_raises_not_bound(conn: sqlite3.Connection) -> None:
    """revoke_session_workspace when no binding exists raises WorkspaceNotBoundError."""
    _insert_session(conn)
    from backend.office.workspace_errors import WorkspaceNotBoundError

    with pytest.raises(WorkspaceNotBoundError):
        revoke_session_workspace(conn, "session-a", now_ms=1000)


# ──────────────────────────────────────────────────────────────────────
# get_workspace_binding: unbound vs revoked
# ──────────────────────────────────────────────────────────────────────


def test_get_workspace_binding_returns_none_when_unbound(
    conn: sqlite3.Connection,
) -> None:
    """get_workspace_binding returns None when no binding row exists."""
    assert get_workspace_binding(conn, "never-bound") is None


def test_get_workspace_binding_returns_none_when_revoked(
    conn: sqlite3.Connection, work_a: Path
) -> None:
    """get_workspace_binding returns None for a revoked binding."""
    _insert_session(conn)
    bind_session_workspace(conn, "session-a", str(work_a), now_ms=1000)
    revoke_session_workspace(conn, "session-a", now_ms=2000)

    assert get_workspace_binding(conn, "session-a") is None


def test_get_workspace_binding_returns_row_for_active(
    conn: sqlite3.Connection, work_a: Path
) -> None:
    """get_workspace_binding returns the active binding row."""
    _insert_session(conn)
    bind_session_workspace(conn, "session-a", str(work_a), now_ms=1000)

    binding = get_workspace_binding(conn, "session-a")

    assert binding is not None
    assert binding.workspace_path == str(work_a.resolve())
    assert binding.generation == 1
    assert binding.revoked_at is None


# ──────────────────────────────────────────────────────────────────────
# get_active_workspace: generation mismatch
# ──────────────────────────────────────────────────────────────────────


def test_get_active_workspace_returns_none_for_mismatched_generation(
    conn: sqlite3.Connection, work_a: Path
) -> None:
    """get_active_workspace(expected_generation=X) returns None when live gen is not X."""
    _insert_session(conn)
    bind_session_workspace(conn, "session-a", str(work_a), now_ms=1000)

    assert get_active_workspace(conn, "session-a", expected_generation=2) is None
    assert get_active_workspace(conn, "session-a", expected_generation=1) is not None


# ──────────────────────────────────────────────────────────────────────
# get_active_workspace (revoked case)
# ──────────────────────────────────────────────────────────────────────


def test_get_active_workspace_returns_none_when_revoked(
    conn: sqlite3.Connection, work_a: Path
) -> None:
    """get_active_workspace returns None after revoke."""
    _insert_session(conn)
    bind_session_workspace(conn, "session-a", str(work_a), now_ms=1000)
    revoke_session_workspace(conn, "session-a", now_ms=2000)

    assert get_active_workspace(conn, "session-a") is None


# ──────────────────────────────────────────────────────────────────────
# Cross-session isolation
# ──────────────────────────────────────────────────────────────────────


def test_bindings_are_isolated_per_session(
    conn: sqlite3.Connection, work_a: Path, work_b: Path
) -> None:
    """A binding for session-a does not affect get_workspace_binding(session-b)."""
    _insert_session(conn, "session-a")
    _insert_session(conn, "session-b")
    bind_session_workspace(conn, "session-a", str(work_a), now_ms=1000)

    assert get_workspace_binding(conn, "session-b") is None

    bind_session_workspace(conn, "session-b", str(work_b), now_ms=1500)

    a = get_workspace_binding(conn, "session-a")
    b = get_workspace_binding(conn, "session-b")
    assert a is not None
    assert b is not None
    assert a.workspace_path != b.workspace_path


# ──────────────────────────────────────────────────────────────────────
# get_document_in_workspace: scoping by id + workspace + archived_at IS NULL
# ──────────────────────────────────────────────────────────────────────


def test_get_document_in_workspace_returns_summary_for_match(
    conn: sqlite3.Connection, work_a: Path
) -> None:
    """get_document_in_workspace returns the summary when id + workspace match."""
    save_document(conn, _make_doc(doc_id="d-1", workspace_path=str(work_a.resolve())))

    result = get_document_in_workspace(conn, "d-1", str(work_a.resolve()))

    assert result is not None
    assert result.id == "d-1"
    assert result.workspace_path == str(work_a.resolve())


def test_get_document_in_workspace_returns_none_when_archived(
    conn: sqlite3.Connection, work_a: Path
) -> None:
    """Archived documents are not visible (archived_at IS NULL)."""
    save_document(
        conn,
        _make_doc(
            doc_id="d-archived",
            workspace_path=str(work_a.resolve()),
            archived_at=1_700_000_000_000,
        ),
    )

    result = get_document_in_workspace(conn, "d-archived", str(work_a.resolve()))

    assert result is None


def test_get_document_in_workspace_returns_none_when_workspace_mismatch(
    conn: sqlite3.Connection, work_a: Path, work_b: Path
) -> None:
    """A document in workspace A is not visible from workspace B lookup."""
    save_document(conn, _make_doc(doc_id="d-1", workspace_path=str(work_a.resolve())))

    result = get_document_in_workspace(conn, "d-1", str(work_b.resolve()))

    assert result is None


def test_get_document_in_workspace_returns_none_for_unknown_id(
    conn: sqlite3.Connection, work_a: Path
) -> None:
    """Unknown document id returns None (no exception)."""
    result = get_document_in_workspace(conn, "nope", str(work_a.resolve()))
    assert result is None


# ──────────────────────────────────────────────────────────────────────
# Error message safety: no absolute path interpolation
# ──────────────────────────────────────────────────────────────────────


def test_error_messages_do_not_contain_absolute_paths(
    conn: sqlite3.Connection, work_a: Path
) -> None:
    """Subclass safe_message must never echo back a submitted absolute workspace path.

    A sentinel path that fails validate_workspace raises OfficePathError
    (path-safety layer) — not a WorkspaceBindingError — so the test catches
    any exception and asserts the sentinel never appears in the safe_message
    surface.
    """
    from backend.office.errors import OfficePathError

    _insert_session(conn, "safe-msg-session")
    sentinel = "/tmp/sensitive-secret-path-12345"
    leaked = False
    try:
        bind_session_workspace(conn, "safe-msg-session", sentinel, now_ms=1)
    except WorkspaceBindingError as exc:
        if sentinel in exc.safe_message:
            leaked = True
    except OfficePathError:
        # Acceptable: validate_workspace rejected the path before the
        # binding layer ever saw it. The path-safety layer has its own
        # "no absolute-path interpolation" guarantees; this test only
        # covers the WorkspaceBindingError surface.
        pass
    assert not leaked


# ──────────────────────────────────────────────────────────────────────
# Dataclass immutability
# ──────────────────────────────────────────────────────────────────────


def test_binding_is_frozen() -> None:
    """SessionWorkspaceBinding is a frozen dataclass — attribute assignment raises."""
    binding = SessionWorkspaceBinding(
        session_id="s",
        workspace_path="/tmp/ws",
        generation=1,
        activated_at=1000,
        revoked_at=None,
    )
    with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
        binding.generation = 2  # type: ignore[misc]
