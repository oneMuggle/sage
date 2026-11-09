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
from typing import Any, List, Literal, Optional
from zipfile import BadZipFile

from docx.opc.exceptions import PackageNotFoundError
from fastapi import APIRouter, HTTPException
<<<<<<< HEAD
from pydantic import BaseModel, Field

from backend.compat.win7.pydantic_compat import ConfigDict
=======
from pydantic import BaseModel, ConfigDict, Field

>>>>>>> origin/main
from backend.data.database import Database, get_database
from backend.office.docx_text import read_docx_text
from backend.office.errors import (
    OfficeFileNotFoundError,
    OfficeLLMError,
    OfficeParseError,
    OfficePathError,
    OfficeSizeLimitError,
)
from backend.office.excel import generate_xlsx
from backend.office.generate_service import (
    build_nl_prompt,
    next_iteration_filename,
    parse_llm_json_object,
    parse_llm_spec,
    to_excel_request,
    to_pdf_request,
    to_ppt_request,
    to_word_request,
)
from backend.office.generated_store import persist_generated_document
from backend.office.models import (
    OfficeDocType,
    OfficeDocumentSummary,
    PdfGenerateResult,
    TemplateLibraryEntry,
    WordTemplateFillResult,
    _constrained_list,
)
from backend.office.path_safety import resolve_within, validate_supported_filename
from backend.office.pdf import generate_pdf
from backend.office.ppt import generate_ppt
from backend.office.progress import track
from backend.office.storage import validate_workspace
from backend.office.template_library import instantiate_template, list_templates
from backend.office.word import generate_docx

# Pydantic v1 trees (release/win7) keep the routing stack behind a lazy
# re-import; on main (v2) this resolves eagerly as before. The module-level
# name stays patchable for tests either way.
try:
    from backend.orchestration.llm_factory import build_llm_client_from_settings
except ImportError:  # pragma: no cover — pydantic v1 without the v2 routing stack
    def build_llm_client_from_settings():  # type: ignore[misc]
        from backend.orchestration.llm_factory import (
            build_llm_client_from_settings as _factory,
        )

        return _factory()

# ruff: noqa: UP006, UP007, UP035

router = APIRouter(prefix="/office/generate", tags=["office"])

_DOC_TYPE_EXTENSIONS = {
    OfficeDocType.WORD: "docx",
    OfficeDocType.PPT: "pptx",
    OfficeDocType.EXCEL: "xlsx",
    OfficeDocType.PDF: "pdf",
}

# B4 — hard caps so a single runaway request cannot exhaust memory or the
# LLM context window. 50 MB keeps the source on disk; 100k chars keeps the
# reference payload below the typical prompt budget.
_MAX_SOURCE_BYTES = 50 * 1024 * 1024
_MAX_REFERENCE_CHARS = 100_000

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
        size = candidate.stat().st_size
        if size > _MAX_SOURCE_BYTES:
            raise OfficeSizeLimitError(size, _MAX_SOURCE_BYTES, file_path=candidate)
        try:
            texts.append(read_docx_text(candidate)[:_MAX_REFERENCE_CHARS])
        except (FileNotFoundError, PackageNotFoundError, BadZipFile) as exc:
            raise OfficeParseError(
                f"Failed to read reference .docx {raw_path}: {exc}",
                file_path=candidate,
            ) from exc
    return texts


async def _complete_or_llm_error(client: Any, prompt: str) -> str:
    """Call the LLM, translating any provider failure into OfficeLLMError (502)."""
    try:
        return await client.complete(prompt)
    except Exception as exc:  # noqa: BLE001 — re-raised as OfficeLLMError below
        raise OfficeLLMError("LLM 调用失败，请稍后重试") from exc


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
        llm_output = await _complete_or_llm_error(client, prompt)

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


class TemplateChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1)


class TemplateChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: Optional[str] = None
    workspace_path: str
    template_id: Optional[str] = None
    workspace_template: Optional[str] = None
    messages: _constrained_list(TemplateChatMessage, min_length=1)


def _resolve_template_entry(
    workspace: Path,
    template_id: Optional[str],
    workspace_template: Optional[str],
) -> TemplateLibraryEntry:
    """Find the library entry the chat will fill, mirroring instantiate rules."""
    if template_id and workspace_template:
        raise OfficePathError("template_id and workspace_template are mutually exclusive")
    entries = list_templates(str(workspace)).templates
    if template_id:
        for entry in entries:
            if entry.source == "builtin" and entry.id == template_id:
                return entry
        raise OfficeFileNotFoundError(Path(template_id))
    if workspace_template:
        for entry in entries:
            if entry.source == "workspace" and entry.filename == workspace_template:
                return entry
        raise OfficeFileNotFoundError(Path(workspace_template))
    raise OfficePathError("template_id or workspace_template is required")


def _build_template_chat_prompt(
    entry: TemplateLibraryEntry, messages: List[TemplateChatMessage]
) -> str:
    """Prompt the LLM to fill every placeholder from the conversation."""
    lines: List[str] = [
        f"你是一个模板填充助手。用户正在通过对话填写「{entry.name}」模板。",
        entry.description.strip(),
        "该模板包含以下占位符：",
    ]
    for placeholder in entry.placeholders:
        description = f"：{placeholder.description}" if placeholder.description else ""
        lines.append(f"- {placeholder.name}（{placeholder.type.value}{description}）")
    lines.extend(
        [
            "请根据对话内容为每个占位符生成合适的中文内容。",
            "只返回 JSON 对象，键为占位符名称，值为填充文本；不要任何解释。",
            "对话记录：",
        ]
    )
    for message in messages:
        speaker = "用户" if message.role == "user" else "助手"
        lines.append(f"{speaker}：{message.content}")
    return "\n".join(line for line in lines if line)


@router.post("/template-chat", response_model=NlGenerateResponse)
async def template_chat_endpoint(req: TemplateChatRequest) -> NlGenerateResponse:
    """Fill a library template from a chat conversation."""
    workspace = validate_workspace(Path(req.workspace_path))
    entry = _resolve_template_entry(workspace, req.template_id, req.workspace_template)
    if entry.doc_type is OfficeDocType.PDF:
        raise OfficePathError("PDF templates are not supported")

    prompt = _build_template_chat_prompt(entry, req.messages)
    client = build_llm_client_from_settings()
    if client is None:
        raise HTTPException(status_code=503, detail="LLM 客户端未配置")

    task_id = req.task_id or uuid.uuid4().hex
    with track(task_id, f"模板填充：{entry.name}") as prog:
        prog.report("调用 LLM 填充模板", 10)
        llm_output = await _complete_or_llm_error(client, prompt)

        prog.report("解析填充内容", 50)
        try:
            data = parse_llm_json_object(llm_output)
        except ValueError as exc:
            raise OfficeParseError(str(exc)) from exc

        prog.report("填充模板", 70)
        extension = _DOC_TYPE_EXTENSIONS[entry.doc_type]
        filename = validate_supported_filename(
            f"{_safe_filename_stem(entry.name)}.{extension}", entry.doc_type
        )
        result: WordTemplateFillResult = instantiate_template(
            str(workspace),
            template_id=req.template_id,
            workspace_template=req.workspace_template,
            filename=filename,
            data=data,
        )
        output_path = Path(result.output_path)

        prog.report("登记文档", 90)
        summary = persist_generated_document(
            _db().get_connection(),
            file_path=output_path,
            doc_type=entry.doc_type,
            workspace_path=str(workspace),
        )
        prog.report("完成", 100)

    return NlGenerateResponse(
        output_path=str(output_path),
        filename=output_path.name,
        file_size_bytes=output_path.stat().st_size,
        summary=summary,
    )


class IterateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: Optional[str] = None
    workspace_path: str
    source_path: str
    instruction: str = Field(..., min_length=1)


def _resolve_source_docx(workspace: Path, raw_path: str) -> Path:
    """Resolve an iterate source inside the workspace; .docx only."""
    source = resolve_within(workspace, Path(raw_path))
    if not source.is_file():
        raise OfficePathError(f"source_path is not a regular file: {raw_path}", file_path=source)
    if source.suffix.lower() != ".docx":
        raise OfficePathError(
            f"source_path only supports .docx files: {raw_path}", file_path=source
        )
    size = source.stat().st_size
    if size > _MAX_SOURCE_BYTES:
        raise OfficeSizeLimitError(size, _MAX_SOURCE_BYTES, file_path=source)
    return source


@router.post("/iterate", response_model=NlGenerateResponse)
async def iterate_endpoint(req: IterateRequest) -> NlGenerateResponse:
    """Rewrite an existing .docx according to an instruction."""
    workspace = validate_workspace(Path(req.workspace_path))
    source = _resolve_source_docx(workspace, req.source_path)
    try:
        source_text = read_docx_text(source)[:_MAX_REFERENCE_CHARS]
    except (FileNotFoundError, PackageNotFoundError, BadZipFile) as exc:
        raise OfficeParseError(
            f"Failed to read source .docx {req.source_path}: {exc}",
            file_path=source,
        ) from exc

    prompt = build_nl_prompt(
        instruction=("在原有文档基础上按修改要求输出完整的新版本。" f"修改要求：{req.instruction}"),
        doc_type="word",
        reference_texts=[source_text],
    )
    client = build_llm_client_from_settings()
    if client is None:
        raise HTTPException(status_code=503, detail="LLM 客户端未配置")

    task_id = req.task_id or uuid.uuid4().hex
    with track(task_id, "迭代文档") as prog:
        prog.report("调用 LLM 改写文档", 10)
        llm_output = await _complete_or_llm_error(client, prompt)

        prog.report("解析文档结构", 50)
        try:
            spec = parse_llm_spec(llm_output, "word")
        except ValueError as exc:
            raise OfficeParseError(str(exc)) from exc

        prog.report("生成新版本", 70)
        filename = validate_supported_filename(
            next_iteration_filename(source.name), OfficeDocType.WORD
        )
        output_path = _generate_document(spec, OfficeDocType.WORD, workspace, filename)

        prog.report("登记文档", 90)
        summary = persist_generated_document(
            _db().get_connection(),
            file_path=output_path,
            doc_type=OfficeDocType.WORD,
            workspace_path=str(workspace),
        )
        prog.report("完成", 100)

    return NlGenerateResponse(
        output_path=str(output_path),
        filename=output_path.name,
        file_size_bytes=output_path.stat().st_size,
        summary=summary,
    )
