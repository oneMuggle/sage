"""PDF page operations (M6): merge, split, rotate, extract/delete, watermark, numbers.

All operations write inside the workspace and use atomic replacement.
PyMuPDF is imported lazily so the module stays importable on machines where
optional PDF deps are missing (operations then raise OfficeParseError).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .errors import OfficeFileNotFoundError, OfficeParseError, OfficePathError
from .path_safety import resolve_within
from .storage import validate_workspace

logger = logging.getLogger(__name__)

__all__ = [
    "PdfMergeRequest",
    "PdfOpsResult",
    "PdfPageNumbersRequest",
    "PdfPagesRequest",
    "PdfRotateRequest",
    "PdfSplitRequest",
    "PdfWatermarkRequest",
    "merge_pdfs",
    "number_pdf_pages",
    "rotate_pdf",
    "split_pdf",
    "update_pages",
    "watermark_pdf",
]

MAX_PDF_OPS_BYTES = 200 * 1024 * 1024


class PdfOpsResult(BaseModel):
    """Result of a PDF page operation."""

    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    outputs: List[str] = Field(default_factory=list)
    page_count: int = 0
    warnings: List[Dict[str, str]] = Field(default_factory=list)


class PdfMergeRequest(BaseModel):
    """POST /office/pdf/merge request."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_paths: List[str] = Field(min_length=2)
    output_filename: Optional[str] = None
    overwrite: bool = False


class PdfRotateRequest(BaseModel):
    """POST /office/pdf/rotate request."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str
    angle: Literal[90, 180, 270]
    pages: Optional[List[str]] = Field(
        default=None, description="1 基页码/区间，如 ['1-3','5']；None=全部"
    )
    output_filename: Optional[str] = None
    overwrite: bool = False


class PdfPagesRequest(BaseModel):
    """POST /office/pdf/pages request (extract or delete)."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str
    action: Literal["extract", "delete"]
    pages: List[str] = Field(min_length=1)
    output_filename: Optional[str] = None
    overwrite: bool = False


class PdfSplitRequest(BaseModel):
    """POST /office/pdf/split request (one output per range)."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str
    ranges: List[str] = Field(min_length=1, description="每项为 1 基区间，如 '1-3'")
    output_prefix: Optional[str] = None


class PdfWatermarkRequest(BaseModel):
    """POST /office/pdf/watermark request (diagonal text watermark)."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str
    text: str = Field(min_length=1, max_length=200)
    output_filename: Optional[str] = None
    overwrite: bool = False
    font_size: int = Field(default=36, ge=8, le=144)
    rotation: int = Field(default=45, ge=-180, le=180)


class PdfPageNumbersRequest(BaseModel):
    """POST /office/pdf/page-numbers request."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str
    output_filename: Optional[str] = None
    overwrite: bool = False
    start: int = Field(default=1, ge=0)
    template: str = Field(default="{n}", min_length=1, max_length=40)


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.name


def _open_pdf(path: Path) -> Any:
    try:
        import fitz  # noqa: PLC0415 — lazy heavy import
    except Exception as exc:  # noqa: BLE001
        raise OfficeParseError(f"PyMuPDF 不可用: {exc}") from exc
    try:
        return fitz.open(str(path))
    except Exception as exc:  # noqa: BLE001 — 统一映射解析失败
        raise OfficeParseError(f"Failed to parse PDF: {exc}", file_path=path) from exc


def _validate_source(workspace_path: str, file_path: str) -> tuple:
    workspace = validate_workspace(Path(workspace_path))
    source = resolve_within(workspace, Path(file_path))
    if not source.is_file():
        raise OfficeFileNotFoundError(source)
    if source.suffix.lower() != ".pdf":
        raise OfficeParseError("PDF 页面操作仅支持 .pdf")
    if source.stat().st_size > MAX_PDF_OPS_BYTES:
        raise OfficeParseError("PDF 超过 200MiB 页面操作上限")
    return workspace, source


def _validate_output_name(name: str) -> str:
    value = (name or "").strip()
    if not value:
        raise OfficeParseError("output_filename 不能为空")
    if Path(value).is_absolute() or "/" in value or "\\" in value:
        raise OfficeParseError("output_filename 不能包含路径分隔符")
    if value in (".", ".."):
        raise OfficeParseError("output_filename 非法")
    if not value.lower().endswith(".pdf"):
        raise OfficeParseError("output_filename 必须以 .pdf 结尾")
    return value


def _resolve_output(
    workspace: Path,
    source: Path,
    output_filename: Optional[str],
    default_name: str,
    *,
    overwrite: bool,
) -> Path:
    name = _validate_output_name(output_filename or default_name)
    try:
        target = resolve_within(workspace, source.parent / name)
    except OfficePathError as exc:
        raise OfficeParseError("输出路径不在工作区内") from exc
    if target == source and not overwrite:
        raise OfficeParseError("输出文件不能覆盖源文件；如需覆盖请使用 overwrite=true")
    if target.exists() and not overwrite:
        raise OfficeParseError("输出文件已存在，拒绝覆盖")
    return target


def _save_pdf(document: Any, target: Path) -> None:
    temporary = target.with_name(target.name + ".pdf-ops-tmp")
    try:
        document.save(str(temporary), deflate=True)
        temporary.replace(target)
    except OSError as exc:
        raise OfficeParseError(f"保存 PDF 失败: {exc}", file_path=target) from exc
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                logger.debug("failed to clean %s", temporary)


def _parse_pages(specs: List[str], page_count: int) -> List[int]:
    indices: List[int] = []
    seen = set()
    for raw in specs:
        text = str(raw).strip()
        if not text:
            continue
        try:
            if "-" in text:
                start_text, end_text = text.split("-", 1)
                start = int(start_text)
                end = int(end_text)
            else:
                start = end = int(text)
        except ValueError as exc:
            raise OfficeParseError(f"非法页码: {text!r}") from exc
        if start < 1 or end < start or end > page_count:
            raise OfficeParseError(f"页码超出范围: {text!r}（共 {page_count} 页）")
        for number in range(start, end + 1):
            index = number - 1
            if index not in seen:
                seen.add(index)
                indices.append(index)
    if not indices:
        raise OfficeParseError("页码列表为空")
    return indices


def merge_pdfs(request: PdfMergeRequest) -> PdfOpsResult:
    """Merge multiple PDFs in the given order."""
    workspace, first = _validate_source(request.workspace_path, request.file_paths[0])
    sources = [first]
    for raw in request.file_paths[1:]:
        _, source = _validate_source(request.workspace_path, raw)
        sources.append(source)
    target = _resolve_output(
        workspace, first, request.output_filename, "merged.pdf", overwrite=request.overwrite
    )
    merged = _open_pdf(first)
    try:
        for source in sources[1:]:
            other = _open_pdf(source)
            try:
                merged.insert_pdf(other)
            finally:
                other.close()
        page_count = merged.page_count
        _save_pdf(merged, target)
    finally:
        merged.close()
    return PdfOpsResult(ok=True, outputs=[_rel(target, workspace)], page_count=page_count)


def rotate_pdf(request: PdfRotateRequest) -> PdfOpsResult:
    """Rotate selected pages by 90/180/270 degrees."""
    workspace, source = _validate_source(request.workspace_path, request.file_path)
    target = _resolve_output(
        workspace,
        source,
        request.output_filename,
        f"{source.stem}-rotated.pdf",
        overwrite=request.overwrite,
    )
    document = _open_pdf(source)
    try:
        indices = (
            _parse_pages(request.pages, document.page_count)
            if request.pages
            else list(range(document.page_count))
        )
        for index in indices:
            page = document.load_page(index)
            page.set_rotation((page.rotation + request.angle) % 360)
        page_count = document.page_count
        _save_pdf(document, target)
    finally:
        document.close()
    return PdfOpsResult(ok=True, outputs=[_rel(target, workspace)], page_count=page_count)


def update_pages(request: PdfPagesRequest) -> PdfOpsResult:
    """Extract or delete selected pages into a new PDF."""
    import fitz  # noqa: PLC0415

    workspace, source = _validate_source(request.workspace_path, request.file_path)
    default_name = (
        f"{source.stem}-extracted.pdf"
        if request.action == "extract"
        else f"{source.stem}-pages-removed.pdf"
    )
    target = _resolve_output(
        workspace, source, request.output_filename, default_name, overwrite=request.overwrite
    )
    source_document = _open_pdf(source)
    try:
        selected = set(_parse_pages(request.pages, source_document.page_count))
        keep = (
            sorted(selected)
            if request.action == "extract"
            else [i for i in range(source_document.page_count) if i not in selected]
        )
        if not keep:
            raise OfficeParseError("操作后没有剩余页面")
        output = fitz.open()
        try:
            for index in keep:
                output.insert_pdf(source_document, from_page=index, to_page=index)
            page_count = output.page_count
            _save_pdf(output, target)
        finally:
            output.close()
    finally:
        source_document.close()
    return PdfOpsResult(ok=True, outputs=[_rel(target, workspace)], page_count=page_count)


def split_pdf(request: PdfSplitRequest) -> PdfOpsResult:
    """Split a PDF into one output per range (e.g. ['1-3','4-6'])."""
    import fitz  # noqa: PLC0415

    workspace, source = _validate_source(request.workspace_path, request.file_path)
    prefix = request.output_prefix or source.stem
    if Path(prefix).name != prefix or ".." in prefix:
        raise OfficeParseError("output_prefix 非法")
    document = _open_pdf(source)
    outputs: List[str] = []
    planned: List[tuple] = []
    try:
        # Validate every range/output before writing anything (all-or-nothing).
        for order, raw_range in enumerate(request.ranges, start=1):
            indices = _parse_pages([raw_range], document.page_count)
            name = _validate_output_name(f"{prefix}-{order}.pdf")
            target = resolve_within(workspace, source.parent / name)
            if target.exists():
                raise OfficeParseError(f"输出文件已存在: {name}")
            planned.append((indices, target))
        for indices, target in planned:
            part = fitz.open()
            try:
                for index in indices:
                    part.insert_pdf(document, from_page=index, to_page=index)
                _save_pdf(part, target)
            finally:
                part.close()
            outputs.append(_rel(target, workspace))
        page_count = document.page_count
    except Exception:
        for relative in outputs:
            try:
                (workspace / relative).unlink()
            except OSError:
                logger.debug("failed to clean partial split output %s", relative)
        raise
    finally:
        document.close()
    return PdfOpsResult(ok=True, outputs=outputs, page_count=page_count)


def watermark_pdf(request: PdfWatermarkRequest) -> PdfOpsResult:
    """Stamp a diagonal text watermark on every page."""
    import math  # noqa: PLC0415

    import fitz  # noqa: PLC0415

    workspace, source = _validate_source(request.workspace_path, request.file_path)
    target = _resolve_output(
        workspace,
        source,
        request.output_filename,
        f"{source.stem}-watermarked.pdf",
        overwrite=request.overwrite,
    )
    document = _open_pdf(source)
    try:
        # Built-in CJK font for non-ASCII watermarks; Helvetica otherwise.
        font_name = "china-s" if any(ord(char) > 127 for char in request.text) else "helv"
        font = fitz.Font(font_name)
        angle = math.radians(request.rotation)
        matrix = fitz.Matrix(
            math.cos(angle), math.sin(angle), -math.sin(angle), math.cos(angle), 0, 0
        )
        for page in document:
            width = font.text_length(request.text, fontsize=request.font_size)
            writer = fitz.TextWriter(page.rect)
            writer.append(
                (page.rect.width / 2 - width / 2, page.rect.height / 2),
                request.text,
                font=font,
                fontsize=request.font_size,
            )
            pivot = fitz.Point(page.rect.width / 2, page.rect.height / 2)
            writer.write_text(page, morph=(pivot, matrix), color=(0.5, 0.5, 0.5))
        page_count = document.page_count
        _save_pdf(document, target)
    finally:
        document.close()
    return PdfOpsResult(ok=True, outputs=[_rel(target, workspace)], page_count=page_count)


def number_pdf_pages(request: PdfPageNumbersRequest) -> PdfOpsResult:
    """Add page numbers (template supports ``{n}``) to the bottom of each page."""
    import fitz  # noqa: PLC0415

    workspace, source = _validate_source(request.workspace_path, request.file_path)
    target = _resolve_output(
        workspace,
        source,
        request.output_filename,
        f"{source.stem}-numbered.pdf",
        overwrite=request.overwrite,
    )
    document = _open_pdf(source)
    try:
        for offset, page in enumerate(document):
            number = request.start + offset
            try:
                text = request.template.format(n=number)
            except (KeyError, ValueError) as exc:
                raise OfficeParseError(f"页码模板非法: {request.template!r}") from exc
            rect = page.rect
            band = fitz.Rect(0, rect.height - 36, rect.width, rect.height - 12)
            page.insert_textbox(
                band,
                text,
                fontsize=10,
                color=(0, 0, 0),
                align=fitz.TEXT_ALIGN_CENTER,
                overlay=True,
            )
        page_count = document.page_count
        _save_pdf(document, target)
    finally:
        document.close()
    return PdfOpsResult(ok=True, outputs=[_rel(target, workspace)], page_count=page_count)
