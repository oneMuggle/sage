"""Session-workspace binding repository.

Maps a chat session id to an active workspace directory. One active row per
session (revoked_at IS NULL); historical rows are retained as tombstones so
``generation`` can monotonically increase across rebinds and a previous
``generation`` lookup can detect a stale caller.

This module is **connection-agnostic** — functions take a sqlite3.Connection
so tests can use :class:`backend.data.database.Database(\":memory:\")` and
production uses the real ``Database.get_connection()``.

Public surface:

    SessionWorkspaceBinding(...)                  # frozen dataclass
    bind_session_workspace(conn, sid, ws, now)   # upsert + bump generation
    get_workspace_binding(conn, sid)              # active row or None
    get_active_workspace(conn, sid, exp_gen=None) # active row, gen check
    revoke_session_workspace(conn, sid, now)      # tombstone + bump generation
    get_document_in_workspace(conn, doc_id, ws)   # workspace-scoped lookup
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from backend.office.models import OfficeDocumentSummary
from backend.office.storage import (
    _row_to_summary,
    validate_workspace,
)
from backend.office.workspace_errors import (
    WorkspaceNotBoundError,
    WorkspaceSessionNotFoundError,
)

logger = logging.getLogger(__name__)


def _now_ms(now_ms: Optional[int]) -> int:
    """Default ``now_ms`` to wall-clock when caller doesn't supply one."""
    if now_ms is None:
        return int(time.time() * 1000)
    return now_ms


def _check_session_exists(conn: sqlite3.Connection, session_id: str) -> None:
    """Raise :class:`WorkspaceSessionNotFoundError` when the session row is absent.

    Centralized so ``bind_session_workspace`` and ``revoke_session_workspace``
    emit the same diagnostic shape and never silently bind a non-existent
    chat session.
    """
    row = conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        raise WorkspaceSessionNotFoundError(
            f"Session '{session_id}' is not registered in the sessions table"
        )


@dataclass(frozen=True)
class SessionWorkspaceBinding:
    """One row of the ``session_workspace_bindings`` table.

    Frozen dataclass so callers cannot accidentally mutate a returned row
    in-place — that would mask bugs where stale references sneak past the
    generation check.

    Attributes:
        session_id: Chat session id (FK to sessions.id).
        workspace_path: Canonical absolute path of the workspace.
        generation: Monotonic per-session counter; bumped on every rebind and
            every revoke. ``generation == 1`` for the initial bind.
        activated_at: ms epoch when the binding became active (NULL revoked).
        revoked_at: ms epoch when the binding was tombstoned; ``None`` while
            the row is the live binding for the session.
    """

    session_id: str
    workspace_path: str
    generation: int
    activated_at: int
    revoked_at: Optional[int]


def _row_to_binding(row: sqlite3.Row) -> SessionWorkspaceBinding:
    """Map a SELECT row to a :class:`SessionWorkspaceBinding`."""
    return SessionWorkspaceBinding(
        session_id=row["session_id"],
        workspace_path=row["workspace_path"],
        generation=row["generation"],
        activated_at=row["activated_at"],
        revoked_at=row["revoked_at"],
    )


def _fetch_active(conn: sqlite3.Connection, session_id: str) -> Optional[SessionWorkspaceBinding]:
    """Return the live (revoked_at IS NULL) binding for the session, or None."""
    row = conn.execute(
        """
        SELECT session_id, workspace_path, generation, activated_at, revoked_at
        FROM session_workspace_bindings
        WHERE session_id = ? AND revoked_at IS NULL
        """,
        (session_id,),
    ).fetchone()
    return None if row is None else _row_to_binding(row)


def bind_session_workspace(
    conn: sqlite3.Connection,
    session_id: str,
    workspace_path: str,
    now_ms: Optional[int] = None,
) -> SessionWorkspaceBinding:
    """Bind (or rebind) a chat session to a workspace directory.

    On first call for a session, a new row is inserted with generation=1
    and revoked_at=NULL. On subsequent calls the existing row is replaced:
    ``workspace_path`` is overwritten with the canonical absolute path
    returned by :func:`validate_workspace`, ``generation`` is bumped by 1,
    ``activated_at`` is updated, and ``revoked_at`` is cleared.

    The replace-and-bump semantics give concurrent callers a way to detect
    when their cached generation is stale (see :func:`get_active_workspace`)
    without requiring a session-wide lock.

    Args:
        conn: SQLite connection (must have already run ``init_db``).
        session_id: Chat session id; must exist in the ``sessions`` table.
        workspace_path: Absolute or relative workspace directory. Symlinks
            and ``..`` segments are resolved by :func:`validate_workspace`.
        now_ms: Optional override for the timestamp (testing seam).

    Raises:
        WorkspaceSessionNotFoundError: ``session_id`` is not in sessions.
        OfficePathError: ``workspace_path`` fails validation.
    """
    _check_session_exists(conn, session_id)
    canonical = validate_workspace(Path(workspace_path))
    canonical_str = str(canonical)
    activated = _now_ms(now_ms)

    # Atomic upsert. ``INSERT … ON CONFLICT DO UPDATE`` lets us avoid a
    # SELECT-then-INSERT race when two binds arrive for the same session
    # concurrently. The generation bump is conditional on the row already
    # existing so the first bind stays at 1 instead of 2.
    conn.execute(
        """
        INSERT INTO session_workspace_bindings (
            session_id, workspace_path, generation, activated_at, revoked_at
        ) VALUES (?, ?, 1, ?, NULL)
        ON CONFLICT(session_id) DO UPDATE SET
            workspace_path = excluded.workspace_path,
            generation = session_workspace_bindings.generation + 1,
            activated_at = excluded.activated_at,
            revoked_at = NULL
        """,
        (session_id, canonical_str, activated),
    )
    conn.commit()

    binding = _fetch_active(conn, session_id)
    assert binding is not None  # we just wrote it
    return binding


def get_workspace_binding(
    conn: sqlite3.Connection,
    session_id: str,
) -> Optional[SessionWorkspaceBinding]:
    """Return the live binding for a session, or ``None`` when unbound/revoked."""
    return _fetch_active(conn, session_id)


def get_active_workspace(
    conn: sqlite3.Connection,
    session_id: str,
    expected_generation: Optional[int] = None,
) -> Optional[SessionWorkspaceBinding]:
    """Return the live binding, optionally asserting the generation matches.

    When ``expected_generation`` is supplied and doesn't match the current
    live generation, return ``None`` so callers can branch on stale-cache
    vs unbound without an exception. ``None`` for revoked bindings too,
    since the live row is gone.
    """
    binding = _fetch_active(conn, session_id)
    if binding is None:
        return None
    if expected_generation is not None and binding.generation != expected_generation:
        return None
    return binding


def revoke_session_workspace(
    conn: sqlite3.Connection,
    session_id: str,
    now_ms: Optional[int] = None,
) -> SessionWorkspaceBinding:
    """Tombstone the session's live binding.

    The first call bumps ``generation`` by 1 and stamps ``revoked_at`` with
    ``now_ms``. Subsequent calls are idempotent — the existing tombstoned
    row is returned unchanged so a double-revoke never appears as a fresh
    state transition in audit logs.

    Args:
        conn: SQLite connection.
        session_id: Chat session id; must exist.
        now_ms: Optional override for the timestamp.

    Raises:
        WorkspaceSessionNotFoundError: ``session_id`` is not in sessions.
        WorkspaceNotBoundError: no live binding exists to revoke.
    """
    _check_session_exists(conn, session_id)
    revoked_at = _now_ms(now_ms)
    # Conditional UPDATE so a re-revoke is a no-op without round-tripping
    # the row. ``rowcount == 0`` distinguishes "nothing to revoke" from
    # "already revoked" — only the former raises.
    cursor = conn.execute(
        """
        UPDATE session_workspace_bindings
        SET generation = generation + 1,
            revoked_at = ?
        WHERE session_id = ? AND revoked_at IS NULL
        """,
        (revoked_at, session_id),
    )
    if cursor.rowcount == 0:
        # Distinguish "session has no binding row at all" from "session has
        # only tombstoned rows". Both should raise, but we use the same
        # exception class with different safe messages.
        existing = conn.execute(
            "SELECT 1 FROM session_workspace_bindings WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if existing is None:
            conn.commit()
            raise WorkspaceNotBoundError(
                f"Session '{session_id}' has never been bound to a workspace"
            )
        # Already revoked — fetch and return the tombstone as-is.
        row = conn.execute(
            """
            SELECT session_id, workspace_path, generation, activated_at, revoked_at
            FROM session_workspace_bindings
            WHERE session_id = ?
            ORDER BY generation DESC
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
        conn.commit()
        assert row is not None  # we just saw existing = 1
        return _row_to_binding(row)

    conn.commit()
    row = conn.execute(
        """
        SELECT session_id, workspace_path, generation, activated_at, revoked_at
        FROM session_workspace_bindings
        WHERE session_id = ? AND revoked_at = ?
        """,
        (session_id, revoked_at),
    ).fetchone()
    assert row is not None  # we just wrote it
    return _row_to_binding(row)


def get_document_in_workspace(
    conn: sqlite3.Connection,
    document_id: str,
    workspace_path: str,
) -> Optional[OfficeDocumentSummary]:
    """Look up a document by id within a workspace, hiding archived rows.

    Scoping by ``(id, workspace_path, archived_at IS NULL)`` ensures a
    caller can't use the document id from one workspace to access docs
    in another. Returns ``None`` (not an exception) when the document is
    unknown, archived, or owned by a different workspace — the routes
    layer raises :class:`WorkspaceDocumentNotFoundError` when needed.
    """
    row = conn.execute(
        """
        SELECT id, workspace_path, doc_type, original_filename,
               generated_filename, status, created_at, updated_at, metadata,
               derived_from, archived_at
        FROM office_documents
        WHERE id = ? AND workspace_path = ? AND archived_at IS NULL
        """,
        (document_id, workspace_path),
    ).fetchone()
    return None if row is None else _row_to_summary(row)


def get_document_in_workspace_any_status(
    conn: sqlite3.Connection,
    document_id: str,
    workspace_path: str,
) -> Optional[OfficeDocumentSummary]:
    """Look up a document by id, including archived rows.

    Same workspace-scope guard as :func:`get_document_in_workspace` but
    without the ``archived_at IS NULL`` filter -- used by the archive /
    restore service methods (PR-2) that legitimately need to find a row
    whose ``archived_at`` is already set. Read / update / delete continue
    to use the archived-hiding variant so soft-deleted docs remain
    invisible to the default LLM surface.
    """
    row = conn.execute(
        """
        SELECT id, workspace_path, doc_type, original_filename,
               generated_filename, status, created_at, updated_at, metadata,
               derived_from, archived_at
        FROM office_documents
        WHERE id = ? AND workspace_path = ?
        """,
        (document_id, workspace_path),
    ).fetchone()
    return None if row is None else _row_to_summary(row)
