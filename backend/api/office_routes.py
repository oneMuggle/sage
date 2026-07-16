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
from typing import TYPE_CHECKING

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from backend.data.database import Database, get_database
from backend.office.errors import OfficeError, office_error_to_http_status
from backend.office.excel import read_xlsx
from backend.office.models import (
    OfficeDeleteResponse,
    OfficeDocumentListResponse,
    OfficeExcelReadResult,
    OfficePptReadResult,
    OfficeReadRequest,
    OfficeWordReadResult,
)
from backend.office.ppt import read_ppt
from backend.office.storage import delete_document, list_documents
from backend.office.word import read_docx

if TYPE_CHECKING:
    pass

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


@router.post("/ppt/read", response_model=OfficePptReadResult)
def read_ppt_endpoint(req: OfficeReadRequest) -> OfficePptReadResult:
    """Read a .pptx file and return structured content."""
    logger.info("Reading PPT: %s", req.file_path)
    return read_ppt(
        file_path=Path(req.file_path),
        workspace_path=req.workspace_path,
    )


@router.post("/word/read", response_model=OfficeWordReadResult)
def read_word_endpoint(req: OfficeReadRequest) -> OfficeWordReadResult:
    """Read a .docx file and return structured content."""
    logger.info("Reading Word: %s", req.file_path)
    return read_docx(
        file_path=Path(req.file_path),
        workspace_path=req.workspace_path,
    )


@router.post("/excel/read", response_model=OfficeExcelReadResult)
def read_excel_endpoint(req: OfficeReadRequest) -> OfficeExcelReadResult:
    """Read a .xlsx file and return structured content."""
    logger.info("Reading Excel: %s", req.file_path)
    return read_xlsx(
        file_path=Path(req.file_path),
        workspace_path=req.workspace_path,
    )


# ──────────────────────────────────────────────────────────────────────
# List / delete endpoints (Phase 1.2 step 8)
# ──────────────────────────────────────────────────────────────────────


@router.get("/documents", response_model=OfficeDocumentListResponse)
def list_documents_endpoint(workspace_path: str) -> OfficeDocumentListResponse:
    """List all office documents in a workspace."""
    documents = list_documents(_db().get_connection(), workspace_path)
    return OfficeDocumentListResponse(documents=documents, total=len(documents))


@router.delete("/documents/{doc_id}", response_model=OfficeDeleteResponse)
def delete_document_endpoint(doc_id: str) -> OfficeDeleteResponse:
    """Delete an office document record by id."""
    deleted = delete_document(_db().get_connection(), doc_id)
    return OfficeDeleteResponse(id=doc_id, deleted=deleted)


__all__ = [
    "router",
    "register_office_exception_handlers",
    "list_documents_endpoint",
    "delete_document_endpoint",
    "read_ppt_endpoint",
    "read_word_endpoint",
    "read_excel_endpoint",
]
