"""Office document API routes (PPT/Word/Excel read + list/delete).

Implements Phase 1.2 endpoints per plan §4.1.2 step 8:
- POST /api/v1/office/ppt/read      — read .pptx file
- POST /api/v1/office/word/read     — read .docx file
- POST /api/v1/office/excel/read    — read .xlsx file
- GET  /api/v1/office/documents      — list workspace documents
- DELETE /api/v1/office/documents/{id} — delete document record

Generate endpoints (Phase 1.4) will be added in a follow-up PR.

OfficeError subclasses are mapped to HTTP status codes via
office_error_to_http_status() (errors.py). The exception handler is exposed
as `register_office_exception_handlers(app)` and called from main.py at
startup so other routers aren't affected.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.data.database import Database, get_database
from backend.office.errors import (
    OfficeError,
    OfficeFileNotFoundError,
    OfficePathError,
    OfficeSizeLimitError,
    office_error_to_http_status,
)
from backend.office.excel import generate_xlsx, read_xlsx
from backend.office.journal.generator import generate_structured
from backend.office.journal.models import (
    JournalContent,
    JournalSpec,
    JournalViolation,
    parse_obj,
)
from backend.office.journal.parser import parse_journal_spec
from backend.office.journal.persistence import (
    list_specs,
    load_spec,
    save_spec,
)
from backend.office.journal.validator import validate_document
from backend.office.models import (
    OfficeDeleteResponse,
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentActionResponse,
    OfficeDocumentListResponse,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
    OfficeExcelGenerateRequest,
    OfficeExcelReadResult,
    OfficePptGenerateRequest,
    OfficePptReadResult,
    OfficeReadRequest,
    OfficeSnapshotListResponse,
    OfficeWordGenerateRequest,
    OfficeWordReadResult,
    PdfFormFillRequest,
    PdfFormFillResult,
    PdfFormReadRequest,
    PdfFormReadResult,
    PdfGenerateRequest,
    PdfGenerateResult,
    PdfReadRequest,
    PdfReadResult,
    WordTemplateAnalysis,
    WordTemplateAnalyzeRequest,
    WordTemplateFillRequest,
    WordTemplateFillResult,
)
from backend.office.path_safety import resolve_within
from backend.office.pdf import MAX_PDF_SIZE, generate_pdf, read_pdf
from backend.office.pdf_forms import fill_pdf_form, read_pdf_form
from backend.office.ppt import generate_ppt, read_ppt
from backend.office.storage import (
    archive_document,
    delete_document,
    get_document,
    list_documents,
    list_snapshots,
    restore_document,
    restore_from_snapshot,
    save_document,
    validate_workspace,
)
from backend.office.word import generate_docx, read_docx
from backend.office.word_template import analyze_word_template, fill_word_template

if TYPE_CHECKING:
    pass


import time  # noqa: E402  (used by _build_summary_for_generated)


def _validate_file_in_workspace(file_path_str: str, workspace_path_str: str) -> Path:
    """CRITICAL SECURITY: ensure file_path is inside workspace_path.

    Rejects path traversal (../), absolute paths outside workspace, and
    symlink-escape attacks. This is the only barrier between an untrusted
    renderer IPC call and arbitrary local file reads (e.g. /etc/passwd).

    Containment is delegated to :func:`path_safety.resolve_within`, which
    resolves the candidate path (collapsing ``..`` and following
    symlinks) and uses ``PurePath.relative_to`` for the boundary check
    instead of brittle string-prefix comparison. This closes the
    sibling-prefix attack class (``/tmp/work-evil`` vs ``/tmp/work``)
    that the previous ``str.startswith`` guard missed.
    """
    workspace = validate_workspace(workspace_path_str)
    target = resolve_within(workspace, Path(file_path_str))
    if not target.is_file():
        raise OfficePathError(
            f"file_path is not a regular file: {file_path_str}",
            file_path=target,
        )
    return target


def _check_size_limit(file_path: Path, max_size_bytes: int) -> None:
    """Plan §6 R1: enforce max_size_bytes (default 50MB) before parsing."""
    actual_size = file_path.stat().st_size
    if actual_size > max_size_bytes:
        raise OfficeSizeLimitError(
            actual_size=actual_size, max_size=max_size_bytes, file_path=file_path
        )


def _build_summary_for_generated(
    *,
    file_path: Path,
    doc_type: OfficeDocType,
    workspace_path: str,
) -> OfficeDocumentSummary:
    """Build a summary for a freshly-generated document and persist it.

    CRITICAL FIX: previous version never called save_document, so the
    office_documents table stayed empty in production.
    """
    now_ms = int(time.time() * 1000)
    # Resolve workspace_path to canonical absolute form so list queries
    # by the same path match later (prevents `/tmp/./foo` vs `/tmp/foo` mismatch).
    canonical_workspace = str(Path(workspace_path).resolve())
    summary = OfficeDocumentSummary(
        id=file_path.parent.name,  # storage places <doc_id>/ next to the file
        workspace_path=canonical_workspace,
        doc_type=doc_type,
        original_filename=None,
        generated_filename=file_path.name,
        status=OfficeDocStatus.GENERATED,
        created_at=now_ms,
        updated_at=now_ms,
        metadata=OfficeDocumentMetadata(file_size_bytes=file_path.stat().st_size),
    )
    save_document(_db().get_connection(), summary)
    return summary


def _delete_office_doc_record_and_files(doc_id: str) -> bool:
    """Delete the DB row AND the on-disk file directory.

    HIGH FIX (Phase 2 — real implementation):
    - Resolve workspace_path before computing parent_dir (avoids drift
      between stored DB path and on-disk path)
    - Use rmtree WITHOUT ignore_errors=True; on Windows file-locked case,
      the OSError propagates so the caller (and user via toast) sees the
      cleanup failure instead of silently orphaning the file
    """
    import shutil

    conn = _db().get_connection()
    row = conn.execute(
        "SELECT workspace_path, doc_type FROM office_documents WHERE id = ?",
        (doc_id,),
    ).fetchone()
    deleted = delete_document(conn, doc_id)
    if row:
        canonical_workspace = str(Path(row["workspace_path"]).resolve())
        parent_dir = Path(canonical_workspace) / "office" / row["doc_type"] / doc_id
        if parent_dir.is_dir():
            # Don't use ignore_errors=True — caller (delete endpoint) will
            # surface the OSError via FastAPI exception handler so user sees
            # the actual cleanup failure (e.g. Word still has the file open).
            shutil.rmtree(parent_dir)
    return deleted


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/office", tags=["office"])


def _db() -> Database:
    """Return the shared global Database instance (singleton).

    Using get_database() instead of a module-level Database() ensures office
    routes share the same connection as main.py's init_db() call.
    """
    return get_database()


def register_office_exception_handlers(app: FastAPI) -> None:
    """Register OfficeError → structured JSON handler on the FastAPI app.

    Must be called from main.py after `app = FastAPI(...)` is created.
    """
    app.add_exception_handler(OfficeError, _office_error_handler)


async def _office_error_handler(request: Request, exc: OfficeError) -> JSONResponse:
    """Return structured JSON error for any OfficeError subclass."""
    status_code = office_error_to_http_status(exc)
    return JSONResponse(
        status_code=status_code,
        content={
            "error_type": type(exc).__name__,
            "message": exc.message,
            "file_path": str(exc.file_path) if exc.file_path else None,
        },
    )


# ──────────────────────────────────────────────────────────────────────
# Read endpoints
# ──────────────────────────────────────────────────────────────────────


def _persist_read_summary(
    result,
    *,
    file_path: Path,
    canonical_workspace: str,
    original_filename: Optional[str],
) -> None:
    """Persist a read result's summary into the office_documents table.

    M0 Task 3: every read creates (or refreshes) a ``parsed`` row keyed by
    the managed directory name. Callers (chat tools, IPC handlers) can
    then list workspace history without re-reading files.

    Implementation note: ``result`` is duck-typed because PPT/Word/Excel
    results each carry their own concrete ``OfficeXxxReadResult`` type
    with the same ``.summary`` attribute. We mutate ``result.summary`` in
    place so the response body reflects the persisted identifiers (the
    reader builds the summary with ``document_id=file_path.stem`` which
    is *not* the managed UUID when the file lives in a UUID directory).

    PR-3 merge semantics: a row that already exists keeps its
    ``archived_at`` / ``derived_from`` (lineage + soft-delete state) and
    its ``original_filename`` (user's uploaded name) when the caller
    passes ``None`` for that field on a re-read. ``status`` and
    ``metadata`` (including ``file_size_bytes`` which the readers set
    via ``file_path.stat().st_size``) are always refreshed from the
    reader because a re-parse produces fresh content + filesystem
    facts. Without this merge, every read would re-INSERT OR REPLACE
    the row and un-archive previously archived documents, drop
    derived_from lineage, and stomp the user-visible original
    filename.
    """
    from backend.office.models import OfficeDocumentSummary  # local: avoids cycle

    conn = _db().get_connection()
    summary = result.summary
    document_id = file_path.parent.name
    # Use the file's basename as ``generated_filename`` (matches the
    # managed-import layout); ``original_filename`` is the user-visible
    # uploaded name when the caller tracked it.
    generated_filename = file_path.name
    # PR-3: read the existing row first so we can preserve lineage,
    # archive state, and original_filename on re-read.
    existing = get_document(conn, document_id)
    if existing is not None:
        # Preserve user/system-managed fields; only refresh reader-derived
        # ones (status, updated_at, metadata facts that the reader sets).
        # ``original_filename`` is kept as the prior value when the
        # caller passed ``None`` on this re-read — the user-supplied
        # name shouldn't silently clear because we re-parsed the file.
        merged_original_filename = (
            original_filename if original_filename is not None
            else existing.original_filename
        )
        persisted = OfficeDocumentSummary(
            id=document_id,
            workspace_path=canonical_workspace,
            doc_type=summary.doc_type,
            original_filename=merged_original_filename,
            generated_filename=generated_filename,
            status=summary.status,
            created_at=existing.created_at,
            updated_at=summary.updated_at,
            metadata=summary.metadata,
            derived_from=existing.derived_from,
            archived_at=existing.archived_at,
        )
    else:
        # Fresh read — no prior row to merge with.
        persisted = OfficeDocumentSummary(
            id=document_id,
            workspace_path=canonical_workspace,
            doc_type=summary.doc_type,
            original_filename=original_filename,
            generated_filename=generated_filename,
            status=summary.status,
            created_at=summary.created_at,
            updated_at=summary.updated_at,
            metadata=summary.metadata,
            derived_from=summary.derived_from,
            archived_at=summary.archived_at,
        )
    save_document(conn, persisted)
    # Patch the returned summary so the caller sees the same id/filename
    # that was persisted (otherwise the reader's default ``file_path.stem``
    # id leaks out, breaking the contract that ``id == managed dir name``).
    result.summary = persisted


@router.post("/ppt/read", response_model=OfficePptReadResult)
def read_ppt_endpoint(req: OfficeReadRequest) -> OfficePptReadResult:
    """Read a .pptx file and return structured content.

    SECURITY: file_path is validated to lie inside workspace_path.
    Plan §6 R1: rejects files >max_size_bytes (default 50MB) to prevent OOM.
    M0 Task 3: persists a ``parsed`` row keyed by the managed directory UUID.
    """
    logger.info("Reading PPT: %s", req.file_path)
    file_path = _validate_file_in_workspace(req.file_path, req.workspace_path)
    _check_size_limit(file_path, req.max_size_bytes)
    # Canonicalize workspace_path so the row's ``workspace_path`` matches
    # the same canonical form used by list_documents() and the generators.
    canonical_workspace = str(Path(req.workspace_path).resolve())
    result = read_ppt(
        file_path=file_path,
        workspace_path=canonical_workspace,
        generated_filename=file_path.name,
        original_filename=req.original_filename,
    )
    _persist_read_summary(
        result,
        file_path=file_path,
        canonical_workspace=canonical_workspace,
        original_filename=req.original_filename,
    )
    return result


@router.post("/word/read", response_model=OfficeWordReadResult)
def read_word_endpoint(req: OfficeReadRequest) -> OfficeWordReadResult:
    """Read a .docx file and return structured content."""
    logger.info("Reading Word: %s", req.file_path)
    file_path = _validate_file_in_workspace(req.file_path, req.workspace_path)
    _check_size_limit(file_path, req.max_size_bytes)
    canonical_workspace = str(Path(req.workspace_path).resolve())
    result = read_docx(
        file_path=file_path,
        workspace_path=canonical_workspace,
        generated_filename=file_path.name,
        original_filename=req.original_filename,
    )
    _persist_read_summary(
        result,
        file_path=file_path,
        canonical_workspace=canonical_workspace,
        original_filename=req.original_filename,
    )
    return result


@router.post("/excel/read", response_model=OfficeExcelReadResult)
def read_excel_endpoint(req: OfficeReadRequest) -> OfficeExcelReadResult:
    """Read a .xlsx file and return structured content."""
    logger.info("Reading Excel: %s", req.file_path)
    file_path = _validate_file_in_workspace(req.file_path, req.workspace_path)
    _check_size_limit(file_path, req.max_size_bytes)
    canonical_workspace = str(Path(req.workspace_path).resolve())
    result = read_xlsx(
        file_path=file_path,
        workspace_path=canonical_workspace,
        generated_filename=file_path.name,
        original_filename=req.original_filename,
    )
    _persist_read_summary(
        result,
        file_path=file_path,
        canonical_workspace=canonical_workspace,
        original_filename=req.original_filename,
    )
    return result


# ──────────────────────────────────────────────────────────────────────
# List / delete endpoints (Phase 1.2 step 8)
# ──────────────────────────────────────────────────────────────────────


@router.get("/documents", response_model=OfficeDocumentListResponse)
def list_documents_endpoint(
    workspace_path: str, include_archived: bool = False
) -> OfficeDocumentListResponse:
    """List all office documents in a workspace.

    Canonicalizes ``workspace_path`` so callers that pass ``/tmp/./ws``
    or symlink-resolved variants still hit the same rows. The persisted
    rows always store the resolved form because every write path
    (``_build_summary_for_generated``, ``_persist_read_summary``)
    normalizes before INSERT.

    ``include_archived``（Item 1.7 归档 UI）：True 时包含软删除行，
    前端「归档文档」视图用；默认只返回 live 文档。
    """
    canonical_workspace = str(Path(workspace_path).resolve())
    documents = list_documents(
        _db().get_connection(), canonical_workspace, include_archived=include_archived
    )
    return OfficeDocumentListResponse(documents=documents, total=len(documents))


@router.delete("/documents/{doc_id}", response_model=OfficeDeleteResponse)
def delete_document_endpoint(doc_id: str) -> OfficeDeleteResponse:
    """Delete an office document record + on-disk file directory.

    HIGH FIX: also removes <workspace>/office/<doc_type>/<doc_id>/ on disk.
    """
    deleted = _delete_office_doc_record_and_files(doc_id)
    return OfficeDeleteResponse(id=doc_id, deleted=deleted)


# ──────────────────────────────────────────────────────────────────────
# Archive / restore / snapshot endpoints (Item 1.7 — 前端归档 + 版本回滚)
# ──────────────────────────────────────────────────────────────────────


def _require_document(conn, doc_id: str) -> OfficeDocumentSummary:
    """Fetch a document or raise 404-mapped OfficeFileNotFoundError."""
    doc = get_document(conn, doc_id)
    if doc is None:
        # OfficeFileNotFoundError 只接受 file_path（message 由基类拼装）
        raise OfficeFileNotFoundError(Path(doc_id))
    return doc


@router.post("/doc/{doc_id}/archive", response_model=OfficeDocumentActionResponse)
def archive_document_endpoint(doc_id: str) -> OfficeDocumentActionResponse:
    """Soft-delete a document (row stays; default list hides it). Idempotent."""
    conn = _db().get_connection()
    _require_document(conn, doc_id)
    archive_document(conn, doc_id)
    return OfficeDocumentActionResponse(ok=True, summary=get_document(conn, doc_id))


@router.post("/doc/{doc_id}/restore", response_model=OfficeDocumentActionResponse)
def restore_document_endpoint(doc_id: str) -> OfficeDocumentActionResponse:
    """Un-archive a soft-deleted document. Idempotent."""
    conn = _db().get_connection()
    _require_document(conn, doc_id)
    restore_document(conn, doc_id)
    return OfficeDocumentActionResponse(ok=True, summary=get_document(conn, doc_id))


@router.get("/doc/{doc_id}/snapshots", response_model=OfficeSnapshotListResponse)
def list_snapshots_endpoint(doc_id: str) -> OfficeSnapshotListResponse:
    """List a document's pre-edit snapshots (newest first)."""
    conn = _db().get_connection()
    doc = _require_document(conn, doc_id)
    snapshots = list_snapshots(doc)
    return OfficeSnapshotListResponse(snapshots=snapshots, total=len(snapshots))


@router.post(
    "/doc/{doc_id}/snapshots/{snapshot_id}/restore",
    response_model=OfficeDocumentActionResponse,
)
def restore_snapshot_endpoint(doc_id: str, snapshot_id: str) -> OfficeDocumentActionResponse:
    """Revert the document file to a pre-edit snapshot.

    恢复前 storage 层会先把当前文件再快照一份（恢复本身可撤销），
    并刷新 DB 的 ``updated_at`` / ``file_size_bytes``。
    """
    conn = _db().get_connection()
    doc = _require_document(conn, doc_id)
    updated = restore_from_snapshot(conn, doc, snapshot_id)
    return OfficeDocumentActionResponse(ok=True, summary=updated)


# ──────────────────────────────────────────────────────────────────────
# Generate endpoints (Phase 1.4 step 19, plan §4.1.4)
# ──────────────────────────────────────────────────────────────────────


@router.post("/ppt/generate")
def generate_ppt_endpoint(req: OfficePptGenerateRequest) -> dict:
    """Generate a .pptx file from structured input.

    CRITICAL FIX: now also calls save_document() to persist the generated
    document in the office_documents table so it appears in the list API.
    """
    output_path = generate_ppt(req)
    _build_summary_for_generated(
        file_path=output_path,
        doc_type=OfficeDocType.PPT,
        workspace_path=req.workspace_path,
    )
    return {
        "output_path": str(output_path),
        "filename": output_path.name,
        "file_size_bytes": output_path.stat().st_size,
    }


@router.post("/word/generate")
def generate_word_endpoint(req: OfficeWordGenerateRequest) -> dict:
    """Generate a .docx file from structured input."""
    output_path = generate_docx(req)
    _build_summary_for_generated(
        file_path=output_path,
        doc_type=OfficeDocType.WORD,
        workspace_path=req.workspace_path,
    )
    return {
        "output_path": str(output_path),
        "filename": output_path.name,
        "file_size_bytes": output_path.stat().st_size,
    }


@router.post("/excel/generate")
def generate_excel_endpoint(req: OfficeExcelGenerateRequest) -> dict:
    """Generate a .xlsx file from structured input."""
    output_path = generate_xlsx(req)
    _build_summary_for_generated(
        file_path=output_path,
        doc_type=OfficeDocType.EXCEL,
        workspace_path=req.workspace_path,
    )
    return {
        "output_path": str(output_path),
        "filename": output_path.name,
        "file_size_bytes": output_path.stat().st_size,
    }


# ──────────────────────────────────────────────────────────────────────
# Word Template endpoints (Phase 2)
# ──────────────────────────────────────────────────────────────────────


@router.post("/word/analyze-template", response_model=WordTemplateAnalysis)
def analyze_word_template_endpoint(
    req: WordTemplateAnalyzeRequest,
) -> WordTemplateAnalysis:
    """Analyze a Word template and extract {{}} placeholders."""
    file_path = _validate_file_in_workspace(req.template_path, req.workspace_path)
    return analyze_word_template(file_path, workspace_path=req.workspace_path)


@router.post("/word/fill-template", response_model=WordTemplateFillResult)
def fill_word_template_endpoint(
    req: WordTemplateFillRequest,
) -> WordTemplateFillResult:
    """Fill a Word template with data.

    Service function handles all validation internally (workspace boundary,
    output path safety, template safety scan).
    """
    return fill_word_template(req)


# ──────────────────────────────────────────────────────────────────────
# PDF endpoints (Phase 2)
# ──────────────────────────────────────────────────────────────────────


@router.post("/pdf/read", response_model=PdfReadResult)
def read_pdf_endpoint(req: PdfReadRequest) -> PdfReadResult:
    """Read a PDF file and extract content."""
    file_path = _validate_file_in_workspace(req.file_path, req.workspace_path)
    _check_size_limit(file_path, MAX_PDF_SIZE)
    canonical_workspace = str(Path(req.workspace_path).resolve())
    result = read_pdf(file_path, workspace_path=req.workspace_path)
    # Item 1.2: PDF 读取与 PPT/Word/Excel 一致入库，出现在文档列表里
    _persist_read_summary(
        result,
        file_path=file_path,
        canonical_workspace=canonical_workspace,
        original_filename=None,
    )
    return result


@router.post("/pdf/generate", response_model=PdfGenerateResult)
def generate_pdf_endpoint(req: PdfGenerateRequest) -> PdfGenerateResult:
    """Generate a PDF from structured data.

    Service function handles workspace validation and output path safety.
    """
    return generate_pdf(req)


@router.post("/pdf/read-form", response_model=PdfFormReadResult)
def read_pdf_form_endpoint(req: PdfFormReadRequest) -> PdfFormReadResult:
    """Read PDF form fields (AcroForm)."""
    file_path = _validate_file_in_workspace(req.file_path, req.workspace_path)
    return read_pdf_form(file_path, workspace_path=req.workspace_path)


@router.post("/pdf/fill-form", response_model=PdfFormFillResult)
def fill_pdf_form_endpoint(req: PdfFormFillRequest) -> PdfFormFillResult:
    """Fill a PDF form with data.

    Service function handles all validation internally.
    """
    return fill_pdf_form(req)



# ──────────────────────────────────────────────────────────────────────
# Journal template subsystem (2026-09-10): 5 endpoints
#
# - POST /office/journal/parse-template      : docx → JournalSpec (cache by sha256)
# - GET  /office/journal/specs               : list workspace specs
# - GET  /office/journal/specs/{spec_id}     : load one spec by id
# - POST /office/journal/validate            : filled docx → violations[]
# - POST /office/journal/fill-from-content   : structured fill → docx
#
# generate_article (LLM self-correction) is tool-only; no HTTP endpoint
# because LLM streams are not yet wired into the FastAPI surface.
# ──────────────────────────────────────────────────────────────────────


class OfficeJournalParseRequest(BaseModel):
    workspace_path: str = Field(..., description="Active workspace root.")
    file_path: str = Field(..., description="Absolute path to .doc/.docx template.")
    max_size_bytes: int = Field(
        default=50 * 1024 * 1024,
        description="Plan §6 R1: enforce 50MB max before parsing.",
    )


class OfficeJournalSpecSummary(BaseModel):
    spec_id: str
    template_sha256: str
    template_filename: str
    headings: List[str]
    body_pt: float


class OfficeJournalSpecListResponse(BaseModel):
    specs: List[OfficeJournalSpecSummary]
    total: int


class OfficeJournalSpecDetailResponse(BaseModel):
    spec: JournalSpec


class OfficeJournalParseResponse(BaseModel):
    spec: JournalSpec
    cached: bool = Field(..., description="True if spec was already in workspace cache.")


class OfficeJournalFillRequest(BaseModel):
    workspace_path: str
    spec_id: Optional[str] = Field(default=None)
    file_path: Optional[str] = Field(default=None)
    content: dict
    output_filename: Optional[str] = Field(default=None)


class OfficeJournalFillResponse(BaseModel):
    gen_id: str
    spec_id: str
    output_path: str
    bytes_written: int


class OfficeJournalValidateRequest(BaseModel):
    workspace_path: str
    spec_id: Optional[str] = Field(default=None)
    file_path: str = Field(..., description="Absolute path to the filled .docx.")


class OfficeJournalValidateResponse(BaseModel):
    spec_id: str
    file_path: str
    violations: List[JournalViolation]
    error_count: int
    warning_count: int


def _canonicalize_workspace(workspace_path: str) -> Path:
    """Resolve workspace root; raise OfficePathError on missing dir."""
    from backend.office.errors import OfficePathError

    ws = validate_workspace(workspace_path)
    if not ws.is_dir():
        raise OfficePathError(f"workspace_path is not a directory: {workspace_path}")
    return ws


@router.post("/journal/parse-template", response_model=OfficeJournalParseResponse)
def parse_journal_template_endpoint(
    req: OfficeJournalParseRequest,
) -> OfficeJournalParseResponse:
    """Parse a journal .doc/.docx template into a JournalSpec.

    Side effects: caches the spec under
    ``<workspace>/office/journal/specs/<spec_id>.json`` and the parsed
    template under ``<workspace>/office/journal/cache/<sha256>.docx``.
    Subsequent calls with the same template (sha256) return the cached
    spec and skip re-parsing.

    Errors:
    - file_path outside workspace → OfficePathError → 400
    - file not found → OfficeFileNotFoundError → 404
    - JournalParseError → 422
    - file > max_size_bytes → OfficeSizeLimitError → 413
    """
    from backend.office.errors import OfficeFileNotFoundError, OfficePathError

    canonical_ws = _canonicalize_workspace(req.workspace_path)
    file_path = Path(req.file_path).expanduser()
    # workspace boundary check (mirrors _validate_file_in_workspace)
    try:
        bounded = resolve_within(canonical_ws, file_path)
    except Exception:
        raise OfficePathError(
            f"file_path escapes workspace: {req.file_path}",
            file_path=file_path,
        )
    if not bounded.is_file():
        raise OfficeFileNotFoundError(bounded)
    _check_size_limit(bounded, req.max_size_bytes)
    # JournalParseError inherits from BOTH JournalError (→ OfficeError)
    # and OfficeParseError. Let it propagate naturally — the registered
    # OfficeError exception handler maps OfficeParseError to HTTP 422.
    spec = parse_journal_spec(bounded)
    save_spec(canonical_ws, spec)
    return OfficeJournalParseResponse(spec=spec, cached=False)


@router.get("/journal/specs", response_model=OfficeJournalSpecListResponse)
def list_journal_specs_endpoint(
    workspace_path: str,
) -> OfficeJournalSpecListResponse:
    """List all JournalSpecs in the workspace."""
    canonical_ws = _canonicalize_workspace(workspace_path)
    specs = list_specs(canonical_ws)
    summaries = [
        OfficeJournalSpecSummary(
            spec_id=s.spec_id,
            template_sha256=s.template_sha256,
            template_filename=s.template_filename,
            headings=[h.keyword for h in s.headings],
            body_pt=s.body_pt,
        )
        for s in specs
    ]
    return OfficeJournalSpecListResponse(specs=summaries, total=len(summaries))


@router.get("/journal/specs/{spec_id}", response_model=OfficeJournalSpecDetailResponse)
def get_journal_spec_endpoint(
    spec_id: str, workspace_path: str
) -> OfficeJournalSpecDetailResponse:
    """Load a single spec by id. 404 when missing."""
    from backend.office.journal.errors import JournalSpecNotFoundError

    canonical_ws = _canonicalize_workspace(workspace_path)
    try:
        spec = load_spec(canonical_ws, spec_id)
    except JournalSpecNotFoundError as exc:
        from backend.office.errors import OfficeFileNotFoundError

        raise OfficeFileNotFoundError(
            Path(spec_id), message=f"journal spec not found: {spec_id}"
        ) from exc
    return OfficeJournalSpecDetailResponse(spec=spec)


@router.post("/journal/fill-from-content", response_model=OfficeJournalFillResponse)
def fill_journal_from_content_endpoint(
    req: OfficeJournalFillRequest,
) -> OfficeJournalFillResponse:
    """Structured fill: write a JournalContent into a template, persist docx.

    Source spec is resolved by ``spec_id`` (preferred) or ``file_path``
    (re-parsed on each call). Output filename defaults to a uuid.
    """
    from backend.office.journal.errors import JournalContentShapeError, JournalSpecNotFoundError

    canonical_ws = _canonicalize_workspace(req.workspace_path)
    # Validate content shape up front for clearer 422.
    try:
        content_model = parse_obj(JournalContent, req.content)
    except Exception as exc:
        raise JournalContentShapeError(f"content shape invalid: {exc}") from exc
    # Resolve spec.
    if isinstance(req.spec_id, str) and req.spec_id.strip():
        try:
            spec = load_spec(canonical_ws, req.spec_id.strip())
        except JournalSpecNotFoundError as exc:
            from backend.office.errors import OfficeFileNotFoundError

            raise OfficeFileNotFoundError(
                Path(req.spec_id), message=f"journal spec not found: {req.spec_id}"
            ) from exc
    elif isinstance(req.file_path, str) and req.file_path.strip():
        from backend.office.errors import OfficePathError

        try:
            bounded = resolve_within(canonical_ws, Path(req.file_path))
        except Exception:
            raise OfficePathError(
                f"file_path escapes workspace: {req.file_path}",
                file_path=Path(req.file_path),
            )
        spec = parse_journal_spec(bounded)
    else:
        from backend.office.errors import OfficePathError

        raise OfficePathError("spec_id or file_path required")
    import uuid

    filename = req.output_filename or f"paper-{uuid.uuid4().hex[:8]}.docx"
    record = generate_structured(spec, content_model, canonical_ws, filename)
    return OfficeJournalFillResponse(
        gen_id=record.gen_id,
        spec_id=record.spec_id,
        output_path=record.output_path,
        bytes_written=record.bytes_written,
    )


@router.post("/journal/validate", response_model=OfficeJournalValidateResponse)
def validate_journal_endpoint(
    req: OfficeJournalValidateRequest,
) -> OfficeJournalValidateResponse:
    """Validate a filled .docx against its spec.

    Uses 6 rule categories (body_font/heading_font/body_size/line_spacing/
    margins/headings_missing/citation_style). Returns violations grouped
    into ``error_count`` / ``warning_count`` for UI rendering.
    """
    from docx import Document

    from backend.office.errors import OfficeFileNotFoundError, OfficePathError
    from backend.office.journal.errors import JournalSpecNotFoundError

    canonical_ws = _canonicalize_workspace(req.workspace_path)
    target = Path(req.file_path).expanduser()
    try:
        bounded = resolve_within(canonical_ws, target)
    except Exception:
        raise OfficePathError(
            f"file_path escapes workspace: {req.file_path}",
            file_path=target,
        )
    if not bounded.is_file():
        raise OfficeFileNotFoundError(bounded)
    # Resolve spec by id (preferred) or via re-parse of an optional template
    # file_path on the spec side. We keep one spec path here.
    if isinstance(req.spec_id, str) and req.spec_id.strip():
        try:
            spec = load_spec(canonical_ws, req.spec_id.strip())
        except JournalSpecNotFoundError as exc:
            raise OfficeFileNotFoundError(
                Path(req.spec_id), message=f"journal spec not found: {req.spec_id}"
            ) from exc
    else:
        # Without spec_id we cannot validate — spec is required for the rule
        # set. Return a 400 to keep the contract explicit (rather than silently
        # validating against an empty spec).
        raise OfficePathError("spec_id is required for journal validation")
    doc = Document(str(bounded))
    violations = validate_document(doc, spec)
    error_count = sum(1 for v in violations if v.severity.value == "error")
    warning_count = sum(1 for v in violations if v.severity.value == "warning")
    return OfficeJournalValidateResponse(
        spec_id=spec.spec_id,
        file_path=str(bounded),
        violations=violations,
        error_count=error_count,
        warning_count=warning_count,
    )


__all__ = [
    "router",
    "register_office_exception_handlers",
    "list_documents_endpoint",
    "delete_document_endpoint",
    "read_ppt_endpoint",
    "read_word_endpoint",
    "read_excel_endpoint",
    "generate_ppt_endpoint",
    "generate_word_endpoint",
    "generate_excel_endpoint",
    # Phase 2: Word template + PDF
    "analyze_word_template_endpoint",
    "fill_word_template_endpoint",
    "read_pdf_endpoint",
    "generate_pdf_endpoint",
    "read_pdf_form_endpoint",
    "fill_pdf_form_endpoint",
    # Item 1.7: archive / restore / snapshots
    "archive_document_endpoint",
    "restore_document_endpoint",
    "list_snapshots_endpoint",
    "restore_snapshot_endpoint",
    # 2026-09-10 journal template subsystem
    "parse_journal_template_endpoint",
    "list_journal_specs_endpoint",
    "get_journal_spec_endpoint",
    "fill_journal_from_content_endpoint",
    "validate_journal_endpoint",
]
