"""Rendered Word audit (M5a): DOCX -> PDF page/margin/font checks.

Uses the existing local converter pipeline (LibreOffice / Word COM) via
``export_to_pdf`` and reads the resulting PDF with PyMuPDF. When no
converter is available the result is ``rendered=False`` with a warning —
the caller can still use the structural rule-pack audit.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .errors import OfficeFileNotFoundError, OfficeParseError
from .export_pdf import ExportPdfResult, export_to_pdf
from .word_rulepack_models import WordRenderAuditResult, WordRenderIssue

_PT_TO_MM = 25.4 / 72.0
_PT_TO_CM = 2.54 / 72.0
_PAGE_SIZES_MM = {
    "A4": (210.0, 297.0),
    "LETTER": (215.9, 279.4),
}
_PAGE_NUMBER_RE = re.compile(
    r"^\s*(?:第\s*)?\d+(?:\s*[/／]\s*\d+)?(?:\s*页)?\s*$"
)


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.name


def _normalize_font(name: str) -> str:
    value = str(name or "").strip()
    if "+" in value:
        value = value.split("+", 1)[1]
    return value.strip()


def _font_allowed(actual: str, allowed: List[str]) -> bool:
    candidate = actual.strip().lower()
    if not candidate:
        return True
    for name in allowed:
        target = str(name).strip().lower()
        if not target:
            continue
        if target in candidate or candidate in target:
            return True
    return False


def audit_rendered_pdf(
    pdf_path: Path,
    *,
    expected_size: Optional[str] = None,
    margins_cm: Optional[Dict[str, float]] = None,
    allowed_fonts: Optional[List[str]] = None,
    require_page_number: bool = False,
    margin_tolerance_cm: float = 0.3,
    page_number_band: float = 0.15,
) -> Tuple[List[WordRenderIssue], List[Dict[str, str]], int]:
    """Inspect a rendered PDF; returns (issues, warnings, page_count)."""
    try:
        import fitz  # noqa: PLC0415 — heavy import, call-time only
    except Exception as exc:  # noqa: BLE001
        raise OfficeParseError(f"PyMuPDF 不可用: {exc}") from exc

    issues: List[WordRenderIssue] = []
    warnings: List[Dict[str, str]] = []
    size_name = expected_size.strip().upper() if expected_size else None
    if size_name is not None and size_name not in _PAGE_SIZES_MM:
        raise OfficeParseError(f"不支持的期望页面尺寸: {expected_size}")
    expected_pair = _PAGE_SIZES_MM.get(size_name) if size_name else None
    baseline: Optional[Tuple[float, float]] = None
    tolerance_cm = max(0.0, float(margin_tolerance_cm))

    document = fitz.open(str(pdf_path))
    try:
        page_count = document.page_count
        for index, page in enumerate(document):
            rect = page.rect
            width_mm = rect.width * _PT_TO_MM
            height_mm = rect.height * _PT_TO_MM
            short, long = sorted((width_mm, height_mm))
            if expected_pair is not None:
                expected_w, expected_h = expected_pair
                if abs(short - expected_w) > 1.0 or abs(long - expected_h) > 1.0:
                    issues.append(
                        WordRenderIssue(
                            page_index=index,
                            category="page",
                            severity="error",
                            message=(
                                f"第 {index + 1} 页尺寸实测 {width_mm:.1f}×{height_mm:.1f}mm，"
                                f"期望 {size_name}"
                            ),
                            expected=size_name,
                            actual=f"{width_mm:.1f}×{height_mm:.1f}mm",
                        )
                    )
            elif baseline is None:
                baseline = (short, long)
            elif abs(short - baseline[0]) > 1.0 or abs(long - baseline[1]) > 1.0:
                issues.append(
                    WordRenderIssue(
                        page_index=index,
                        category="page",
                        severity="warning",
                        message=(
                            f"第 {index + 1} 页尺寸与首页不一致 "
                            f"({width_mm:.1f}×{height_mm:.1f}mm)"
                        ),
                        expected=f"{baseline[0]:.1f}×{baseline[1]:.1f}mm",
                        actual=f"{short:.1f}×{long:.1f}mm",
                    )
                )

            page_dict = page.get_text("dict")
            blocks = [
                block
                for block in page_dict.get("blocks", [])
                if block.get("type") == 0 and block.get("lines")
            ]
            body_blocks = [
                block
                for block in blocks
                if block["bbox"][3] > rect.height * 0.10
                and block["bbox"][1] < rect.height * 0.90
            ]

            if margins_cm and body_blocks:
                expected = {
                    side: margins_cm.get(side)
                    for side in ("top", "bottom", "left", "right")
                }
                min_x = min(block["bbox"][0] for block in body_blocks)
                max_x = max(block["bbox"][2] for block in body_blocks)
                min_y = min(block["bbox"][1] for block in body_blocks)
                max_y = max(block["bbox"][3] for block in body_blocks)
                sides = (
                    ("left", min_x * _PT_TO_CM, "左"),
                    ("right", (rect.width - max_x) * _PT_TO_CM, "右"),
                    ("top", min_y * _PT_TO_CM, "上"),
                    ("bottom", (rect.height - max_y) * _PT_TO_CM, "下"),
                )
                for side, actual_cm, label in sides:
                    value = expected.get(side)
                    if value is None:
                        continue
                    if actual_cm + tolerance_cm < float(value):
                        issues.append(
                            WordRenderIssue(
                                page_index=index,
                                category="margin",
                                severity="error",
                                message=(
                                    f"第 {index + 1} 页{label}侧正文距页面边缘 "
                                    f"{actual_cm:.2f}cm，小于期望 {float(value):g}cm"
                                ),
                                expected=f"{float(value):g}cm",
                                actual=f"{actual_cm:.2f}cm",
                            )
                        )

            if allowed_fonts:
                names: List[str] = []
                for font in page.get_fonts(full=True):
                    base = _normalize_font(font[3] if len(font) > 3 else "")
                    if base and base not in names:
                        names.append(base)
                for name in names:
                    if not _font_allowed(name, allowed_fonts):
                        issues.append(
                            WordRenderIssue(
                                page_index=index,
                                category="font",
                                severity="warning",
                                message=f"第 {index + 1} 页使用了未允许的字体: {name}",
                                expected=", ".join(allowed_fonts),
                                actual=name,
                            )
                        )

            if require_page_number:
                band_top = rect.height * (1.0 - max(0.01, min(0.5, page_number_band)))
                footer_texts = [
                    line.get("spans", [{}])[0].get("text", "")
                    for block in blocks
                    if block["bbox"][1] >= band_top
                    for line in block.get("lines", [])
                ]
                has_number = any(
                    _PAGE_NUMBER_RE.match(text.strip()) or re.search(r"\d+", text)
                    for text in footer_texts
                )
                if not has_number:
                    issues.append(
                        WordRenderIssue(
                            page_index=index,
                            category="page_number",
                            severity="warning",
                            message=f"第 {index + 1} 页底部未检测到页码",
                            expected="页码",
                            actual="未找到",
                        )
                    )
    finally:
        document.close()
    return issues, warnings, page_count


def audit_word_render(
    file_path: Path,
    *,
    workspace_path: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None,
    export_fn: Optional[Callable[..., ExportPdfResult]] = None,
) -> WordRenderAuditResult:
    """Render a .docx to PDF (local converter) and audit the PDF layout."""
    path = Path(file_path)
    if not path.exists():
        raise OfficeFileNotFoundError(path)
    if not path.is_file():
        raise OfficeParseError("DOCX 路径不是文件")
    if path.suffix.lower() != ".docx":
        raise OfficeParseError("渲染审计仅支持 .docx")
    root = Path(workspace_path).resolve() if workspace_path else path.parent.resolve()
    if not root.is_dir():
        raise OfficeParseError("工作区目录不存在")
    opts = options or {}
    timeout = int(opts.get("timeout_seconds", 120))
    exporter = export_fn or export_to_pdf
    export = exporter(path, root, timeout_seconds=timeout)
    if not export.ok or not export.output_path:
        return WordRenderAuditResult(
            ok=True,
            source_path=_rel(path, root),
            rendered=False,
            method=None,
            page_count=0,
            issues=[],
            warnings=[
                {
                    "code": "render_unavailable",
                    "message": export.error or "未找到可用的 PDF 转换器，渲染级检查未执行",
                }
            ],
        )

    warnings: List[Dict[str, str]] = []
    try:
        issues, pdf_warnings, page_count = audit_rendered_pdf(
            Path(export.output_path),
            expected_size=opts.get("expected_size"),
            margins_cm=opts.get("margins_cm"),
            allowed_fonts=opts.get("allowed_fonts"),
            require_page_number=bool(opts.get("require_page_number", False)),
            margin_tolerance_cm=float(opts.get("margin_tolerance_cm", 0.3)),
            page_number_band=float(opts.get("page_number_band", 0.15)),
        )
    except OfficeParseError as exc:
        return WordRenderAuditResult(
            ok=True,
            source_path=_rel(path, root),
            rendered=True,
            method=export.method,
            page_count=0,
            issues=[],
            warnings=[
                {
                    "code": "render_audit_failed",
                    "message": f"PDF 已生成但检查失败: {exc}",
                }
            ],
        )
    warnings.extend(pdf_warnings)
    errors = [issue for issue in issues if issue.severity == "error"]
    return WordRenderAuditResult(
        ok=not errors,
        source_path=_rel(path, root),
        rendered=True,
        method=export.method,
        page_count=page_count,
        issues=issues,
        warnings=warnings,
    )


__all__ = ["audit_rendered_pdf", "audit_word_render"]
