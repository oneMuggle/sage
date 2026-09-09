"""PPTX reader using python-pptx.

Pure functions: no FastAPI, no I/O outside the file argument. Caller (the
FastAPI route handler in office_routes.py) wraps exceptions into HTTP errors
using the office_error_to_http_status() mapping in errors.py.

The reader extracts a structured view of a .pptx:
- slide titles (from layout placeholder or first text shape)
- all text blocks (concatenated paragraphs across shapes)
- table count per slide
- image count per slide
- speaker notes

It deliberately does NOT preserve:
- formatting (bold, color, font size)
- animations / transitions
- master slide references
- OLE / embedded objects (counted but not extracted)

These omissions are intentional per plan §1.3 "non-goals".
"""

from __future__ import annotations

import contextlib
import logging
import time
from pathlib import Path
from typing import List, Optional

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from .errors import OfficeFileNotFoundError, OfficeGenerateError, OfficeParseError, OfficePathError
from .models import (
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
    OfficePptReadResult,
    PptSlideContent,
)
from .path_safety import managed_document_path, resolve_output_path, validate_supported_filename
from .storage import validate_workspace

logger = logging.getLogger(__name__)


def _extract_slide_title(slide) -> Optional[str]:
    """Get the slide title from the title placeholder or first text shape."""
    try:
        if slide.shapes.title is not None and slide.shapes.title.has_text_frame:
            text = slide.shapes.title.text_frame.text.strip()
            if text:
                return text
    except (AttributeError, KeyError):
        pass

    # Fallback: first text-bearing shape
    for shape in slide.shapes:
        if shape.has_text_frame:
            text = shape.text_frame.text.strip()
            if text:
                return text
    return None


def _extract_text_blocks(slide) -> List[str]:
    """All non-empty text paragraphs from every shape on the slide.

    Skips the title shape's first paragraph (already captured in slide.title)
    but keeps subsequent paragraphs from the title shape (often bullet points
    under the title in title-slide layouts).
    """
    blocks: List[str] = []
    title_shape_id: Optional[int] = None
    try:
        if slide.shapes.title is not None:
            title_shape_id = id(slide.shapes.title)
    except (AttributeError, KeyError):
        pass

    for shape in slide.shapes:
        if not shape.has_text_frame:
            continue
        if id(shape) == title_shape_id:
            # Skip the title's first paragraph; keep subsequent (often bullets).
            for para in shape.text_frame.paragraphs[1:]:
                text = para.text.strip()
                if text:
                    blocks.append(text)
            continue
        for para in shape.text_frame.paragraphs:
            text = para.text.strip()
            if text:
                blocks.append(text)
    return blocks


def _count_tables(slide) -> int:
    """Number of GraphicFrame shapes containing tables on this slide."""
    return sum(1 for shape in slide.shapes if shape.shape_type == MSO_SHAPE_TYPE.TABLE)


def _count_images(slide) -> int:
    """Number of Picture shapes on this slide."""
    return sum(1 for shape in slide.shapes if shape.shape_type == MSO_SHAPE_TYPE.PICTURE)


def _extract_notes(slide) -> Optional[str]:
    """Speaker notes text, or None if no notes slide."""
    try:
        notes_slide = slide.notes_slide
        if notes_slide is None:
            return None
        text = notes_slide.notes_text_frame.text.strip()
        return text or None
    except (AttributeError, KeyError, ValueError):
        # python-pptx raises ValueError if no notes part exists
        return None


def _build_pptx_summary(
    file_path: Path,
    *,
    document_id: str,
    workspace_path: str,
    generated_filename: Optional[str],
    original_filename: Optional[str],
    status: OfficeDocStatus,
    page_count: int,
) -> OfficeDocumentSummary:
    """Construct a summary for a PPTX document."""
    now_ms = int(time.time() * 1000)
    return OfficeDocumentSummary(
        id=document_id,
        workspace_path=workspace_path,
        doc_type=OfficeDocType.PPT,
        original_filename=original_filename,
        generated_filename=generated_filename or file_path.name,
        status=status,
        created_at=now_ms,
        updated_at=now_ms,
        metadata=OfficeDocumentMetadata(
            page_count=page_count,
            table_count=None,  # aggregated across slides; not in summary
            paragraph_count=None,
            file_size_bytes=file_path.stat().st_size,
        ),
    )


def read_ppt(
    file_path: Path,
    *,
    document_id: Optional[str] = None,
    workspace_path: str = "",
    generated_filename: Optional[str] = None,
    original_filename: Optional[str] = None,
) -> OfficePptReadResult:
    """Read a .pptx file and return its structured content.

    Args:
        file_path: Absolute path to the .pptx file.
        document_id: Optional UUID for the summary record. Defaults to file_path.stem.
        workspace_path: Required by storage layer; pass empty string for read-only tests.
        generated_filename: Filename as stored in workspace/office/<id>/.
        original_filename: User's uploaded filename (None when generated from scratch).

    Returns:
        OfficePptReadResult with summary + slides array.

    Raises:
        OfficeFileNotFoundError: file doesn't exist.
        OfficeParseError: file exists but isn't a valid PPTX.
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise OfficeFileNotFoundError(file_path)
    if not file_path.is_file():
        raise OfficeParseError(f"Path is not a regular file: {file_path}", file_path=file_path)

    try:
        prs = Presentation(str(file_path))
    except Exception as exc:
        # python-pptx raises various low-level exceptions (zipfile.BadZipFile,
        # lxml.etree.XMLSyntaxError, etc.). Normalize to OfficeParseError.
        raise OfficeParseError(f"Failed to parse PPTX: {exc}", file_path=file_path) from exc

    doc_id = document_id or file_path.stem
    slides: List[PptSlideContent] = []
    for idx, slide in enumerate(prs.slides):
        slides.append(
            PptSlideContent(
                index=idx,
                title=_extract_slide_title(slide),
                text_blocks=_extract_text_blocks(slide),
                table_count=_count_tables(slide),
                image_count=_count_images(slide),
                notes=_extract_notes(slide),
            )
        )

    summary = _build_pptx_summary(
        file_path,
        document_id=doc_id,
        workspace_path=workspace_path,
        generated_filename=generated_filename,
        original_filename=original_filename,
        status=OfficeDocStatus.PARSED,
        page_count=len(prs.slides),
    )

    return OfficePptReadResult(summary=summary, slides=slides)


# ──────────────────────────────────────────────────────────────────────
# Generator (Phase 1.4 step 19, plan §4.1.4)
# ──────────────────────────────────────────────────────────────────────

#: Same textbox geometry the edit layer uses, so generated decks and
#: in-place edits blend together（与 edit._TITLE/_BODY_BOX_GEOMETRY 一致）.
_TITLE_BOX_GEOMETRY = (914400, 274638, 9144000, 1143000)
_BODY_BOX_GEOMETRY = (914400, 1600200, 9144000, 4572000)

#: 批次 2.3：PptSlideSpec.layout → 默认模板版式名（按名查找，找不到再按
#: 常见索引兜底，最后回退 Blank + 文本框几何）。
_LAYOUT_NAME_HINTS = {
    "title": ("Title Slide",),
    "title_content": ("Title and Content",),
    "blank": ("Blank",),
}
_LAYOUT_INDEX_FALLBACK = {"title": 0, "title_content": 1, "blank": 6}


def _resolve_slide_layout(prs, layout_name: Optional[str]):
    """按名字在演示文稿模板里找版式；找不到回退常见索引；再不行返回 None
    （调用方据此走原有 Blank + 文本框几何路径）。"""
    if not layout_name:
        return None
    # PptLayoutName 是 str-Enum：成员的 hash 与裸字符串不同，dict 查找前
    # 必须归一化为 .value。
    name = str(getattr(layout_name, "value", layout_name))
    layouts = prs.slide_layouts
    for hint in _LAYOUT_NAME_HINTS.get(name, ()):
        for layout in layouts:
            if layout.name == hint:
                return layout
    fallback = _LAYOUT_INDEX_FALLBACK.get(name)
    if fallback is not None and 0 <= fallback < len(layouts):
        return layouts[fallback]
    logger.warning("未找到 slide layout %r，回退默认几何", name)
    return None


def _slide_body_placeholder(slide):
    """标题占位符之外、第一个带文本框的占位符（title_content 版式的正文框）。"""
    title = None
    with contextlib.suppress(AttributeError, KeyError):
        title = slide.shapes.title
    for placeholder in slide.placeholders:
        if title is not None and placeholder.placeholder_format.idx == title.placeholder_format.idx:
            continue
        if placeholder.has_text_frame:
            return placeholder
    return None


def _fill_text_frame_lines(text_frame, lines) -> None:
    """首行写入 text，其余逐段 add_paragraph（生成器/编辑层同款语义）。"""
    if not lines:
        return
    text_frame.text = lines[0]
    for line in lines[1:]:
        text_frame.add_paragraph().text = line


def _add_slide_image(slide, image_spec) -> None:
    """批次 2.1：把 ImageSourceSpec 插到 slide（缺省位于正文区左上角）。"""
    from .charts import image_bytes_to_stream, resolve_image_payload

    payload = resolve_image_payload(image_spec.source)
    left, top = _BODY_BOX_GEOMETRY[0], _BODY_BOX_GEOMETRY[1]
    from pptx.util import Inches

    width = Inches(image_spec.width_inches) if image_spec.width_inches else None
    height = Inches(image_spec.height_inches) if image_spec.height_inches else None
    slide.shapes.add_picture(
        image_bytes_to_stream(payload), left, top, width=width, height=height
    )


def _safe_filename(name: str, default_ext: str) -> str:
    """Backwards-compat shim retained for callers that still import it.

    The canonical implementation now lives in
    :func:`backend.office.path_safety.validate_supported_filename`, which
    additionally enforces the extension matches the doc type's canonical
    extension and rejects sibling-prefix-style typos.
    """
    if default_ext == "pptx":
        return validate_supported_filename(name, OfficeDocType.PPT)
    if default_ext == "docx":
        return validate_supported_filename(name, OfficeDocType.WORD)
    if default_ext == "xlsx":
        return validate_supported_filename(name, OfficeDocType.EXCEL)
    raise OfficePathError(f"Unknown default_ext: {default_ext!r}")


def generate_ppt(req, output_dir: Optional[str] = None) -> Path:
    """Generate a .pptx file from structured Pydantic input.

    ``output_dir`` 提供时写入该任意目录（信任的用户指定目录，经
    :func:`resolve_output_path` 校验文件名）；``None`` 时保持现状写
    workspace 沙箱（``<workspace>/office/ppt/<uuid>/<name>``，经
    :func:`path_safety.managed_document_path` 跨平台包含性校验）。
    """
    if output_dir is not None:
        output_path = resolve_output_path(output_dir, OfficeDocType.PPT, req.filename)
    else:
        workspace = validate_workspace(Path(req.workspace_path))
        import uuid
        doc_id = uuid.uuid4().hex
        output_path = managed_document_path(workspace, OfficeDocType.PPT, doc_id, req.filename)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        prs = Presentation()
        # Layout 6 is "Blank" — most flexible for any content
        blank_layout = prs.slide_layouts[6]
        for spec in req.slides:
            # 批次 2.3：可选 layout 字段按模板版式名查找；未指定或模板里
            # 找不到对应版式时，保持既有 Blank + 文本框几何行为不变。
            layout = _resolve_slide_layout(prs, getattr(spec, "layout", None))
            slide = prs.slides.add_slide(layout if layout is not None else blank_layout)
            title_shape = None
            if layout is not None:
                with contextlib.suppress(AttributeError, KeyError):
                    title_shape = slide.shapes.title
            # Add a title text box at the top
            if spec.title:
                if title_shape is not None and title_shape.has_text_frame:
                    # 版式自带标题占位符：填占位符（继承版式样式）。
                    title_shape.text_frame.text = spec.title
                else:
                    title_box = slide.shapes.add_textbox(*_TITLE_BOX_GEOMETRY)
                    title_box.text_frame.text = spec.title
            # Add bullets as another text box
            if spec.bullets:
                body_placeholder = _slide_body_placeholder(slide) if layout is not None else None
                if body_placeholder is not None:
                    _fill_text_frame_lines(body_placeholder.text_frame, spec.bullets)
                else:
                    body_box = slide.shapes.add_textbox(*_BODY_BOX_GEOMETRY)
                    _fill_text_frame_lines(body_box.text_frame, spec.bullets)
            # 批次 2.1：可选插图（位于文本之后）
            image_spec = getattr(spec, "image", None)
            if image_spec is not None:
                _add_slide_image(slide, image_spec)
            # Add speaker notes
            if spec.notes:
                slide.notes_slide.notes_text_frame.text = spec.notes
        prs.save(str(output_path))
    except Exception as exc:
        raise OfficeGenerateError(f"Failed to generate PPTX: {exc}", file_path=output_path) from exc

    return output_path
