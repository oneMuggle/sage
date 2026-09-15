"""Storage-layer tests for PR-2: ``archive_document`` / ``restore_document`` /
``snapshot_pre_edit``.

Covers:
- ``archive_document`` flips ``archived_at`` to the supplied (or current) ms
  epoch and commits; returns True iff a row matched.
- ``archive_document`` on an unknown id returns False (no row touched).
- ``archive_document`` on an already-archived row updates the timestamp
  (last-write-wins -- caller can treat it as a "touch" if it ever needs to).
- ``restore_document`` clears ``archived_at`` back to NULL; same True/False
  semantics.
- ``snapshot_pre_edit`` copies the current on-disk file to a timestamped
  sibling snapshot under ``<managed>/.snapshots/``.
- ``snapshot_pre_edit`` is best-effort: missing source / IO error -> None,
  never raises, never blocks the caller's edit.
- ``snapshot_pre_edit`` uses ``now_ms`` when supplied (deterministic for tests).

No model / DB migration testing here -- the ``archived_at`` column already
exists since M0 Task 3.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.office.models import (
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
)
from backend.office.storage import (
    archive_document,
    document_path,
    restore_document,
    save_document,
    snapshot_pre_edit,
)

pytestmark = pytest.mark.unit


# ──────────────────────────────────────────────────────────────────────
# Fixtures + helpers
# ──────────────────────────────────────────────────────────────────────


def _make_doc(
    *,
    doc_id: str = "doc-1",
    workspace_path: str = "/tmp/ws",
    doc_type: OfficeDocType = OfficeDocType.WORD,
    generated_filename: str = "out.docx",
    status: OfficeDocStatus = OfficeDocStatus.GENERATED,
) -> OfficeDocumentSummary:
    return OfficeDocumentSummary(
        id=doc_id,
        workspace_path=workspace_path,
        doc_type=doc_type,
        original_filename=None,
        generated_filename=generated_filename,
        status=status,
        created_at=1_700_000_000_000,
        updated_at=1_700_000_000_000,
        metadata=OfficeDocumentMetadata(file_size_bytes=1024),
    )


@pytest.fixture()
def db_conn() -> sqlite3.Connection:
    """In-memory SQLite connection with the office_documents table created."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE office_documents (
            id TEXT PRIMARY KEY,
            workspace_path TEXT NOT NULL,
            doc_type TEXT NOT NULL,
            original_filename TEXT,
            generated_filename TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            metadata TEXT,
            derived_from TEXT,
            archived_at INTEGER
        )
        """
    )
    conn.commit()
    return conn


# ──────────────────────────────────────────────────────────────────────
# archive_document
# ──────────────────────────────────────────────────────────────────────


def test_archive_document_sets_archived_at_to_now_ms(db_conn: sqlite3.Connection):
    save_document(db_conn, _make_doc(doc_id="d1"))
    ok = archive_document(db_conn, "d1", now_ms=1_700_000_001_234)
    assert ok is True
    row = db_conn.execute(
        "SELECT archived_at FROM office_documents WHERE id = 'd1'"
    ).fetchone()
    assert row["archived_at"] == 1_700_000_001_234


def test_archive_document_returns_false_for_unknown_id(db_conn: sqlite3.Connection):
    assert archive_document(db_conn, "ghost", now_ms=1) is False
    # No row inserted as a side effect.
    assert db_conn.execute("SELECT COUNT(*) c FROM office_documents").fetchone()["c"] == 0


def test_archive_document_overwrites_previous_timestamp(db_conn: sqlite3.Connection):
    """Re-archiving a row updates the timestamp (last-write-wins).

    The service layer treats this as idempotent success and returns the
    pre-existing timestamp; storage itself simply writes whatever now_ms
    is given. Verifies storage does not silently no-op.
    """
    save_document(db_conn, _make_doc(doc_id="d1"))
    archive_document(db_conn, "d1", now_ms=1000)
    archive_document(db_conn, "d1", now_ms=2000)
    row = db_conn.execute(
        "SELECT archived_at FROM office_documents WHERE id = 'd1'"
    ).fetchone()
    assert row["archived_at"] == 2000


def test_archive_document_default_now_ms_uses_current_time(db_conn: sqlite3.Connection):
    """When ``now_ms`` is omitted, the timestamp is ~``time.time()*1000``."""
    import time

    save_document(db_conn, _make_doc(doc_id="d1"))
    before = int(time.time() * 1000)
    ok = archive_document(db_conn, "d1")
    after = int(time.time() * 1000)
    assert ok is True
    row = db_conn.execute(
        "SELECT archived_at FROM office_documents WHERE id = 'd1'"
    ).fetchone()
    assert before <= row["archived_at"] <= after


# ──────────────────────────────────────────────────────────────────────
# restore_document
# ──────────────────────────────────────────────────────────────────────


def test_restore_document_clears_archived_at(db_conn: sqlite3.Connection):
    save_document(db_conn, _make_doc(doc_id="d1"))
    archive_document(db_conn, "d1", now_ms=1_700_000_001_234)
    ok = restore_document(db_conn, "d1")
    assert ok is True
    row = db_conn.execute(
        "SELECT archived_at FROM office_documents WHERE id = 'd1'"
    ).fetchone()
    assert row["archived_at"] is None


def test_restore_document_returns_false_for_unknown_id(db_conn: sqlite3.Connection):
    assert restore_document(db_conn, "ghost") is False


def test_restore_document_on_live_row_is_noop(db_conn: sqlite3.Connection):
    """Restoring a never-archived row returns True (it matched an id) and
    leaves ``archived_at`` NULL -- symmetric with archive's idempotency."""
    save_document(db_conn, _make_doc(doc_id="d1"))
    ok = restore_document(db_conn, "d1")
    assert ok is True
    row = db_conn.execute(
        "SELECT archived_at FROM office_documents WHERE id = 'd1'"
    ).fetchone()
    assert row["archived_at"] is None


# ──────────────────────────────────────────────────────────────────────
# snapshot_pre_edit
# ──────────────────────────────────────────────────────────────────────


def _seed_doc_with_file(tmp_path: Path) -> OfficeDocumentSummary:
    """Drop a real file at the managed path and return a matching summary."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    managed_dir = workspace / "office" / "word" / "doc-1"
    managed_dir.mkdir(parents=True)
    target = managed_dir / "out.docx"
    target.write_bytes(b"hello world")
    return _make_doc(
        doc_id="doc-1",
        workspace_path=str(workspace),
        generated_filename="out.docx",
    )


def test_snapshot_pre_edit_writes_to_deterministic_path(tmp_path: Path):
    """``now_ms`` controls the snapshot filename so tests are reproducible."""
    summary = _seed_doc_with_file(tmp_path)
    result = snapshot_pre_edit(summary, now_ms=1_700_000_777_777)
    assert result is not None
    expected = (
        tmp_path
        / "ws"
        / "office"
        / "word"
        / "doc-1"
        / ".snapshots"
        / "1700000777777-out.docx"
    )
    assert result == expected
    assert result.is_file()
    assert result.read_bytes() == b"hello world"


def test_snapshot_pre_edit_creates_snapshots_dir_on_demand(tmp_path: Path):
    """``.snapshots/`` is auto-created even if it doesn't exist yet."""
    summary = _seed_doc_with_file(tmp_path)
    snap_dir = document_path(summary).parent / ".snapshots"
    assert not snap_dir.exists()
    snapshot_pre_edit(summary, now_ms=42)
    assert snap_dir.is_dir()


def test_snapshot_pre_edit_returns_none_when_source_missing(tmp_path: Path):
    """No on-disk file -> return None (never raise, never block edit)."""
    summary = _make_doc(
        doc_id="doc-missing",
        workspace_path=str(tmp_path / "ws"),
    )
    # Intentionally do NOT write the file.
    result = snapshot_pre_edit(summary, now_ms=1)
    assert result is None


def test_snapshot_pre_edit_preserves_bytes(tmp_path: Path):
    """``copy2`` semantics: the snapshot is byte-identical to the original."""
    summary = _seed_doc_with_file(tmp_path)
    document_path(summary).write_bytes(b"some bytes " * 1000)
    expected_bytes = document_path(summary).read_bytes()
    result = snapshot_pre_edit(summary, now_ms=99)
    assert result is not None
    assert result.read_bytes() == expected_bytes


def test_snapshot_pre_edit_default_now_ms(tmp_path: Path):
    """Without ``now_ms``, the filename still starts with a numeric prefix."""
    summary = _seed_doc_with_file(tmp_path)
    result = snapshot_pre_edit(summary)
    assert result is not None
    name = result.name
    # Name pattern: "<ms_epoch>-<generated_filename>"
    prefix, _, tail = name.partition("-")
    assert prefix.isdigit()
    assert tail == "out.docx"


def test_snapshot_pre_edit_swallows_oserror(tmp_path: Path, monkeypatch):
    """OSError from ``copy2`` is logged and swallowed (None, no raise)."""
    summary = _seed_doc_with_file(tmp_path)

    def _boom(*_args, **_kwargs):
        raise OSError("disk full")

    # Patch shutil.copy2 only inside backend.office.storage (its import).
    import backend.office.storage as storage_mod

    monkeypatch.setattr(storage_mod.shutil, "copy2", _boom)
    result = snapshot_pre_edit(summary, now_ms=1)
    assert result is None
