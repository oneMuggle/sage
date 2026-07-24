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
from typing import TYPE_CHECKING, Optional

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from backend.data.database import Database, get_database
from backend.office.errors import (
    OfficeError,
    OfficePathError,
    OfficeSizeLimitError,
    office_error_to_http_status,
)
from backend.office.excel import generate_xlsx, read_xlsx
from backend.office.models import (
    OfficeDeleteResponse,
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentListResponse,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
    OfficeExcelGenerateRequest,
    OfficeExcelReadResult,
    OfficePptGenerateRequest,
    OfficePptReadResult,
    OfficeReadRequest,
    OfficeWordGenerateRequest,
    OfficeWordReadResult,
)
from backend.office.path_safety import resolve_within
from backend.office.ppt import generate_ppt, read_ppt
from backend.office.storage import (
    delete_document,
    list_documents,
    save_document,
    validate_workspace,
)
from backend.office.word import generate_docx, read_docx

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
    """
    from backend.office.models import OfficeDocumentSummary  # local: avoids cycle

    conn = _db().get_connection()
    summary = result.summary
    document_id = file_path.parent.name
    # Use the file's basename as ``generated_filename`` (matches the
    # managed-import layout); ``original_filename`` is the user-visible
    # uploaded name when the caller tracked it.
    generated_filename = file_path.name
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
def list_documents_endpoint(workspace_path: str) -> OfficeDocumentListResponse:
    """List all office documents in a workspace.

    Canonicalizes ``workspace_path`` so callers that pass ``/tmp/./ws``
    or symlink-resolved variants still hit the same rows. The persisted
    rows always store the resolved form because every write path
    (``_build_summary_for_generated``, ``_persist_read_summary``)
    normalizes before INSERT.
    """
    canonical_workspace = str(Path(workspace_path).resolve())
    documents = list_documents(_db().get_connection(), canonical_workspace)
    return OfficeDocumentListResponse(documents=documents, total=len(documents))


@router.delete("/documents/{doc_id}", response_model=OfficeDeleteResponse)
def delete_document_endpoint(doc_id: str) -> OfficeDeleteResponse:
    """Delete an office document record + on-disk file directory.

    HIGH FIX: also removes <workspace>/office/<doc_type>/<doc_id>/ on disk.
    """
    deleted = _delete_office_doc_record_and_files(doc_id)
    return OfficeDeleteResponse(id=doc_id, deleted=deleted)


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
]
