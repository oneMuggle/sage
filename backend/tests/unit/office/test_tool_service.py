"""Unit tests for :mod:`backend.office.tool_service`.

Covers:
- Generation mismatch / revoke / rebind -> empty / error (no path leak)
- Workspace + archived filtering (docs outside binding are invisible)
- Policy limits (``max_result_items``, ``max_output_bytes``)
- Indistinguishable not-found (unknown doc vs archived vs wrong workspace)
- Section ``summary`` / ``head`` / ``all`` deterministic truncation
- No absolute workspace path in list results
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pytest

from backend.data.database import Database
from backend.domain.tool_policy import ToolPolicy
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
from backend.office.tool_service import OfficeToolService

pytestmark = pytest.mark.unit


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _make_doc(
    *,
    doc_id: str,
    workspace_path: str,
    doc_type: OfficeDocType = OfficeDocType.WORD,
    original_filename: str = "doc.docx",
    generated_filename: Optional[str] = None,
    archived_at: Optional[int] = None,
    file_size_bytes: int = 1024,
) -> OfficeDocumentSummary:
    return OfficeDocumentSummary(
        id=doc_id,
        workspace_path=workspace_path,
        doc_type=doc_type,
        original_filename=original_filename,
        generated_filename=generated_filename or f"{doc_id}.docx",
        status=OfficeDocStatus.GENERATED,
        created_at=1_700_000_000_000,
        updated_at=1_700_000_000_000,
        metadata=OfficeDocumentMetadata(file_size_bytes=file_size_bytes),
        archived_at=archived_at,
    )


def _seed_session(conn, session_id: str) -> None:
    conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (session_id, "t", 1, 1),
    )
    conn.commit()


# ──────────────────────────────────────────────────────────────────────
# Authorization: binding generation / revoke / rebind
# ──────────────────────────────────────────────────────────────────────


def test_list_returns_empty_when_generation_mismatch(tmp_path: Path):
    """A stale ``binding_generation`` must not leak document rows."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-1", str(work), now_ms=1)
    save_document(
        conn,
        _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path),
    )

    service = OfficeToolService()
    result = service.list(conn, "sess-1", binding.generation + 1)
    assert result == []


def test_list_returns_empty_after_revoke(tmp_path: Path):
    """Revoked binding -> list returns empty (no error to leak path info)."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-1", str(work), now_ms=1)
    save_document(
        conn,
        _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path),
    )
    revoke_session_workspace(conn, "sess-1", now_ms=2)

    service = OfficeToolService()
    result = service.list(conn, "sess-1", binding.generation)
    assert result == []


def test_list_after_rebind_uses_new_generation(tmp_path: Path):
    """After rebind, old generation stops working; new one sees new docs."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    work_a = tmp_path / "a"
    work_a.mkdir()
    binding1 = bind_session_workspace(conn, "sess-1", str(work_a), now_ms=1)
    save_document(
        conn,
        _make_doc(doc_id="doc-a", workspace_path=binding1.workspace_path),
    )

    work_b = tmp_path / "b"
    work_b.mkdir()
    binding2 = bind_session_workspace(conn, "sess-1", str(work_b), now_ms=2)
    save_document(
        conn,
        _make_doc(doc_id="doc-b", workspace_path=binding2.workspace_path),
    )

    service = OfficeToolService()
    # old generation -> empty
    assert service.list(conn, "sess-1", binding1.generation) == []
    # new generation -> only doc-b (scoped to binding2.workspace_path)
    result = service.list(conn, "sess-1", binding2.generation)
    ids = [r["id"] for r in result]
    assert ids == ["doc-b"]


# ──────────────────────────────────────────────────────────────────────
# Workspace + archived filtering
# ──────────────────────────────────────────────────────────────────────


def test_list_filters_archived_documents(tmp_path: Path):
    """Archived documents must be excluded from list results."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-1", str(work), now_ms=1)
    save_document(
        conn,
        _make_doc(doc_id="live", workspace_path=binding.workspace_path),
    )
    save_document(
        conn,
        _make_doc(
            doc_id="archived",
            workspace_path=binding.workspace_path,
            archived_at=9_999_999,
        ),
    )

    service = OfficeToolService()
    result = service.list(conn, "sess-1", binding.generation)
    ids = {r["id"] for r in result}
    assert "live" in ids
    assert "archived" not in ids


def test_list_does_not_expose_absolute_workspace_path(tmp_path: Path):
    """Result dicts must not contain the binding's absolute workspace path."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-1", str(work), now_ms=1)
    save_document(
        conn,
        _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path),
    )

    service = OfficeToolService()
    result = service.list(conn, "sess-1", binding.generation)
    assert len(result) == 1
    # ``workspace_path`` must not appear as a value in the result dict.
    full_text = json.dumps(result[0], ensure_ascii=False, default=str)
    assert str(work.resolve()) not in full_text


def test_list_filters_by_doc_type(tmp_path: Path):
    """``doc_type`` filter narrows to the requested type."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-1", str(work), now_ms=1)
    save_document(
        conn,
        _make_doc(
            doc_id="w1",
            workspace_path=binding.workspace_path,
            doc_type=OfficeDocType.WORD,
        ),
    )
    save_document(
        conn,
        _make_doc(
            doc_id="p1",
            workspace_path=binding.workspace_path,
            doc_type=OfficeDocType.PPT,
            generated_filename="p1.pptx",
        ),
    )

    service = OfficeToolService()
    result = service.list(conn, "sess-1", binding.generation, doc_type="word")
    ids = {r["id"] for r in result}
    assert ids == {"w1"}


def test_list_query_filters_case_insensitively(tmp_path: Path):
    """``query`` matches against original_filename case-insensitively."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-1", str(work), now_ms=1)
    save_document(
        conn,
        _make_doc(
            doc_id="d1",
            workspace_path=binding.workspace_path,
            original_filename="MeetingNotes.docx",
        ),
    )
    save_document(
        conn,
        _make_doc(
            doc_id="d2",
            workspace_path=binding.workspace_path,
            original_filename="Report.docx",
        ),
    )

    service = OfficeToolService()
    result = service.list(conn, "sess-1", binding.generation, query="meeting")
    ids = {r["id"] for r in result}
    assert ids == {"d1"}


# ──────────────────────────────────────────────────────────────────────
# Policy limits
# ──────────────────────────────────────────────────────────────────────


def test_list_respects_max_result_items(tmp_path: Path):
    """``policy.max_result_items`` caps the number of returned rows."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-1", str(work), now_ms=1)
    for i in range(10):
        save_document(
            conn,
            _make_doc(
                doc_id=f"d{i:02d}",
                workspace_path=binding.workspace_path,
                original_filename=f"file{i}.docx",
            ),
        )

    service = OfficeToolService(policy=ToolPolicy(max_result_items=3))
    result = service.list(conn, "sess-1", binding.generation)
    assert len(result) <= 3


# ──────────────────────────────────────────────────────────────────────
# read: indistinguishable not-found
# ──────────────────────────────────────────────────────────────────────


def test_read_unknown_doc_returns_safe_error(tmp_path: Path):
    """Unknown doc id -> error with safe code; no path leak."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-1", str(work), now_ms=1)

    service = OfficeToolService()
    result = service.read(conn, "sess-1", binding.generation, "ghost-doc")
    assert result["success"] is False
    assert result["error"]["code"] == "document_not_found"
    # No path leak in the error message.
    full_text = json.dumps(result, ensure_ascii=False, default=str)
    assert str(work.resolve()) not in full_text


def test_read_archived_doc_treated_as_not_found(tmp_path: Path):
    """Archived doc -> same error as unknown (indistinguishable)."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-1", str(work), now_ms=1)
    save_document(
        conn,
        _make_doc(
            doc_id="archived",
            workspace_path=binding.workspace_path,
            archived_at=9_999_999,
        ),
    )

    service = OfficeToolService()
    result = service.read(conn, "sess-1", binding.generation, "archived")
    assert result["success"] is False
    assert result["error"]["code"] == "document_not_found"


def test_read_rejects_file_exceeding_max_read_bytes(tmp_path: Path):
    """A file whose on-disk size exceeds ``max_read_bytes`` must be refused
    with ``file_too_large`` before the parser runs.
    """
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-1", str(work), now_ms=1)
    doc_summary = _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path)
    save_document(conn, doc_summary)
    # Write a real .docx at the managed path.
    from backend.office.storage import document_path

    _write_minimal_docx(document_path(doc_summary))

    # ``max_read_bytes=1`` is smaller than any real .docx, so the service
    # must refuse the read before invoking the parser.
    service = OfficeToolService(policy=ToolPolicy(max_read_bytes=1))
    result = service.read(conn, "sess-1", binding.generation, "doc-a", section="all")
    assert result["success"] is False
    assert result["error"]["code"] == "file_too_large"


def test_read_stale_generation_returns_not_found(tmp_path: Path):
    """Stale binding generation -> document_not_found (indistinguishable)."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-1", str(work), now_ms=1)
    save_document(
        conn,
        _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path),
    )

    service = OfficeToolService()
    result = service.read(conn, "sess-1", binding.generation + 1, "doc-a")
    assert result["success"] is False
    assert result["error"]["code"] == "document_not_found"


# ──────────────────────────────────────────────────────────────────────
# read: choosing between summary / head / all sections
# ──────────────────────────────────────────────────────────────────────


def test_read_summary_returns_only_summary_section(tmp_path: Path):
    """``section='summary'`` returns a summary-only dict (no content body)."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-1", str(work), now_ms=1)
    save_document(
        conn,
        _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path),
    )

    service = OfficeToolService()
    result = service.read(conn, "sess-1", binding.generation, "doc-a", section="summary")
    assert result["success"] is True
    assert "summary" in result["content"]
    # content must not have slide/paragraph/sheet body sections.
    content = result["content"]
    for body_key in ("slides", "paragraphs", "sheets"):
        assert body_key not in content


def _write_minimal_docx(path: Path) -> None:
    """Write a minimal .docx file so the reader has something to parse."""
    from docx import Document

    doc = Document()
    doc.add_paragraph("hello world " * 50)  # ~600 bytes of body text
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)


def test_read_all_exceeding_output_bytes_returns_truncated_head(
    tmp_path: Path,
):
    """``section='all'`` that exceeds ``max_output_bytes`` degrades to bounded
    head + ``truncated=True``. Result size must stay within the policy cap.
    """
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-1", str(work), now_ms=1)
    doc_summary = _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path)
    save_document(conn, doc_summary)
    # Write a real .docx at the managed path so the reader can parse it.
    from backend.office.storage import document_path

    _write_minimal_docx(document_path(doc_summary))

    # ``max_output_bytes=32`` is small enough that any realistic read result
    # exceeds it. The service must degrade to bounded head + truncated flag.
    service = OfficeToolService(policy=ToolPolicy(max_output_bytes=32))
    result = service.read(conn, "sess-1", binding.generation, "doc-a", section="all")
    assert result["success"] is True
    assert result["content"].get("truncated") is True


# ──────────────────────────────────────────────────────────────────────
# create: round-trip — file lands under workspace/office/<doc_type>/<id>/<name>
#         AND the row is registered so list/read see it.
# ──────────────────────────────────────────────────────────────────────


def _word_create_args(**overrides) -> dict:
    """Default args for ``service.create(..., doc_type='word', ...)``."""
    args = {
        "doc_type": "word",
        "filename": "天气.docx",
        "content": {"title": "天气", "paragraphs": [{"text": "今天天气很好"}]},
    }
    args.update(overrides)
    return args


def test_create_writes_file_and_registers_row(tmp_path: Path):
    """``create`` must (1) write the file inside the workspace's managed
    directory and (2) register an ``office_documents`` row so the next
    ``list`` / ``read`` call sees it. Otherwise tool-generated docs are
    invisible to the Office scope — the round-trip bug T7.5 plans to fix.
    """
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-create")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-create", str(work), now_ms=1)

    service = OfficeToolService()
    result = service.create(
        conn,
        "sess-create",
        binding.generation,
        **_word_create_args(),
    )

    # Return shape: {document_id, doc_type, filename}; NEVER an absolute path.
    assert result["success"] is True
    assert result["content"]["doc_type"] == "word"
    assert result["content"]["filename"] == "天气.docx"
    document_id = result["content"]["document_id"]
    assert isinstance(document_id, str)
    assert len(document_id) >= 16

    # File landed under <workspace>/office/word/<document_id>/<filename>.
    on_disk = work / "office" / "word" / document_id / "天气.docx"
    assert on_disk.is_file(), f"file missing: {on_disk}"

    # The list path sees the registered row.
    listed = service.list(conn, "sess-create", binding.generation)
    assert len(listed) == 1
    assert listed[0]["id"] == document_id

    # And the read path can parse the file end-to-end.
    read = service.read(conn, "sess-create", binding.generation, document_id)
    assert read["success"] is True


def test_create_returns_only_document_id_doc_type_filename(tmp_path: Path):
    """Result payload must omit ``path`` / ``workspace_path`` / ``bytes``.

    Tool-generated Office docs are now first-class Office scope items, not
    raw file paths. Echoing the absolute path would defeat the "no path
    leak to the LLM" invariant already enforced by ``list`` / ``read``.
    """
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-create")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-create", str(work), now_ms=1)

    service = OfficeToolService()
    result = service.create(
        conn,
        "sess-create",
        binding.generation,
        **_word_create_args(),
    )
    payload = result["content"]
    assert set(payload.keys()) == {"document_id", "doc_type", "filename"}
    full_text = json.dumps(result, ensure_ascii=False)
    assert str(work.resolve()) not in full_text


def test_create_fails_closed_on_generation_mismatch(tmp_path: Path):
    """Stale ``binding_generation`` → no file, no row.

    Symmetric with the ``list`` / ``read`` generation-mismatch contract:
    a revoked / rebound binding must not silently allow the create to
    land in some orphan directory or leak the absence of a binding via
    a confusing error.
    """
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-create")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-create", str(work), now_ms=1)

    service = OfficeToolService()
    result = service.create(
        conn,
        "sess-create",
        binding.generation + 99,
        **_word_create_args(),
    )

    assert result["success"] is False
    # No files should have landed under any office/ directory.
    office_dirs = list(work.rglob("office"))
    assert office_dirs == [], f"unexpected files written: {office_dirs}"
    # No row was registered either.
    assert service.list(conn, "sess-create", binding.generation) == []


def test_create_rolls_back_file_on_registration_failure(tmp_path: Path, monkeypatch):
    """If ``save_document`` raises after the file was written, the file
    must be removed so the on-disk state matches the SQLite state.

    Otherwise the next list call wouldn't surface the doc but the file
    would persist as an orphan — silent failure mode T7.5 explicitly
    calls out as the round-trip bug.
    """
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-create")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-create", str(work), now_ms=1)

    # Force save_document to blow up after the file write.
    from backend.office import tool_service as svc_mod

    def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated DB outage")

    monkeypatch.setattr(svc_mod, "save_document", _boom)

    service = OfficeToolService()
    result = service.create(
        conn,
        "sess-create",
        binding.generation,
        **_word_create_args(),
    )

    assert result["success"] is False
    # The orphan file must have been cleaned up.
    office_files = list(work.rglob("*.docx"))
    assert office_files == [], f"orphan files remain: {office_files}"


# ──────────────────────────────────────────────────────────────────────
# update: in-place edit — binding-scoped, status flips to EDITED,
#         failed ops leave the file (and row) untouched.
# ──────────────────────────────────────────────────────────────────────


def test_update_applies_ops_and_marks_row_edited(tmp_path: Path):
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-upd")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-upd", str(work), now_ms=1)
    doc_summary = _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path)
    save_document(conn, doc_summary)
    from backend.office.storage import document_path

    _write_minimal_docx(document_path(doc_summary))

    service = OfficeToolService()
    result = service.update(
        conn,
        "sess-upd",
        binding.generation,
        "doc-a",
        [{"op": "replace_text", "find": "hello world", "replace": "goodbye world"}],
    )
    assert result["success"] is True
    assert result["content"]["document_id"] == "doc-a"
    assert result["content"]["results"][0]["replacements"] >= 1
    assert "workspace_path" not in str(result["content"])

    row = conn.execute(
        "SELECT status, updated_at FROM office_documents WHERE id = 'doc-a'"
    ).fetchone()
    assert row["status"] == OfficeDocStatus.EDITED.value
    assert row["updated_at"] > doc_summary.updated_at


def test_update_unknown_doc_returns_not_found(tmp_path: Path):
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-upd")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-upd", str(work), now_ms=1)

    service = OfficeToolService()
    result = service.update(
        conn, "sess-upd", binding.generation, "ghost", [{"op": "replace_text", "find": "a", "replace": "b"}]
    )
    assert result == {
        "success": False,
        "error": {"code": "document_not_found", "message": "document not found"},
    }


def test_update_failed_ops_leave_file_and_row_untouched(tmp_path: Path):
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-upd")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-upd", str(work), now_ms=1)
    doc_summary = _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path)
    save_document(conn, doc_summary)
    from backend.office.storage import document_path

    _write_minimal_docx(document_path(doc_summary))
    before = document_path(doc_summary).stat().st_mtime_ns

    service = OfficeToolService()
    result = service.update(
        conn,
        "sess-upd",
        binding.generation,
        "doc-a",
        [{"op": "replace_text", "find": "不存在的句子", "replace": "x"}],
    )
    assert result["success"] is False
    assert result["error"]["code"] == "operation_failed"
    assert result["results"][0]["ok"] is False
    assert document_path(doc_summary).stat().st_mtime_ns == before
    row = conn.execute("SELECT status FROM office_documents WHERE id = 'doc-a'").fetchone()
    assert row["status"] == OfficeDocStatus.GENERATED.value


def test_update_respects_max_read_bytes(tmp_path: Path):
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-upd")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-upd", str(work), now_ms=1)
    doc_summary = _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path)
    save_document(conn, doc_summary)
    from backend.office.storage import document_path

    _write_minimal_docx(document_path(doc_summary))

    service = OfficeToolService(policy=ToolPolicy(max_read_bytes=10))
    result = service.update(
        conn, "sess-upd", binding.generation, "doc-a", [{"op": "replace_text", "find": "a", "replace": "b"}]
    )
    assert result["success"] is False
    assert result["error"]["code"] == "file_too_large"


def test_update_stale_generation_returns_not_found(tmp_path: Path):
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-upd")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-upd", str(work), now_ms=1)
    save_document(conn, _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path))

    service = OfficeToolService()
    result = service.update(
        conn, "sess-upd", binding.generation + 1, "doc-a", [{"op": "replace_text", "find": "a", "replace": "b"}]
    )
    assert result["error"]["code"] == "document_not_found"


# ──────────────────────────────────────────────────────────────────────
# delete: binding-scoped — managed dir + row removed together,
#         files-first so a locked file keeps a consistent state.
# ──────────────────────────────────────────────────────────────────────


def test_delete_removes_managed_dir_and_row(tmp_path: Path):
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-del")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-del", str(work), now_ms=1)
    doc_summary = _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path)
    save_document(conn, doc_summary)
    from backend.office.storage import document_path

    _write_minimal_docx(document_path(doc_summary))
    managed_dir = document_path(doc_summary).parent
    assert managed_dir.is_dir()

    service = OfficeToolService()
    result = service.delete(conn, "sess-del", binding.generation, "doc-a")
    assert result["success"] is True
    assert result["content"] == {"document_id": "doc-a", "doc_type": "word"}
    assert not managed_dir.exists()
    assert conn.execute("SELECT COUNT(*) c FROM office_documents WHERE id='doc-a'").fetchone()["c"] == 0
    # list 不再可见
    assert service.list(conn, "sess-del", binding.generation) == []


def test_delete_unknown_doc_returns_not_found(tmp_path: Path):
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-del")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-del", str(work), now_ms=1)

    service = OfficeToolService()
    result = service.delete(conn, "sess-del", binding.generation, "ghost")
    assert result["error"]["code"] == "document_not_found"


def test_delete_rmtree_failure_keeps_row(tmp_path: Path, monkeypatch):
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-del")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-del", str(work), now_ms=1)
    doc_summary = _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path)
    save_document(conn, doc_summary)
    from backend.office.storage import document_path

    _write_minimal_docx(document_path(doc_summary))

    def _boom(_path):
        raise OSError("file locked by Word")

    monkeypatch.setattr("shutil.rmtree", _boom)

    service = OfficeToolService()
    result = service.delete(conn, "sess-del", binding.generation, "doc-a")
    assert result["success"] is False
    assert result["error"]["code"] == "delete_failed"
    # 行保留，文件保留 —— 状态一致，用户可重试
    assert conn.execute("SELECT COUNT(*) c FROM office_documents WHERE id='doc-a'").fetchone()["c"] == 1
    assert document_path(doc_summary).is_file()
