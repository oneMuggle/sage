"""Office document lifecycle, template library, preview, form & update routes (L5 split).

Extracted from ``backend/api/office_routes.py`` to keep route modules below the
800-line ceiling and remove ``office_routes.py`` from ``architecture-baseline.json``.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from backend.data.database import Database, get_database
from backend.office import progress as office_progress
from backend.office.apply_update import (
    OfficeDocUpdateRequest,
    OfficeDocUpdateResult,
    apply_doc_update,
)
from backend.office.diff_preview import (
    DiffPreviewResult,
    OfficeExportPdfRequest,
    OfficeUpdatePreviewRequest,
    preview_update,
)
from backend.office.errors import OfficeFileNotFoundError, OfficePathError
from backend.office.excel_recalc import (
    ExcelRecalcRequest,
    ExcelRecalcResult,
    refresh_formula_cache,
)
from backend.office.legacy_import import (
    LegacyImportRequest,
    LegacyImportResult,
    convert_legacy_import,
)
from backend.office.models import (
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentActionResponse,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
    OfficeSnapshotListResponse,
    OfficeTemplateInstantiateRequest,
    PdfFormFillRequest,
    PdfFormFillResult,
    PdfFormReadRequest,
    PdfFormReadResult,
    TemplateLibraryResponse,
    WordTemplateFillResult,
)
from backend.office.path_safety import resolve_within
from backend.office.pdf_forms import fill_pdf_form, read_pdf_form
from backend.office.pdf_to_word import PdfToWordRequest, PdfToWordResult, convert_pdf_to_word
from backend.office.ppt_template import (
    PptTemplateAnalyzeRequest,
    PptTemplateAnalyzeResult,
    PptTemplateFillRequest,
    PptTemplateFillResult,
    analyze_ppt_template,
    fill_ppt_template,
)
from backend.office.revision import stat_revision
from backend.office.storage import (
    archive_document,
    document_path,
    get_document,
    list_snapshots,
    restore_document,
    restore_from_snapshot,
    save_document,
    validate_workspace,
)
from backend.office.template_library import instantiate_template, list_templates

logger = logging.getLogger(__name__)

router = APIRouter()


def _db() -> Database:
    return get_database()


def _validate_file_in_workspace(file_path_str: str, workspace_path_str: str) -> Path:
    workspace = validate_workspace(workspace_path_str)
    target = resolve_within(workspace, Path(file_path_str))
    if not target.is_file():
        raise OfficePathError(
            f"file_path is not a regular file: {file_path_str}",
            file_path=target,
        )
    return target


def _build_summary_for_generated(
    *,
    file_path: Path,
    doc_type: OfficeDocType,
    workspace_path: str,
) -> OfficeDocumentSummary:
    now_ms = int(time.time() * 1000)
    canonical_workspace = str(Path(workspace_path).resolve())
    summary = OfficeDocumentSummary(
        id=file_path.parent.name,
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


@router.get("/doc/{doc_id}/snapshots/{snapshot_id}/diff", response_model=DiffPreviewResult)
def diff_snapshot_endpoint(doc_id: str, snapshot_id: str) -> DiffPreviewResult:
    """Round B P2: 对比快照与当前版本，返回结构化差异清单。

    快照=before，当前=after —— 「恢复到这份快照会失去/找回什么」一目了
    然。响应复用 DiffPreviewResult（前端红绿渲染与编辑预览共享）；快照
    缺失/解析失败折叠为 ``ok=False``（HTTP 200），未知 doc_id 仍走 404。
    Patch point：``backend.office.snapshot_diff.diff_snapshot``。
    """
    conn = _db().get_connection()
    doc = _require_document(conn, doc_id)
    from backend.office import snapshot_diff

    return snapshot_diff.diff_snapshot(doc, snapshot_id)


class OfficeTemplateThumbnailRequest(BaseModel):
    """POST /office/templates/thumbnail（Round C P5）。

    builtin 模板传 ``template_id``；workspace 模板传 ``workspace_template``
    （office/templates/ 下文件名，同 instantiate 的口径）。二者互斥。
    """

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    template_id: Optional[str] = None
    workspace_template: Optional[str] = None


@router.post("/templates/thumbnail")
def template_thumbnail_endpoint(req: OfficeTemplateThumbnailRequest) -> dict:
    """Round C P5: 模板首页 PNG 缩略图（PDF 管线 + PyMuPDF，磁盘缓存）。

    一切生成失败折叠为 ``ok=False``（HTTP 200）——缩略图是装饰性信息，
    前端静默降级。Patch point：
    ``backend.office.template_thumbnail.render_template_thumbnail``。
    """
    from backend.office import template_thumbnail
    from backend.office.template_library import (
        _BUILTIN_BY_ID,
        WORKSPACE_TEMPLATES_SUBDIR,
        builtin_template_path,
    )

    workspace = Path(req.workspace_path)
    if req.template_id:
        spec = _BUILTIN_BY_ID.get(req.template_id)
        if spec is None:
            return {"ok": False, "error": f"未知的内置模板: {req.template_id}"}
        source = builtin_template_path(spec)
        cache_key = "builtin:" + req.template_id
    elif req.workspace_template:
        # 文件名围栏：与 instantiate 同口径（拒绝路径分隔符/父目录）
        if any(sep in req.workspace_template for sep in ("/", "\\", "..")):
            return {"ok": False, "error": f"非法模板文件名: {req.workspace_template}"}
        source = workspace / WORKSPACE_TEMPLATES_SUBDIR / req.workspace_template
        try:
            mtime_ns = source.stat().st_mtime_ns
        except OSError:
            return {"ok": False, "error": f"模板文件不存在: {req.workspace_template}"}
        cache_key = f"ws:{req.workspace_template}|{mtime_ns}"
    else:
        return {"ok": False, "error": "template_id 与 workspace_template 必须传其一"}

    result = template_thumbnail.render_template_thumbnail(
        source, workspace, cache_key=cache_key
    )
    return result.model_dump(mode="json")


@router.post("/excel/recalc", response_model=ExcelRecalcResult)
def excel_recalc_endpoint(req: ExcelRecalcRequest) -> ExcelRecalcResult:
    """P2-C: 受管 .xlsx 公式缓存重算（soffice 就地刷新，重算前自动快照）。"""
    return refresh_formula_cache(req)


@router.post("/import/convert-legacy", response_model=LegacyImportResult)
def convert_legacy_import_endpoint(req: LegacyImportRequest) -> LegacyImportResult:
    """P1-C: 旧格式 (.doc/.xls/.ppt) 暂存文件 → 现代格式就地转换。"""
    return convert_legacy_import(req)


@router.post("/ppt/analyze-template", response_model=PptTemplateAnalyzeResult)
def ppt_analyze_template_endpoint(req: PptTemplateAnalyzeRequest) -> PptTemplateAnalyzeResult:
    """P5-A: 枚举 pptx 模板的母版版式与占位符（generate slides[].layout 引用）。"""
    return analyze_ppt_template(req)


@router.post("/ppt/fill-template", response_model=PptTemplateFillResult)
def ppt_fill_template_endpoint(req: PptTemplateFillRequest) -> PptTemplateFillResult:
    """P5-A: 以模板副本为基础按占位符填充，另存为新文件（模板原件不动）。"""
    return fill_ppt_template(req)


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
# Update preview + PDF export (Office parity batch 2 — Item 2.5)
# ──────────────────────────────────────────────────────────────────────


@router.post("/update/preview", response_model=DiffPreviewResult)
def preview_update_endpoint(req: OfficeUpdatePreviewRequest) -> DiffPreviewResult:
    """Dry-run update ops against a copy; the source file is never touched.

    File resolution mirrors office_update:
    - ``file_path`` → validated to lie inside ``workspace_path``;
    - ``doc_id``    → resolved via ``_require_document`` (404 when unknown)
      + ``document_path`` (managed dir layout), containment re-checked
      against the row's canonical ``workspace_path``.
    Invalid ops come back as ``DiffPreviewResult(ok=False, error=…)`` so
    the UI can show WHY the real update would fail (this is a preview).
    """
    if req.doc_id:
        doc = _require_document(_db().get_connection(), req.doc_id)
        managed = document_path(doc)
        if not managed.is_file():
            raise OfficeFileNotFoundError(managed)
        file_path = _validate_file_in_workspace(str(managed), doc.workspace_path)
    elif req.file_path:
        file_path = _validate_file_in_workspace(req.file_path, req.workspace_path)
    else:
        raise OfficePathError("file_path or doc_id is required")
    return preview_update(file_path, req.ops)


@router.post("/export-pdf")
def export_pdf_endpoint(req: OfficeExportPdfRequest):
    """Export a workspace document to PDF via backend.office.export_pdf.

    The ``export_pdf`` module is delivered by a parallel batch-2 agent, so
    the import is deferred to call time (keeps this router importable
    before that module lands). Because the route imports the *module
    object* and looks up the attribute on each call, the clean test patch
    point is ``backend.office.export_pdf.export_to_pdf``.
    """
    file_path = _validate_file_in_workspace(req.file_path, req.workspace_path)
    from backend.office import export_pdf

    with office_progress.track(req.task_id, "导出 PDF") as prog:
        prog.report("转换 PDF", 30)
        result = export_pdf.export_to_pdf(file_path, Path(req.workspace_path).resolve())
        prog.report("完成", 95)
    return result


@router.get("/capabilities")
def get_capabilities_endpoint(force: bool = False):
    """Round A P6: 探测本机 Office 环境能力（转换器 / 可选依赖）。

    前端 Office 页加载时调用一次，用于能力徽章与安装引导；
    ``force=true`` 跳过 30s 缓存强制重探（用户点「重新检测」）。
    Patch point（同 export-pdf 口径）：``backend.office.capabilities``
    模块对象上的 ``probe_capabilities``。
    """
    from backend.office import capabilities

    return capabilities.probe_capabilities(force=force)


@router.post("/pdf-preview")
def pdf_preview_endpoint(req: OfficeExportPdfRequest):
    """Round A P1: 高保真预览 —— docx/xlsx/pptx → 缓存 PDF → data URL。

    请求体复用 OfficeExportPdfRequest（workspace_path + file_path +
    可选 task_id）——语义相同：定位工作区内一份托管文档。区别在产物
    去向：导出写在源文件旁，预览写进 office/.preview-cache/ 并以
    data URL 返回。失败契约同 export：HTTP 200 + ``ok=False``。
    Patch point：``backend.office.pdf_preview.render_pdf_preview``。
    """
    file_path = _validate_file_in_workspace(req.file_path, req.workspace_path)
    from backend.office import pdf_preview

    with office_progress.track(req.task_id, "高保真预览") as prog:
        prog.report("转换 PDF", 30)
        result = pdf_preview.render_pdf_preview(
            file_path, Path(req.workspace_path).resolve()
        )
        prog.report("完成", 95)
    return result


@router.get("/progress/{task_id}")
def get_progress_endpoint(task_id: str):
    """P7: 查询 office 长任务进度（前端 500ms 轮询）。

    任务不存在（未开始 / 已结束）时返回 ``active: false`` 而非 404 ——
    轮询方把 active=false 视为任务完成信号，无需异常处理。
    """
    snap = office_progress.snapshot(task_id)
    if snap is None:
        return {"active": False, "stage": None, "percent": None, "title": None}
    return {"active": True, **snap}


# ──────────────────────────────────────────────────────────────────────
# Template library (batch 3 — Item 3.2)
# ──────────────────────────────────────────────────────────────────────


@router.get("/templates", response_model=TemplateLibraryResponse)
def list_templates_endpoint(workspace_path: Optional[str] = None) -> TemplateLibraryResponse:
    """List the builtin 中文办公模板 + workspace user templates.

    Builtin entries carry curated placeholder metadata and are instantiated by
    ``id``; workspace entries (``<workspace>/office/templates/*.docx``) are
    classified with the existing template scanner and instantiated by
    ``filename``. Broken workspace files are skipped with a logged warning.
    """
    return list_templates(workspace_path)


@router.post("/templates/instantiate", response_model=WordTemplateFillResult)
def instantiate_template_endpoint(
    req: OfficeTemplateInstantiateRequest,
) -> WordTemplateFillResult:
    """Instantiate a library template (word/excel/ppt) into the managed layout.

    Fills through the same machinery per doc_type (word: docxtpl with ZIP
    guards, dangerous-Jinja scan, SandboxedEnvironment, ≤10MB images; xlsx/
    pptx: {{marker}} replacement per Round-3 N2). The generated row is
    persisted here (like the other generate routes) so the document shows up
    in GET /documents — doc_type derived from the output extension so excel/
    ppt templates land in the right list.
    """
    with office_progress.track(req.task_id, "模板实例化") as prog:
        prog.report("填充模板", 30)
        result = instantiate_template(
            req.workspace_path,
            template_id=req.template_id,
            workspace_template=req.workspace_template,
            filename=req.filename,
            data=req.data,
            images=req.images,
        )
        prog.report("登记文档", 90)
        output_path = Path(result.output_path)
        ext = output_path.suffix.lstrip(".").lower()
        doc_type = {"docx": OfficeDocType.WORD, "xlsx": OfficeDocType.EXCEL, "pptx": OfficeDocType.PPT}.get(ext, OfficeDocType.WORD)
        _build_summary_for_generated(
            file_path=output_path,
            doc_type=doc_type,
            workspace_path=req.workspace_path,
        )
    return result


# ──────────────────────────────────────────────────────────────────────
# Apply update (Office parity round 2 — R1: edit-preview dialog 的「应用」)
# ──────────────────────────────────────────────────────────────────────


@router.post("/doc/{doc_id}/update", response_model=OfficeDocUpdateResult)
def update_document_endpoint(
    doc_id: str, req: OfficeDocUpdateRequest
) -> OfficeDocUpdateResult:
    """Apply update ops to a managed document in place.

    Semantics mirror the office_update tool path: pre-edit snapshot first
    (best-effort), then the all-or-nothing editor (a rejected op leaves the
    file untouched), then the row refresh (status → edited, fresh
    ``updated_at`` / ``file_size_bytes``) and a best-effort self-check
    readback of the saved file.

    F1 (P0-A): ``expected_revision`` binds this write to the exact bytes the
    caller previewed — a mismatch is a 409 with the file untouched, not a
    silent overwrite of someone else's change. ``idempotency_key`` makes a
    retried apply replay the first outcome instead of appending twice.

    Errors: unknown doc id → 404 (``OfficeFileNotFoundError``); missing
    managed file → 404; stale revision → 409
    (``OfficeRevisionConflictError``); rejected ops → 422
    (``OfficeOpRejectedError``, per-op failure info in ``message``);
    file-level save failure → 500 (``OfficeEditError``). All mapped by the
    registered OfficeError handler.
    """
    conn = _db().get_connection()
    doc = _require_document(conn, doc_id)
    return apply_doc_update(
        conn,
        doc,
        req.ops,
        expected_revision=req.expected_revision,
        idempotency_key=req.idempotency_key,
    )


@router.get("/doc/{doc_id}/revision")
def get_document_revision_endpoint(doc_id: str) -> Dict[str, Any]:
    """Current content revision of a managed document (F1/F2 read side).

    The preview UI keys its caches on this value instead of
    ``id:file_size_bytes``, which collides whenever an edit keeps the file
    the same size. Hashing is memoized on ``(path, size, mtime_ns)``, so
    polling it on every document switch stays cheap.
    """
    conn = _db().get_connection()
    doc = _require_document(conn, doc_id)
    managed = document_path(doc)
    if not managed.is_file():
        raise OfficeFileNotFoundError(managed)
    stat = managed.stat()
    return {
        "doc_id": doc.id,
        "revision": stat_revision(managed),
        "size_bytes": stat.st_size,
        "mtime_ms": int(stat.st_mtime * 1000),
    }


# ──────────────────────────────────────────────────────────────────────
# PDF → Word conversion + self-check history (Office parity round 3 — N3/N4)
# ──────────────────────────────────────────────────────────────────────


@router.post("/pdf/to-word", response_model=PdfToWordResult)
def pdf_to_word_endpoint(req: PdfToWordRequest) -> PdfToWordResult:
    """Convert a text-layer PDF into a managed .docx (round-3 N3).

    The service function (:func:`backend.office.pdf_to_word.convert_pdf_to_word`)
    never raises and returns ``PdfToWordResult(ok=False, error=...)`` on any
    failure; this handler only adds the boundary checks that map to HTTP
    errors (400/404 via the OfficeError handler) and the persistence step:

    - ``file_path`` must lie inside ``workspace_path`` (path traversal → 400);
    - ``source_doc_id``, when given, must exist (unknown id → 404) and becomes
      the generated Word row's ``derived_from`` lineage.
    """
    logger.info("Converting PDF to Word: %s", req.file_path)
    file_path = _validate_file_in_workspace(req.file_path, req.workspace_path)
    if req.source_doc_id:
        _require_document(_db().get_connection(), req.source_doc_id)
    result = convert_pdf_to_word(
        file_path,
        Path(req.workspace_path).resolve(),
        req.out_filename or "",
    )
    if result.ok:
        # Persist the generated row like the other generate routes.
        # _build_summary_for_generated() takes no derived_from (its existing
        # call sites don't track lineage), so the lineage is attached after
        # the helper ran and the row is re-saved (INSERT OR REPLACE keeps
        # this a plain overwrite of the row we just created).
        summary = _build_summary_for_generated(
            file_path=Path(result.output_path),
            doc_type=OfficeDocType.WORD,
            workspace_path=req.workspace_path,
        )
        if req.source_doc_id:
            summary.derived_from = req.source_doc_id
            save_document(_db().get_connection(), summary)
    return result


@router.get("/doc/{doc_id}/self-checks")
def list_self_checks_endpoint(doc_id: str, limit: int = 50) -> dict:
    """List a document's self-check verification history (round-3 N4).

    Response shape is the fixed frontend contract:
    ``{"items": [{id, doc_id, action, ok, summary, created_at}, ...], "total"}``
    — newest first, ``ok`` a bool, ``summary`` the deserialized readback dict.
    ``total`` mirrors ``len(items)`` (same convention as the snapshots
    endpoint) because the backend list query has no pagination offset.

    The ``backend.office.selfcheck_history`` module is imported lazily at
    call time (same parallel-delivery pattern as ``export_pdf``), keeping
    this router importable even if the history module is absent.
    """
    conn = _db().get_connection()
    _require_document(conn, doc_id)
    # Clamp the page size: at least 1 row, never more than 500 per call.
    clamped_limit = max(1, min(limit, 500))
    from backend.office.selfcheck_history import list_for_document

    items = list_for_document(conn, doc_id, limit=clamped_limit)
    return {"items": items, "total": len(items)}

__all__ = [
    "OfficeTemplateThumbnailRequest",
    "archive_document_endpoint",
    "convert_legacy_import_endpoint",
    "diff_snapshot_endpoint",
    "excel_recalc_endpoint",
    "export_pdf_endpoint",
    "fill_pdf_form_endpoint",
    "get_capabilities_endpoint",
    "get_document_revision_endpoint",
    "get_progress_endpoint",
    "instantiate_template_endpoint",
    "list_self_checks_endpoint",
    "list_snapshots_endpoint",
    "list_templates_endpoint",
    "pdf_preview_endpoint",
    "pdf_to_word_endpoint",
    "ppt_analyze_template_endpoint",
    "ppt_fill_template_endpoint",
    "preview_update_endpoint",
    "read_pdf_form_endpoint",
    "restore_document_endpoint",
    "restore_snapshot_endpoint",
    "router",
    "template_thumbnail_endpoint",
    "update_document_endpoint",
]
