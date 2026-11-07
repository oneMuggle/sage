"""Generate-workspace API routes (Office AI Workbench P3).

``POST /office/generate/nl`` turns a natural-language instruction into an
existing deterministic document generator call:

    instruction (+ optional .docx references)
        -> build_nl_prompt -> LLM JSON -> parse_llm_spec
        -> to_*_request -> generate_docx/ppt/xlsx/pdf
        -> persist_generated_document

Path containment and filename safety are delegated to
backend.office.path_safety and validate_workspace; parse failures surface
as OfficeParseError (422) through the shared handler.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.data.database import Database, get_database
from backend.office.docx_text import read_docx_text
from backend.office.errors import OfficeParseError, OfficePathError
from backend.office.excel import generate_xlsx
from backend.office.generate_service import (
    build_nl_prompt,
    parse_llm_spec,
    to_excel_request,
    to_pdf_request,
    to_ppt_request,
    to_word_request,
)
from backend.office.generated_store import persist_generated_document
from backend.office.models import OfficeDocType, OfficeDocumentSummary, PdfGenerateResult
from backend.office.path_safety import resolve_within, validate_supported_filename
from backend.office.pdf import generate_pdf
from backend.office.ppt import generate_ppt
from backend.office.progress import track
from backend.office.storage import validate_workspace
from backend.office.word import generate_docx
from backend.orchestration.llm_factory import build_llm_client_from_settings

# ruff: noqa: UP006, UP007, UP035

router = APIRouter(prefix="/office/generate", tags=["office"])

_DOC_TYPE_EXTENSIONS = {
    OfficeDocType.WORD: "docx",
    OfficeDocType.PPT: "pptx",
    OfficeDocType.EXCEL: "xlsx",
    OfficeDocType.PDF: "pdf",
}

_UNSAFE_FILENAME_CHARS = re.compile(r"[^\w \-]")
_MAX_FILENAME_STEM = 60


class NlGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: Optional[str] = None
    workspace_path: str
    instruction: str = Field(..., min_length=1)
    doc_type: str = Field(..., pattern="^(word|ppt|excel|pdf)$")
    reference_paths: Optional[List[str]] = None


class NlGenerateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_path: str
    filename: str
    file_size_bytes: int
    summary: OfficeDocumentSummary


def _db() -> Database:
    """Return the shared global Database instance (same pattern as office_routes)."""
    return get_database()


def _safe_filename_stem(title: Optional[str]) -> str:
    """Turn an LLM-supplied title into a filesystem-safe filename stem.

    Keeps word characters, spaces and hyphens; everything else (path
    separators, dots, quotes) becomes an underscore. Empty input falls
    back to ``generated``.
    """
    stem = _UNSAFE_FILENAME_CHARS.sub("_", (title or "").strip())
    stem = re.sub(r"_+", "_", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" ._-")
    return stem[:_MAX_FILENAME_STEM].strip(" ._-") or "generated"


def _collect_reference_texts(workspace: Path, reference_paths: Optional[List[str]]) -> List[str]:
    """Read .docx reference files, refusing anything outside the workspace."""
    if not reference_paths:
        return []
    texts: List[str] = []
    for raw_path in reference_paths:
        candidate = resolve_within(workspace, Path(raw_path))
        if not candidate.is_file():
            raise OfficePathError(
                f"reference_paths entry is not a regular file: {raw_path}",
                file_path=candidate,
            )
        if candidate.suffix.lower() != ".docx":
            raise OfficePathError(
                f"reference_paths only supports .docx files: {raw_path}",
                file_path=candidate,
            )
        texts.append(read_docx_text(candidate))
    return texts


def _generate_document(spec: dict, doc_type: OfficeDocType, workspace: Path, filename: str) -> Path:
    """Map the parsed LLM spec onto the matching deterministic generator."""
    workspace_str = str(workspace)
    if doc_type is OfficeDocType.WORD:
        return generate_docx(to_word_request(spec, workspace_path=workspace_str, filename=filename))
    if doc_type is OfficeDocType.PPT:
        return generate_ppt(to_ppt_request(spec, workspace_path=workspace_str, filename=filename))
    if doc_type is OfficeDocType.EXCEL:
        return generate_xlsx(
            to_excel_request(spec, workspace_path=workspace_str, filename=filename)
        )
    if doc_type is OfficeDocType.PDF:
        result: PdfGenerateResult = generate_pdf(
            to_pdf_request(spec, workspace_path=workspace_str, filename=filename)
        )
        return Path(result.output_path)
    raise ValueError(f"Unsupported doc_type: {doc_type}")


@router.post("/nl", response_model=NlGenerateResponse)
async def generate_nl_endpoint(req: NlGenerateRequest) -> NlGenerateResponse:
    """Generate a document from a natural-language instruction."""
    workspace = validate_workspace(Path(req.workspace_path))
    doc_type = OfficeDocType(req.doc_type)
    reference_texts = _collect_reference_texts(workspace, req.reference_paths)

    prompt = build_nl_prompt(
        instruction=req.instruction,
        doc_type=req.doc_type,
        reference_texts=reference_texts or None,
    )
    client = build_llm_client_from_settings()
    if client is None:
        raise HTTPException(status_code=503, detail="LLM 客户端未配置")

    task_id = req.task_id or uuid.uuid4().hex
    with track(task_id, f"生成 {doc_type.value}") as prog:
        prog.report("调用 LLM 生成文档结构", 10)
        llm_output = await client.complete(prompt)

        prog.report("解析文档结构", 50)
        try:
            spec = parse_llm_spec(llm_output, req.doc_type)
        except ValueError as exc:
            raise OfficeParseError(str(exc)) from exc

        prog.report("生成文档", 70)
        extension = _DOC_TYPE_EXTENSIONS[doc_type]
        filename = validate_supported_filename(
            f"{_safe_filename_stem(spec.get('title'))}.{extension}", doc_type
        )
        output_path = _generate_document(spec, doc_type, workspace, filename)

        prog.report("登记文档", 90)
        summary = persist_generated_document(
            _db().get_connection(),
            file_path=output_path,
            doc_type=doc_type,
            workspace_path=str(workspace),
        )
        prog.report("完成", 100)

    return NlGenerateResponse(
        output_path=str(output_path),
        filename=output_path.name,
        file_size_bytes=output_path.stat().st_size,
        summary=summary,
    )
