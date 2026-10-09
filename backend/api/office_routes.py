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

import base64
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from backend.data.database import Database, get_database
from backend.office import progress as office_progress
from backend.office.bibtex import parse_bibtex
from backend.office.errors import (
    OfficeError,
    OfficePathError,
    OfficeSizeLimitError,
    office_error_to_http_status,
)
from backend.office.excel import generate_xlsx, read_xlsx
from backend.office.models import (
    BibTeXParseRequest,
    BibTeXParseResponse,
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
    PdfDataRequest,
    PdfDataResult,
    PdfGenerateRequest,
    PdfGenerateResult,
    PdfReadRequest,
    PdfReadResult,
    WordLintRequest,
    WordLintResult,
    WordRepairRequest,
    WordRepairResult,
    WordTemplateAnalysis,
    WordTemplateAnalyzeRequest,
    WordTemplateFillRequest,
    WordTemplateFillResult,
)
from backend.office.path_safety import resolve_within
from backend.office.pdf import MAX_PDF_SIZE, generate_pdf, read_pdf
from backend.office.ppt import generate_ppt, read_ppt
from backend.office.storage import (
    delete_document,
    get_document,
    list_documents,
    save_document,
    validate_workspace,
)
from backend.office.word import generate_docx, read_docx
from backend.office.word_lint import lint_docx
from backend.office.word_repair import repair_docx
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
# Generate endpoints (Phase 1.4 step 19, plan §4.1.4)
# ──────────────────────────────────────────────────────────────────────


@router.post("/ppt/generate")
def generate_ppt_endpoint(req: OfficePptGenerateRequest) -> dict:
    """Generate a .pptx file from structured input.

    CRITICAL FIX: now also calls save_document() to persist the generated
    document in the office_documents table so it appears in the list API.
    """
    with office_progress.track(req.task_id, "生成 PPT") as prog:
        prog.report("生成文档", 30)
        output_path = generate_ppt(req)
        prog.report("登记文档", 90)
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
    with office_progress.track(req.task_id, "生成 Word") as prog:
        prog.report("生成文档", 30)
        output_path = generate_docx(req)
        prog.report("登记文档", 90)
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


@router.post("/word/parse-bibtex")
def parse_bibtex_endpoint(req: BibTeXParseRequest) -> BibTeXParseResponse:
    """解析 BibTeX 文本为结构化参考文献（Round 9 引用体系）。

    纯文本解析，零落盘/零外发；条目可直接传入 /word/generate 的
    ``references``。解析失败由全局 OfficeParseError → 422 信封处理。
    """
    references = parse_bibtex(req.text)
    return BibTeXParseResponse(count=len(references), references=references)


@router.post("/word/lint")
def lint_word_endpoint(req: WordLintRequest) -> WordLintResult:
    """对照 FormatSpec 校验 .docx（Round 10 格式 Linter）。

    纯回读；file_path 经工作区围栏（resolve_within）把守，5MB 上限与
    读取端点一致。解析失败走全局 OfficeParseError → 422 信封。
    """
    file_path = _validate_file_in_workspace(req.file_path, req.workspace_path)
    _check_size_limit(file_path, req.max_size_bytes)
    return lint_docx(file_path, req.format_spec)


@router.post("/word/repair")
def repair_word_endpoint(req: WordRepairRequest) -> WordRepairResult:
    """对照 FormatSpec 自动修复 .docx 可机械修复违规（Round 12）。

    默认写 ``<stem>-repaired.docx`` 新文件；overwrite=true 时原子替换
    原文件。修复后自动复检，remaining 携带未消除违规（如语义类
    citation/coverage）。围栏与尺寸上限同 lint 端点。
    """
    file_path = _validate_file_in_workspace(req.file_path, req.workspace_path)
    _check_size_limit(file_path, req.max_size_bytes)
    return repair_docx(file_path, req.format_spec, overwrite=req.overwrite)


@router.post("/excel/generate")
def generate_excel_endpoint(req: OfficeExcelGenerateRequest) -> dict:
    """Generate a .xlsx file from structured input."""
    with office_progress.track(req.task_id, "生成 Excel") as prog:
        prog.report("生成文档", 30)
        output_path = generate_xlsx(req)
        prog.report("登记文档", 90)
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


#: P2-B (office-p2b): docx 原文 base64 上限（docx-preview 原生渲染用，
#: 与 PDF 原文口径一致）
MAX_DOCX_DATA_BYTES = 20_000_000


@router.post("/word/data", response_model=PdfDataResult)
def word_data_endpoint(req: PdfDataRequest) -> PdfDataResult:
    """受管 docx 原文 base64（/office 页 docx-preview 原生渲染用）。

    失败契约同 /pdf/data：预期内失败返回 ``ok=False``，不抛 HTTP 异常。
    """
    try:
        file_path = _validate_file_in_workspace(req.file_path, req.workspace_path)
        if file_path.stat().st_size > MAX_DOCX_DATA_BYTES:
            return PdfDataResult(
                ok=False, error="文件超过 20MB 预览上限，请在文件管理器中查看"
            )
        data = base64.b64encode(file_path.read_bytes()).decode("ascii")
        return PdfDataResult(
            ok=True, data_url=f"data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,{data}"
        )
    except OfficeError as exc:
        logger.warning("word/data preview rejected: %s", exc)
        return PdfDataResult(ok=False, error="文件不可预览（路径无效或超出工作区）")
    except OSError:
        logger.warning("word/data preview failed to read: %s", req.file_path)
        return PdfDataResult(ok=False, error="文件读取失败")


#: F3 (office-p0): 原文预览上限 —— 与 chat 产物侧 artifact_reader.MAX_PDF_BYTES
#: 同口径（过大 PDF base64 化既撑爆响应也拖垮 renderer）。
MAX_PDF_DATA_BYTES = 20_000_000


@router.post("/pdf/data", response_model=PdfDataResult)
def pdf_data_endpoint(req: PdfDataRequest) -> PdfDataResult:
    """受管 PDF 原文 base64 预览（/office 页面"原文预览"开关）。

    返回 ``data:application/pdf`` URL，前端 iframe 交给 Chromium 内置
    viewer 渲染——与聊天产物侧同一条高保真通路。预期内失败（越界 /
    超限 / 不可读）返回 ``ok=False``，不抛 HTTP 异常，前端回落结构化
    页卡片视图。路径校验复用 ``_validate_file_in_workspace``（renderer
    IPC 与任意本地文件读之间的唯一屏障）。
    """
    try:
        file_path = _validate_file_in_workspace(req.file_path, req.workspace_path)
        if file_path.stat().st_size > MAX_PDF_DATA_BYTES:
            return PdfDataResult(
                ok=False, error="PDF 超过 20MB 预览上限，请在文件管理器中查看"
            )
        data = base64.b64encode(file_path.read_bytes()).decode("ascii")
        return PdfDataResult(ok=True, data_url=f"data:application/pdf;base64,{data}")
    except OfficeError as exc:
        # 泛化错误信息防路径泄露（与 pdf.py 的错误口径一致）。
        logger.warning("pdf/data preview rejected: %s", exc)
        return PdfDataResult(ok=False, error="文件不可预览（路径无效或超出工作区）")
    except OSError:
        logger.warning("pdf/data preview failed to read: %s", req.file_path)
        return PdfDataResult(ok=False, error="文件读取失败")


@router.post("/pdf/generate", response_model=PdfGenerateResult)
def generate_pdf_endpoint(req: PdfGenerateRequest) -> PdfGenerateResult:
    """Generate a PDF from structured data.

    Service function handles workspace validation and output path safety.
    """
    with office_progress.track(req.task_id, "生成 PDF") as prog:
        prog.report("生成文档", 40)
        result = generate_pdf(req)
        prog.report("完成", 95)
    return result


# ──────────────────────────────────────────────────────────────────────
# Lifecycle, preview, template library, form & update routes (L5 split)
# ──────────────────────────────────────────────────────────────────────

from backend.api.office_lifecycle_routes import (  # noqa: E402
    OfficeTemplateThumbnailRequest,
    archive_document_endpoint,
    convert_legacy_import_endpoint,
    diff_snapshot_endpoint,
    excel_recalc_endpoint,
    export_pdf_endpoint,
    fill_pdf_form_endpoint,
    get_capabilities_endpoint,
    get_document_revision_endpoint,
    get_progress_endpoint,
    instantiate_template_endpoint,
    list_self_checks_endpoint,
    list_snapshots_endpoint,
    list_templates_endpoint,
    pdf_preview_endpoint,
    pdf_to_word_endpoint,
    ppt_analyze_template_endpoint,
    ppt_fill_template_endpoint,
    preview_update_endpoint,
    read_pdf_form_endpoint,
    restore_document_endpoint,
    restore_snapshot_endpoint,
    router as _lifecycle_router,
    template_thumbnail_endpoint,
    update_document_endpoint,
)

router.include_router(_lifecycle_router)


# ──────────────────────────────────────────────────────────────────────
# Journal template subsystem (extracted to office_journal_routes.py for L5)
# ──────────────────────────────────────────────────────────────────────

from backend.api.office_journal_routes import (  # noqa: E402
    OfficeJournalFillRequest,
    OfficeJournalFillResponse,
    OfficeJournalParseRequest,
    OfficeJournalParseResponse,
    OfficeJournalSpecDetailResponse,
    OfficeJournalSpecListResponse,
    OfficeJournalSpecSummary,
    OfficeJournalValidateRequest,
    OfficeJournalValidateResponse,
    fill_journal_from_content_endpoint,
    get_journal_spec_endpoint,
    list_journal_specs_endpoint,
    parse_journal_template_endpoint,
    router as _journal_router,
    validate_journal_endpoint,
)

router.include_router(_journal_router)

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
    # Office parity batch 2 (Item 2.5): update preview + PDF export
    "preview_update_endpoint",
    "export_pdf_endpoint",
    # Office parity batch 3 (Item 3.2): template library
    "list_templates_endpoint",
    "instantiate_template_endpoint",
    # Office parity round 2 (R1): apply update ops to a managed document
    "update_document_endpoint",
    "OfficeTemplateThumbnailRequest",
    "convert_legacy_import_endpoint",
    "diff_snapshot_endpoint",
    "excel_recalc_endpoint",
    "get_capabilities_endpoint",
    "get_document_revision_endpoint",
    "get_progress_endpoint",
    "pdf_preview_endpoint",
    "ppt_analyze_template_endpoint",
    "ppt_fill_template_endpoint",
    "template_thumbnail_endpoint",
    # Office parity round 3 (N3): PDF → Word text-level conversion
    "pdf_to_word_endpoint",
    # Office parity round 3 (N4): self-check verification history
    "list_self_checks_endpoint",
    # 2026-09-10 journal template subsystem
    "OfficeJournalFillRequest",
    "OfficeJournalFillResponse",
    "OfficeJournalParseRequest",
    "OfficeJournalParseResponse",
    "OfficeJournalSpecDetailResponse",
    "OfficeJournalSpecListResponse",
    "OfficeJournalSpecSummary",
    "OfficeJournalValidateRequest",
    "OfficeJournalValidateResponse",
    "parse_journal_template_endpoint",
    "list_journal_specs_endpoint",
    "get_journal_spec_endpoint",
    "fill_journal_from_content_endpoint",
    "validate_journal_endpoint",
]
