# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Office Journal Template HTTP routes (extracted from office_routes.py for L5).

Covers 5 endpoints:
- POST /office/journal/parse-template      : docx -> JournalSpec (cache by sha256)
- GET  /office/journal/specs               : list workspace specs
- GET  /office/journal/specs/{spec_id}     : load one spec by id
- POST /office/journal/validate            : filled docx -> violations[]
- POST /office/journal/fill-from-content   : structured fill -> docx
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.office.errors import OfficeFileNotFoundError, OfficePathError, OfficeSizeLimitError
from backend.office.journal.errors import JournalContentShapeError, JournalSpecNotFoundError
from backend.office.journal.generator import generate_structured
from backend.office.journal.models import (
    JournalContent,
    JournalSpec,
    JournalViolation,
)
from backend.office.journal.parser import parse_journal_spec
from backend.office.journal.persistence import (
    list_specs,
    load_spec,
    save_spec,
)
from backend.office.journal.validator import validate_document
from backend.office.path_safety import resolve_within
from backend.office.storage import validate_workspace

router = APIRouter(tags=["office-journal"])


def _check_size_limit(file_path: Path, max_bytes: int) -> None:
    size = file_path.stat().st_size
    if size > max_bytes:
        raise OfficeSizeLimitError(
            file_path=file_path,
            actual_bytes=size,
            limit_bytes=max_bytes,
        )


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
    ws = validate_workspace(workspace_path)
    if not ws.is_dir():
        raise OfficePathError(f"workspace_path is not a directory: {workspace_path}")
    return ws


@router.post("/journal/parse-template", response_model=OfficeJournalParseResponse)
def parse_journal_template_endpoint(
    req: OfficeJournalParseRequest,
) -> OfficeJournalParseResponse:
    """Parse a journal .doc/.docx template into a JournalSpec."""
    canonical_ws = _canonicalize_workspace(req.workspace_path)
    file_path = Path(req.file_path).expanduser()
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
    canonical_ws = _canonicalize_workspace(workspace_path)
    try:
        spec = load_spec(canonical_ws, spec_id)
    except JournalSpecNotFoundError as exc:
        raise OfficeFileNotFoundError(
            Path(spec_id), message=f"journal spec not found: {spec_id}"
        ) from exc
    return OfficeJournalSpecDetailResponse(spec=spec)


@router.post("/journal/fill-from-content", response_model=OfficeJournalFillResponse)
def fill_journal_from_content_endpoint(
    req: OfficeJournalFillRequest,
) -> OfficeJournalFillResponse:
    """Structured fill: write a JournalContent into a template, persist docx."""
    canonical_ws = _canonicalize_workspace(req.workspace_path)
    try:
        content_model = JournalContent.model_validate(req.content)
    except Exception as exc:
        raise JournalContentShapeError(f"content shape invalid: {exc}") from exc
    if isinstance(req.spec_id, str) and req.spec_id.strip():
        try:
            spec = load_spec(canonical_ws, req.spec_id.strip())
        except JournalSpecNotFoundError as exc:
            raise OfficeFileNotFoundError(
                Path(req.spec_id), message=f"journal spec not found: {req.spec_id}"
            ) from exc
    elif isinstance(req.file_path, str) and req.file_path.strip():
        try:
            bounded = resolve_within(canonical_ws, Path(req.file_path))
        except Exception:
            raise OfficePathError(
                f"file_path escapes workspace: {req.file_path}",
                file_path=Path(req.file_path),
            )
        spec = parse_journal_spec(bounded)
    else:
        raise OfficePathError("spec_id or file_path required")

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
    """Validate a filled .docx against its spec."""
    from docx import Document

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
    if isinstance(req.spec_id, str) and req.spec_id.strip():
        try:
            spec = load_spec(canonical_ws, req.spec_id.strip())
        except JournalSpecNotFoundError as exc:
            raise OfficeFileNotFoundError(
                Path(req.spec_id), message=f"journal spec not found: {req.spec_id}"
            ) from exc
    else:
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
