"""Read-only PDF layout/font audit backed by PyMuPDF.

The audit never modifies the PDF and never runs TeX. It reports deterministic
findings (page count/size, embedded fonts, effective image DPI) with page
anchors so callers can fix the source or export settings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.office.errors import (
    OfficeFileNotFoundError,
    OfficeParseError,
    OfficeSizeLimitError,
)

DEFAULT_MAX_PDF_BYTES = 100 * 1024 * 1024
MAX_ANALYZED_PAGES = 500
MIN_IMAGE_POINTS = 36.0
SIZE_TOLERANCE = 2.0
_KNOWN_SIZES = (
    ("A4", 595.28, 841.89),
    ("Letter", 612.0, 792.0),
    ("Legal", 612.0, 1008.0),
)


def _load_fitz() -> Any:
    try:
        import pymupdf  # noqa: PLC0415 — optional heavy dependency

        return pymupdf
    except ImportError:
        try:
            import fitz  # noqa: PLC0415 — fallback for older PyMuPDF

            return fitz
        except ImportError as exc:
            raise OfficeParseError("PDF 审计需要 PyMuPDF，请安装后重试") from exc


def _label_size(width: float, height: float) -> Optional[str]:
    for name, standard_w, standard_h in _KNOWN_SIZES:
        if (
            abs(width - standard_w) <= SIZE_TOLERANCE
            and abs(height - standard_h) <= SIZE_TOLERANCE
        ):
            return name
        if (
            abs(width - standard_h) <= SIZE_TOLERANCE
            and abs(height - standard_w) <= SIZE_TOLERANCE
        ):
            return f"{name} (landscape)"
    return None


def _issue(
    source_path: str,
    rule_id: str,
    severity: str,
    category: str,
    message: str,
    *,
    page: Optional[int] = None,
    evidence: Optional[Any] = None,
    fix_hint: str = "",
) -> Dict[str, Any]:
    item: Dict[str, Any] = {
        "rule_id": rule_id,
        "severity": severity,
        "category": category,
        "message": message,
        "fix_hint": fix_hint,
    }
    if page is not None:
        item["anchor"] = {"file": source_path, "page": page}
    if evidence:
        item["evidence"] = evidence
    return item


def _collect_page_facts(
    doc: Any,
    analyzed_pages: int,
    *,
    source_path: str,
    min_image_dpi: float,
    issues: List[Dict[str, Any]],
) -> Tuple[
    Dict[Tuple[float, float], List[int]],
    Dict[Tuple[str, str, str], Dict[str, Any]],
    int,
    Optional[float],
]:
    sizes: Dict[Tuple[float, float], List[int]] = {}
    fonts: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    images_count = 0
    min_dpi: Optional[float] = None
    for index in range(analyzed_pages):
        page = doc.load_page(index)
        page_number = index + 1
        width = round(float(page.rect.width), 1)
        height = round(float(page.rect.height), 1)
        sizes.setdefault((width, height), []).append(page_number)

        for font in page.get_fonts(full=True):
            ext = str(font[1] or "")
            font_type = str(font[2] or "")
            basefont = str(font[3] or "")
            key = (basefont, font_type, ext)
            entry = fonts.get(key)
            if entry is None:
                entry = {
                    "basefont": basefont,
                    "type": font_type,
                    "ext": ext,
                    "embedded": ext not in ("", "n/a"),
                    "pages": [],
                }
                fonts[key] = entry
            if page_number not in entry["pages"]:
                entry["pages"].append(page_number)

        for info in page.get_image_info(xrefs=True):
            bbox = info.get("bbox") or (0.0, 0.0, 0.0, 0.0)
            box_width = float(bbox[2]) - float(bbox[0])
            box_height = float(bbox[3]) - float(bbox[1])
            if box_width <= 0 or box_height <= 0:
                continue
            images_count += 1
            if box_width < MIN_IMAGE_POINTS or box_height < MIN_IMAGE_POINTS:
                continue
            dpi_width = float(info.get("width", 0)) / (box_width / 72.0)
            dpi_height = float(info.get("height", 0)) / (box_height / 72.0)
            dpi = min(dpi_width, dpi_height)
            min_dpi = dpi if min_dpi is None else min(min_dpi, dpi)
            if dpi < min_image_dpi:
                issues.append(
                    _issue(
                        source_path,
                        "PDF-IMAGE-LOW-DPI",
                        "warning",
                        "pdf-image",
                        f"第 {page_number} 页图片有效分辨率过低: {dpi:.0f} DPI",
                        page=page_number,
                        evidence={
                            "width": info.get("width"),
                            "height": info.get("height"),
                            "dpi": round(dpi, 1),
                            "bbox": [round(value, 1) for value in bbox],
                        },
                        fix_hint="替换为更高分辨率图片，或缩小版面尺寸",
                    )
                )
    return sizes, fonts, images_count, min_dpi


def audit_pdf(
    file_path: Path,
    *,
    root: Optional[Path] = None,
    required_min_pages: Optional[int] = None,
    required_max_pages: Optional[int] = None,
    min_image_dpi: float = 150.0,
    max_bytes: int = DEFAULT_MAX_PDF_BYTES,
) -> Dict[str, Any]:
    """Audit a workspace PDF for page size/count, embedded fonts and image DPI."""
    path = Path(file_path)
    if not path.is_file():
        raise OfficeFileNotFoundError(path)
    if path.suffix.lower() != ".pdf":
        raise OfficeParseError("仅支持 .pdf 审计")
    if root is not None:
        from backend.office.path_safety import resolve_within

        path = resolve_within(Path(root), path)
    size = path.stat().st_size
    if size > max_bytes:
        raise OfficeSizeLimitError(size, max_bytes)

    fitz = _load_fitz()
    source_path = path.name
    if root is not None:
        try:
            source_path = path.relative_to(Path(root).resolve()).as_posix()
        except ValueError:
            source_path = path.name

    try:
        doc = fitz.open(str(path))
    except Exception as exc:  # noqa: BLE001 — map backend failures to parse error
        raise OfficeParseError(f"无法打开 PDF: {exc}") from exc

    issues: List[Dict[str, Any]] = []
    with doc:
        if getattr(doc, "needs_pass", False) or getattr(doc, "is_encrypted", False):
            raise OfficeParseError("PDF 已加密，拒绝审计")
        pages_total = int(doc.page_count)
        if pages_total <= 0:
            raise OfficeParseError("PDF 没有页面")
        analyzed_pages = min(pages_total, MAX_ANALYZED_PAGES)
        if pages_total > MAX_ANALYZED_PAGES:
            issues.append(
                _issue(
                    source_path,
                    "PDF-PAGE-LIMIT",
                    "info",
                    "pdf-pages",
                    f"PDF 共 {pages_total} 页，仅分析前 {MAX_ANALYZED_PAGES} 页",
                    fix_hint="如确需全量分析，请拆分 PDF 后分别审计",
                )
            )

        sizes, fonts, images_count, min_dpi = _collect_page_facts(
            doc,
            analyzed_pages,
            source_path=source_path,
            min_image_dpi=min_image_dpi,
            issues=issues,
        )

    if required_min_pages is not None and pages_total < required_min_pages:
        issues.append(
            _issue(
                source_path,
                "PDF-PAGE-COUNT",
                "error",
                "pdf-pages",
                f"页数不足: {pages_total} < {required_min_pages}",
                fix_hint="检查内容是否完整或调整页数要求",
            )
        )
    if required_max_pages is not None and pages_total > required_max_pages:
        issues.append(
            _issue(
                source_path,
                "PDF-PAGE-COUNT",
                "error",
                "pdf-pages",
                f"页数超限: {pages_total} > {required_max_pages}",
                fix_hint="精简内容或调整页数要求",
            )
        )

    first_size, first_pages = next(iter(sizes.items()))
    first_label = _label_size(*first_size)
    if first_label is None:
        issues.append(
            _issue(
                source_path,
                "PDF-PAGE-SIZE-UNUSUAL",
                "warning",
                "pdf-page-size",
                f"页面尺寸不是常见规格: {first_size[0]}×{first_size[1]} pt",
                page=first_pages[0],
                evidence={"width": first_size[0], "height": first_size[1]},
                fix_hint="确认期刊要求的 A4 / Letter / Legal 页面尺寸",
            )
        )
    if len(sizes) > 1:
        issues.append(
            _issue(
                source_path,
                "PDF-PAGE-SIZE-MIXED",
                "warning",
                "pdf-page-size",
                f"页面尺寸不一致（{len(sizes)} 种）",
                page=first_pages[0],
                evidence=[
                    {"width": width, "height": height, "pages": pages}
                    for (width, height), pages in sizes.items()
                ],
                fix_hint="统一页面尺寸后重新导出",
            )
        )

    for entry in fonts.values():
        if entry["embedded"]:
            continue
        issues.append(
            _issue(
                source_path,
                "PDF-FONT-NOT-EMBEDDED",
                "error",
                "pdf-font",
                f"字体未嵌入: {entry['basefont']}",
                page=entry["pages"][0],
                evidence={
                    "basefont": entry["basefont"],
                    "type": entry["type"],
                    "pages": entry["pages"],
                },
                fix_hint="导出 PDF 时选择嵌入全部字体",
            )
        )

    return {
        "ok": not any(item["severity"] == "error" for item in issues),
        "source_path": source_path,
        "summary": {
            "pages": pages_total,
            "page_size": {
                "width": first_size[0],
                "height": first_size[1],
                "label": first_label or "Custom",
            },
            "page_sizes": [
                {"width": width, "height": height, "pages": pages}
                for (width, height), pages in sizes.items()
            ],
            "fonts": list(fonts.values()),
            "images_count": images_count,
            "min_image_dpi": round(min_dpi, 1) if min_dpi is not None else None,
        },
        "issues": issues,
    }


__all__ = ["DEFAULT_MAX_PDF_BYTES", "MAX_ANALYZED_PAGES", "audit_pdf"]
