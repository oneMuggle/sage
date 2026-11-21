"""Render & Verify (M1): render Office documents to PDF and check the result.

``word_render_audit`` already verifies a rendered Word PDF (page size,
margins, fonts, page numbers).  This module generalizes that pipeline for
the three editable formats and adds format-agnostic checks that only make
sense on the *rendered* artifact:

- blank pages (no text, no images, no vector drawings)
- content overflowing the page box
- page thumbnails for the workbench result card

Failure contract mirrors ``export_to_pdf``: a missing converter or an
unreadable PDF degrades to ``status="degraded"`` with warnings instead of
raising, so the caller can always show the structural result.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Callable, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .errors import OfficeFileNotFoundError, OfficeParseError
from .export_pdf import ExportPdfResult, export_to_pdf
from .path_safety import resolve_within
from .storage import validate_workspace
from .word_render_audit import audit_rendered_pdf

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_VERIFY_BYTES",
    "RenderVerifyIssue",
    "RenderVerifyRequest",
    "RenderVerifyResult",
    "RenderVerifySummary",
    "verify_document",
    "verify_for_tool",
    "verify_rendered_pdf",
]

#: 渲染校验的源文件上限（与 Word 渲染审计/Office 编辑上限同口径）。
MAX_VERIFY_BYTES = 50 * 1024 * 1024

#: 单次校验最多检查的页数（防止超长文档拖垮转换/检查）。
MAX_VERIFY_PAGES = 2000

#: 溢出判定容差（pt）：小于该值的 bbox 越界视为正常裁切。
_OVERFLOW_TOLERANCE_PT = 2.0

_SUPPORTED_SUFFIXES = (".docx", ".xlsx", ".pptx")

#: word_render_audit 的 category 到通用 category 的映射。
_CATEGORY_MAP = {"page": "page_size"}


class RenderVerifyIssue(BaseModel):
    """A single rendered-artifact finding."""

    model_config = ConfigDict(extra="forbid")

    page_index: Optional[int] = Field(default=None, description="0 基页号；文档级问题为 None")
    category: str = Field(description="page_size/margin/font/page_number/blank_page/content_overflow/empty_document")
    severity: Literal["error", "warning", "info"]
    message: str
    expected: Optional[str] = None
    actual: Optional[str] = None


class RenderVerifySummary(BaseModel):
    """Per-document page statistics."""

    model_config = ConfigDict(extra="forbid")

    pages: int = Field(default=0, description="PDF 实际页数")
    inspected_pages: int = Field(default=0, description="实际检查的页数（受 max_pages 限制）")
    text_pages: int = Field(default=0, description="含可提取文本的页数")
    blank_pages: int = Field(default=0, description="空白页数（无文本/图片/矢量绘制）")
    image_pages: int = Field(default=0, description="含位图的页数")


class RenderVerifyRequest(BaseModel):
    """REST/tool request: locate a managed document and describe expectations."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str = Field(description="工作区路径")
    file_path: str = Field(description="工作区内 .docx/.xlsx/.pptx 路径")
    expected_size: Optional[str] = Field(
        default=None, description="期望页面尺寸：A4/LETTER；None 时只校验页间一致性"
    )
    margins_cm: Optional[Dict[str, float]] = Field(
        default=None, description="四边页边距期望值（cm）：top/bottom/left/right"
    )
    allowed_fonts: Optional[List[str]] = Field(
        default=None, description="允许的字体集合；None 时跳过字体检查"
    )
    require_page_number: bool = Field(default=False, description="是否要求每页底部有页码")
    margin_tolerance_cm: float = Field(default=0.3, ge=0, le=5)
    page_number_band: float = Field(default=0.15, gt=0, le=0.5)
    max_pages: int = Field(default=200, ge=1, le=MAX_VERIFY_PAGES)
    thumbnail_pages: int = Field(default=0, ge=0, le=5, description="为前 N 页生成 JPEG 缩略图")
    thumbnail_dpi: int = Field(default=96, ge=72, le=200)
    timeout_seconds: int = Field(default=120, ge=1, le=600)


class RenderVerifyResult(BaseModel):
    """Verification outcome: passed / degraded (no render) / failed."""

    model_config = ConfigDict(extra="forbid")

    ok: bool = Field(description="无 error 级问题（未渲染时为 True，与既有审计契约一致）")
    status: Literal["passed", "degraded", "failed"]
    source_path: str
    rendered: bool
    method: Optional[Literal["libreoffice", "word_com"]] = None
    page_count: int = 0
    issues: List[RenderVerifyIssue] = Field(default_factory=list)
    warnings: List[Dict[str, str]] = Field(default_factory=list)
    summary: RenderVerifySummary = Field(default_factory=RenderVerifySummary)
    thumbnails: List[str] = Field(default_factory=list)


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.name


def _decode_jpeg_data_url(pixmap: object) -> str:
    payload = pixmap.tobytes("jpeg", jpg_quality=70)  # type: ignore[attr-defined]
    return "data:image/jpeg;base64," + base64.b64encode(payload).decode("ascii")


def verify_rendered_pdf(
    pdf_path: Path,
    *,
    expected_size: Optional[str] = None,
    margins_cm: Optional[Dict[str, float]] = None,
    allowed_fonts: Optional[List[str]] = None,
    require_page_number: bool = False,
    margin_tolerance_cm: float = 0.3,
    page_number_band: float = 0.15,
    max_pages: int = 200,
    thumbnail_pages: int = 0,
    thumbnail_dpi: int = 96,
) -> Tuple[List[RenderVerifyIssue], List[Dict[str, str]], RenderVerifySummary, List[str]]:
    """Inspect a rendered PDF; returns (issues, warnings, summary, thumbnails).

    Reuses :func:`word_render_audit.audit_rendered_pdf` for the page/margin/
    font/page-number geometry and adds blank-page/overflow checks.
    """
    try:
        import fitz  # noqa: PLC0415 — heavy import, call-time only
    except Exception as exc:  # noqa: BLE001
        raise OfficeParseError(f"PyMuPDF 不可用: {exc}") from exc

    inspected_limit = max(1, int(max_pages))
    legacy_issues, legacy_warnings, total_pages = audit_rendered_pdf(
        Path(pdf_path),
        expected_size=expected_size,
        margins_cm=margins_cm,
        allowed_fonts=allowed_fonts,
        require_page_number=require_page_number,
        margin_tolerance_cm=margin_tolerance_cm,
        page_number_band=page_number_band,
        max_pages=inspected_limit,
    )

    issues: List[RenderVerifyIssue] = [
        RenderVerifyIssue(
            page_index=issue.page_index,
            category=_CATEGORY_MAP.get(issue.category, issue.category),
            severity=issue.severity,
            message=issue.message,
            expected=issue.expected,
            actual=issue.actual,
        )
        for issue in legacy_issues
    ]
    warnings: List[Dict[str, str]] = list(legacy_warnings)

    inspected = min(total_pages, inspected_limit)
    if total_pages > inspected_limit:
        warnings.append(
            {
                "code": "page_limit_truncated",
                "message": f"文档共 {total_pages} 页，仅检查前 {inspected_limit} 页",
            }
        )

    summary = RenderVerifySummary(pages=total_pages, inspected_pages=inspected)
    thumbnails: List[str] = []

    document = fitz.open(str(pdf_path))
    try:
        if total_pages == 0:
            issues.append(
                RenderVerifyIssue(
                    category="empty_document",
                    severity="error",
                    message="PDF 没有页面",
                )
            )
        for index in range(inspected):
            page = document.load_page(index)
            rect = page.rect
            text = page.get_text("text").strip()
            images = page.get_images(full=True)
            drawings = page.get_drawings()
            if text:
                summary.text_pages += 1
            if images:
                summary.image_pages += 1

            is_blank = not text and not images and not drawings
            if is_blank:
                summary.blank_pages += 1
                issues.append(
                    RenderVerifyIssue(
                        page_index=index,
                        category="blank_page",
                        severity="warning",
                        message=f"第 {index + 1} 页为空白页",
                    )
                )

            overflow = False
            for block in page.get_text("dict").get("blocks", []):
                bbox = block.get("bbox")
                if not bbox or len(bbox) < 4:
                    continue
                if (
                    bbox[0] < -_OVERFLOW_TOLERANCE_PT
                    or bbox[1] < -_OVERFLOW_TOLERANCE_PT
                    or bbox[2] > rect.width + _OVERFLOW_TOLERANCE_PT
                    or bbox[3] > rect.height + _OVERFLOW_TOLERANCE_PT
                ):
                    overflow = True
                    break
            if overflow:
                issues.append(
                    RenderVerifyIssue(
                        page_index=index,
                        category="content_overflow",
                        severity="warning",
                        message=f"第 {index + 1} 页有内容越出页面边界",
                        actual="越界",
                    )
                )

            if len(thumbnails) < max(0, int(thumbnail_pages)):
                dpi = max(72, min(200, int(thumbnail_dpi)))
                thumbnails.append(_decode_jpeg_data_url(page.get_pixmap(dpi=dpi)))
    finally:
        document.close()

    return issues, warnings, summary, thumbnails


def verify_document(
    request: RenderVerifyRequest,
    *,
    export_fn: Optional[Callable[..., ExportPdfResult]] = None,
) -> RenderVerifyResult:
    """Render a managed docx/xlsx/pptx and verify the rendered PDF."""
    workspace = validate_workspace(Path(request.workspace_path))
    source = resolve_within(workspace, Path(request.file_path))
    if not source.is_file():
        raise OfficeFileNotFoundError(source)
    if source.suffix.lower() not in _SUPPORTED_SUFFIXES:
        raise OfficeParseError("渲染校验仅支持 .docx/.xlsx/.pptx")
    if source.stat().st_size > MAX_VERIFY_BYTES:
        raise OfficeParseError(
            f"文件超过 {MAX_VERIFY_BYTES // (1024 * 1024)}MiB 渲染校验上限"
        )

    exporter = export_fn or export_to_pdf
    export = exporter(source, workspace, timeout_seconds=request.timeout_seconds)
    source_rel = _rel(source, workspace)

    if not export.ok or not export.output_path:
        return RenderVerifyResult(
            ok=True,
            status="degraded",
            source_path=source_rel,
            rendered=False,
            method=None,
            warnings=[
                {
                    "code": "render_unavailable",
                    "message": export.error or "未找到可用的 PDF 转换器，渲染校验未执行",
                }
            ],
        )

    try:
        issues, warnings, summary, thumbnails = verify_rendered_pdf(
            Path(export.output_path),
            expected_size=request.expected_size,
            margins_cm=request.margins_cm,
            allowed_fonts=request.allowed_fonts,
            require_page_number=request.require_page_number,
            margin_tolerance_cm=request.margin_tolerance_cm,
            page_number_band=request.page_number_band,
            max_pages=request.max_pages,
            thumbnail_pages=request.thumbnail_pages,
            thumbnail_dpi=request.thumbnail_dpi,
        )
    except OfficeParseError as exc:
        return RenderVerifyResult(
            ok=True,
            status="degraded",
            source_path=source_rel,
            rendered=True,
            method=export.method,
            warnings=[
                {"code": "render_check_failed", "message": f"PDF 已生成但检查失败: {exc}"}
            ],
        )
    except Exception as exc:  # noqa: BLE001 — 契约：检查失败降级，不向路由层抛未知异常
        logger.exception("render verify crashed unexpectedly")
        return RenderVerifyResult(
            ok=True,
            status="degraded",
            source_path=source_rel,
            rendered=True,
            method=export.method,
            warnings=[
                {
                    "code": "render_check_failed",
                    "message": f"PDF 已生成但检查失败（{type(exc).__name__}，详见日志）",
                }
            ],
        )

    status: Literal["passed", "failed"] = (
        "failed" if any(issue.severity == "error" for issue in issues) else "passed"
    )
    return RenderVerifyResult(
        ok=status != "failed",
        status=status,
        source_path=source_rel,
        rendered=True,
        method=export.method,
        page_count=summary.pages,
        issues=issues,
        warnings=warnings,
        summary=summary,
        thumbnails=thumbnails,
    )


def _compact_result(result: RenderVerifyResult) -> Dict[str, object]:
    """Tool-facing summary: no paths, no thumbnails, issues capped."""

    errors = sum(1 for issue in result.issues if issue.severity == "error")
    warnings_count = sum(1 for issue in result.issues if issue.severity == "warning")
    payload: Dict[str, object] = {
        "status": result.status,
        "rendered": result.rendered,
        "method": result.method,
        "page_count": result.page_count,
        "issue_count": len(result.issues),
        "error_count": errors,
        "warning_count": warnings_count,
        "summary": result.summary.model_dump(),
        "warnings": [warning.get("code") for warning in result.warnings],
        "issues": [issue.model_dump() for issue in result.issues[:10]],
    }
    if len(result.issues) > 10:
        payload["issues_truncated"] = True
    return payload


def verify_for_tool(
    *,
    file_path: Path,
    workspace: Path,
    mode: str = "auto",
) -> Optional[Dict[str, object]]:
    """Run render & verify for a tool result, best-effort.

    ``mode="off"`` returns ``None`` (no key attached).  ``auto`` skips the
    render when no PDF converter is available (avoids slowing every create
    on converter-less machines) but still reports the degraded state.
    """
    normalized = str(mode or "auto").strip().lower()
    if normalized == "off":
        return None

    from .capabilities import probe_capabilities

    try:
        capabilities = probe_capabilities()
        available = bool(capabilities.pdf_export_available)
    except Exception:  # noqa: BLE001 — 能力探测失败按不可用降级
        available = False
    if not available:
        return {
            "status": "degraded",
            "rendered": False,
            "reason": "render_unavailable",
        }

    try:
        result = verify_document(
            RenderVerifyRequest(
                workspace_path=str(workspace),
                file_path=str(file_path),
            )
        )
    except Exception as exc:  # noqa: BLE001 — 工具结果绝不因校验失败而失败
        logger.warning("render verify (tool) failed: %s", type(exc).__name__)
        return {
            "status": "degraded",
            "rendered": False,
            "reason": "verify_failed",
        }
    return _compact_result(result)
