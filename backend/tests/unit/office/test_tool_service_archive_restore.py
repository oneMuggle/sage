# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Service-layer tests for PR-2: ``OfficeToolService.archive`` / ``.restore``.

Covers the six cases the task spec calls out:
1. archive success -> archived_at populated, content echoes doc_id + ts
2. restore success -> archived_at cleared, content echoes doc_id
3. archive idempotent (re-archive on already-archived keeps the original ts)
4. restore idempotent (re-restore on already-live returns success)
5. archive unknown doc -> not_found (indistinguishable from stale binding)
6. archive/restore stale binding -> not_found

Plus a follow-up: archive must NOT delete the on-disk file (soft-delete
contract). And the pre-edit snapshot integration with update() (the
``<managed>/.snapshots/<ts>-<filename>`` side-effect from Task 3).

Pattern mirrors :mod:`tests.unit.office.test_tool_service` -- in-memory
SQLite via ``Database`` + ``bind_session_workspace`` to mint a real
binding + ``save_document`` to seed rows.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

from backend.data.database import Database
from backend.office.models import (
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
)
from backend.office.session_workspace import bind_session_workspace
from backend.office.storage import save_document
from backend.office.tool_service import OfficeToolService

pytestmark = pytest.mark.unit


# ──────────────────────────────────────────────────────────────────────
# Helpers (mirror test_tool_service.py)
# ──────────────────────────────────────────────────────────────────────


def _make_doc(
    *,
    doc_id: str,
    workspace_path: str,
    archived_at: Optional[int] = None,
) -> OfficeDocumentSummary:
    return OfficeDocumentSummary(
        id=doc_id,
        workspace_path=workspace_path,
        doc_type=OfficeDocType.WORD,
        original_filename="上传.docx",
        generated_filename=f"{doc_id}.docx",
        status=OfficeDocStatus.GENERATED,
        created_at=1_700_000_000_000,
        updated_at=1_700_000_000_000,
        metadata=OfficeDocumentMetadata(file_size_bytes=1024),
        archived_at=archived_at,
    )


def _seed_session(conn, session_id: str) -> None:
    conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (session_id, "t", 1, 1),
    )
    conn.commit()


def _setup(tmp_path: Path) -> tuple:
    """Standard fixture: db + conn + binding for a single session."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-x")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-x", str(work), now_ms=1)
    return db, conn, work, binding


def _write_minimal_docx(path: Path) -> None:
    """Drop a real .docx so ``document_path(doc)`` resolves for snapshots."""
    from docx import Document

    doc = Document()
    doc.add_paragraph("hi " * 200)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)


# ──────────────────────────────────────────────────────────────────────
# archive
# ──────────────────────────────────────────────────────────────────────


def test_archive_success_persists_archived_at(tmp_path: Path):
    db, conn, _, binding = _setup(tmp_path)
    save_document(conn, _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path))

    service = OfficeToolService()
    result = service.archive(conn, "sess-x", binding.generation, "doc-a")
    assert result["success"] is True
    assert result["content"]["document_id"] == "doc-a"
    assert result["content"]["was_archived"] is True
    assert isinstance(result["content"]["archived_at"], int)

    row = conn.execute(
        "SELECT archived_at FROM office_documents WHERE id = 'doc-a'"
    ).fetchone()
    assert row["archived_at"] == result["content"]["archived_at"]


def test_archive_idempotent_on_already_archived(tmp_path: Path):
    """Re-archiving returns the original timestamp, not a fresh one."""
    db, conn, _, binding = _setup(tmp_path)
    save_document(
        conn,
        _make_doc(
            doc_id="doc-a",
            workspace_path=binding.workspace_path,
            archived_at=1_700_000_555_555,
        ),
    )

    service = OfficeToolService()
    result = service.archive(conn, "sess-x", binding.generation, "doc-a")
    assert result["success"] is True
    assert result["content"]["was_archived"] is True
    # Original timestamp preserved (not bumped).
    assert result["content"]["archived_at"] == 1_700_000_555_555


def test_archive_unknown_doc_returns_not_found(tmp_path: Path):
    db, conn, _, binding = _setup(tmp_path)
    service = OfficeToolService()
    result = service.archive(conn, "sess-x", binding.generation, "ghost")
    assert result == {
        "success": False,
        "error": {"code": "document_not_found", "message": "document not found"},
    }


def test_archive_stale_binding_returns_not_found(tmp_path: Path):
    """Mismatched generation must collapse to not_found (no path leak)."""
    db, conn, _, binding = _setup(tmp_path)
    save_document(conn, _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path))

    service = OfficeToolService()
    result = service.archive(conn, "sess-x", binding.generation + 99, "doc-a")
    assert result["error"]["code"] == "document_not_found"


def test_archive_does_not_delete_file(tmp_path: Path):
    """Soft-delete contract: on-disk file must remain after archive."""
    db, conn, work, binding = _setup(tmp_path)
    save_document(conn, _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path))
    target = work / "office" / "word" / "doc-a" / "doc-a.docx"
    _write_minimal_docx(target)
    assert target.is_file()

    service = OfficeToolService()
    result = service.archive(conn, "sess-x", binding.generation, "doc-a")
    assert result["success"] is True
    # File still on disk.
    assert target.is_file()
    # Row hidden from default list, visible with include_archived=True.
    assert service.list(conn, "sess-x", binding.generation) == []
    from backend.office.storage import list_documents

    archived_view = list_documents(conn, binding.workspace_path, include_archived=True)
    assert [d.id for d in archived_view] == ["doc-a"]


# ──────────────────────────────────────────────────────────────────────
# restore
# ──────────────────────────────────────────────────────────────────────


def test_restore_success_clears_archived_at(tmp_path: Path):
    db, conn, _, binding = _setup(tmp_path)
    save_document(
        conn,
        _make_doc(
            doc_id="doc-a",
            workspace_path=binding.workspace_path,
            archived_at=1_700_000_111_111,
        ),
    )

    service = OfficeToolService()
    result = service.restore(conn, "sess-x", binding.generation, "doc-a")
    assert result["success"] is True
    assert result["content"]["document_id"] == "doc-a"
    assert result["content"]["was_archived"] is False

    row = conn.execute(
        "SELECT archived_at FROM office_documents WHERE id = 'doc-a'"
    ).fetchone()
    assert row["archived_at"] is None
    # Default list view sees it again.
    listed = service.list(conn, "sess-x", binding.generation)
    assert [d["id"] for d in listed] == ["doc-a"]


def test_restore_idempotent_on_live_doc(tmp_path: Path):
    """Restoring a never-archived doc is a no-op success (no row mutation)."""
    db, conn, _, binding = _setup(tmp_path)
    save_document(conn, _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path))

    service = OfficeToolService()
    result = service.restore(conn, "sess-x", binding.generation, "doc-a")
    assert result["success"] is True
    assert result["content"]["was_archived"] is False

    row = conn.execute(
        "SELECT archived_at FROM office_documents WHERE id = 'doc-a'"
    ).fetchone()
    assert row["archived_at"] is None


def test_restore_unknown_doc_returns_not_found(tmp_path: Path):
    db, conn, _, binding = _setup(tmp_path)
    service = OfficeToolService()
    result = service.restore(conn, "sess-x", binding.generation, "ghost")
    assert result["error"]["code"] == "document_not_found"


def test_restore_stale_binding_returns_not_found(tmp_path: Path):
    db, conn, _, binding = _setup(tmp_path)
    save_document(
        conn,
        _make_doc(
            doc_id="doc-a",
            workspace_path=binding.workspace_path,
            archived_at=1_700_000_111_111,
        ),
    )

    service = OfficeToolService()
    result = service.restore(conn, "sess-x", binding.generation + 99, "doc-a")
    assert result["error"]["code"] == "document_not_found"


# ──────────────────────────────────────────────────────────────────────
# Cross-check: archive then restore round-trip + list filtering
# ──────────────────────────────────────────────────────────────────────


def test_archive_then_restore_round_trip(tmp_path: Path):
    db, conn, _, binding = _setup(tmp_path)
    save_document(conn, _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path))
    save_document(conn, _make_doc(doc_id="doc-b", workspace_path=binding.workspace_path))

    service = OfficeToolService()
    # Archive doc-a only.
    assert service.archive(conn, "sess-x", binding.generation, "doc-a")["success"] is True
    # list default: doc-b only.
    listed = service.list(conn, "sess-x", binding.generation)
    assert {d["id"] for d in listed} == {"doc-b"}
    # Restore doc-a.
    assert service.restore(conn, "sess-x", binding.generation, "doc-a")["success"] is True
    # Both visible again.
    listed = service.list(conn, "sess-x", binding.generation)
    assert {d["id"] for d in listed} == {"doc-a", "doc-b"}


# ──────────────────────────────────────────────────────────────────────
# Pre-edit snapshot integration with update()
# ──────────────────────────────────────────────────────────────────────


def test_update_writes_pre_edit_snapshot_to_managed_dir(tmp_path: Path):
    """``update`` snapshots the pre-edit file to ``<managed>/.snapshots/``.

    Two consecutive edits should leave two snapshots behind (each edit
    snapshots the bytes that the next op is about to overwrite). The
    snapshot dir is auto-created on demand.
    """
    db, conn, _, binding = _setup(tmp_path)
    save_document(conn, _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path))
    from backend.office.storage import document_path

    target = document_path(
        _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path)
    )
    _write_minimal_docx(target)

    service = OfficeToolService()
    # Edit #1: replace "hi" -> "bye"
    res1 = service.update(
        conn,
        "sess-x",
        binding.generation,
        "doc-a",
        [{"op": "replace_text", "find": "hi", "replace": "bye"}],
    )
    assert res1["success"] is True
    # Edit #2: replace "bye" -> "ciao"
    res2 = service.update(
        conn,
        "sess-x",
        binding.generation,
        "doc-a",
        [{"op": "replace_text", "find": "bye", "replace": "ciao"}],
    )
    assert res2["success"] is True

    snap_dir = target.parent / ".snapshots"
    assert snap_dir.is_dir(), "snapshot dir was not created by update()"
    snaps = sorted(p.name for p in snap_dir.iterdir())
    # Two updates -> two snapshots (each captures the pre-edit bytes).
    assert len(snaps) == 2
    # Filename pattern: "<ms>-<generated_filename>"
    for snap_name in snaps:
        prefix, _, tail = snap_name.partition("-")
        assert prefix.isdigit()
        assert tail == "doc-a.docx"


def test_update_snapshot_does_not_block_on_io_error(tmp_path: Path, monkeypatch):
    """A failing snapshot_pre_edit must NOT cause update() to fail.

    The user's edit is the primary intent; the snapshot is best-effort
    fallback for "undo last edit". If ``copy2`` blows up, the edit still
    lands and the user gets a successful result.
    """
    db, conn, _, binding = _setup(tmp_path)
    save_document(conn, _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path))
    from backend.office.storage import document_path

    target = document_path(
        _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path)
    )
    _write_minimal_docx(target)

    # Force snapshot_pre_edit to return None (mimics IO error).
    from backend.office import tool_service as svc_mod

    def _noop(_summary, *, now_ms=None):
        return None

    monkeypatch.setattr(svc_mod, "snapshot_pre_edit", _noop)

    service = OfficeToolService()
    result = service.update(
        conn,
        "sess-x",
        binding.generation,
        "doc-a",
        [{"op": "replace_text", "find": "hi", "replace": "bye"}],
    )
    assert result["success"] is True
    # Row updated to EDITED.
    row = conn.execute(
        "SELECT status FROM office_documents WHERE id = 'doc-a'"
    ).fetchone()
    assert row["status"] == OfficeDocStatus.EDITED.value
