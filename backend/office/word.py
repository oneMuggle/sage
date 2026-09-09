"""DOCX reader using python-docx.

Pure functions: no FastAPI, no I/O outside the file argument. Caller (the
FastAPI route handler in office_routes.py) wraps exceptions into HTTP errors.

The reader extracts a structured view of a .docx:
- paragraphs with style + level (heading level 0 means body text); run-level
  bold/italic is rendered as ``**bold**`` / ``*italic*`` markers (round 2 R2b)
- tables (rows of cell text, ignoring nested tables / images inside cells)
- image count (inline shapes count as images)
- comments (round 2 R3): ``read_docx`` fills ``OfficeWordReadResult.comments``
  through the same extraction the dedicated :func:`read_docx_comments` uses
  (shared :func:`_extract_comments` helper; the OOXML is walked once per read)

Marker simplifications (documented, round 2 R2b):
- only *direct* run formatting counts: ``run.bold`` / ``run.italic`` are
  ``None`` when inherited from a style, and ``None`` is treated as
  not-bold / not-italic (resolving the style cascade is out of scope);
- paragraphs whose text already contains ``**`` are returned verbatim (no
  marker wrapping — it would be ambiguous with the literal markdown).

It does NOT extract:
- headers / footers (out of scope per plan §1.3)
- footnotes / endnotes
- text boxes / shapes outside the body
- track changes

These omissions are intentional per plan §1.3 "non-goals".
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

DEFAULT_ASCII_FONT = "Times New Roman"
DEFAULT_EA_FONT = "宋体"


_STYLES_TO_PATCH = (
    "Normal",
    "Title",
    "Heading 1",
    "Heading 2",
    "Heading 3",
    "List Bullet",
    "List Number",
)


def _patch_style_rfonts(style, ascii_name: str, ea_name: str) -> None:
    """向指定 style 的 rPr.rFonts 写入 ascii/hAnsi/eastAsia/cs，并清掉 theme 引用。

    python-docx 默认模板中 Title/Heading 1-9/Subtitle 等样式携带
    ``w:asciiTheme="majorHAnsi" w:eastAsiaTheme="majorEastAsia"``，这些
    theme 引用优先级高于显式 ``w:eastAsia``——不删的话日语 Word 默认
    theme 会解析为 ＭＳ ゴシック，让标题仍然渲染成日文字体。
    """
    rPr = style.element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    for theme_attr in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
        attr = qn(f"w:{theme_attr}")
        if attr in rFonts.attrib:
            del rFonts.attrib[attr]
    rFonts.set(qn("w:ascii"), ascii_name)
    rFonts.set(qn("w:hAnsi"), ascii_name)
    rFonts.set(qn("w:eastAsia"), ea_name)
    rFonts.set(qn("w:cs"), ascii_name)


def _patch_linked_character_styles(doc: Document, ascii_name: str, ea_name: str) -> None:
    """Patch 所有被 ``<w:link>`` 关联的 character styles（HeadingNChar /
    TitleChar / SubtitleChar 等）。Word 渲染时，paragraph style 通过
    ``<w:link>`` 关联的 character style 的 rFonts 会覆盖 paragraph style
    本身的 rFonts——所以仅 patch paragraph style 不够，必须同步 patch 所有
    linked character style。
    """
    linked_style_ids: Set[str] = set()
    for style in doc.styles:
        link = style.element.find(qn("w:link"))
        if link is not None:
            linked_style_ids.add(link.get(qn("w:val")))
    for style in doc.styles:
        if style.style_id in linked_style_ids:
            _patch_style_rfonts(style, ascii_name, ea_name)


def set_doc_default_font(doc: Document, ascii_name: str, ea_name: str) -> None:
    """改 styles.xml 中所有 generator 用到的样式（Normal / Title / Heading
    1-3 / List Bullet / List Number）的 rPr.rFonts，强制 Word 用指定字体渲染。

    只改 Normal 不够——Title 与 Heading 1-9 默认携带 theme 引用，会让日语
    Word 渲染成 ＭＳ ゴシック；此外它们通过 ``<w:link>`` 关联的 character
    styles（HeadingNChar / TitleChar）也会覆盖 paragraph style 的 rFonts，
    必须同步 patch。
    """
    for style_name in _STYLES_TO_PATCH:
        try:
            style = doc.styles[style_name]
        except KeyError:
            continue
        _patch_style_rfonts(style, ascii_name, ea_name)
    _patch_linked_character_styles(doc, ascii_name, ea_name)

from .errors import OfficeFileNotFoundError, OfficeParseError
from .models import (
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
    OfficeWordReadResult,
    WordCommentContent,
    WordCommentsResult,
    WordParagraphContent,
    WordTableContent,
)

logger = logging.getLogger(__name__)


def _extract_heading_level(style_name: str) -> int:
    """Extract heading level from python-docx style name.

    Returns 1, 2, 3, ... for 'Heading 1', 'Heading 2', etc.
    Returns 0 for 'Normal' or any other body style.
    """
    if not style_name:
        return 0
    if style_name.startswith("Heading "):
        try:
            return int(style_name[len("Heading ") :])
        except (ValueError, IndexError):
            return 0
    if style_name == "Title":
        return 1  # treat Title as h1
    return 0


def _render_paragraph_text(para) -> str:
    """Paragraph text with run-level bold/italic rendered as markdown markers.

    Consecutive runs sharing the same effective formatting are merged into one
    ``**bold**`` / ``*italic*`` (``***both***``) span; whitespace-only and
    empty runs are kept verbatim inside their span.

    Simplifications (round 2 R2b, documented):
    - ``run.bold`` / ``run.italic`` are *direct* formatting only; ``None``
      (inherited from a paragraph/character style) counts as not-bold /
      not-italic — resolving the full style cascade is out of scope.
    - Paragraphs whose text already contains ``**`` are returned verbatim:
      wrapping spans would be ambiguous with the literal markdown.
    - The marked-up text is assembled from runs only. ``Paragraph.text`` also
      folds in hyperlink text (python-docx ≥1.1), so paragraphs containing
      hyperlinks are complete only on the no-marker fast path below (which
      returns ``para.text`` unchanged for unformatted paragraphs).
    """
    plain = para.text
    if "**" in plain:
        return plain
    if not any(bool(run.bold) or bool(run.italic) for run in para.runs):
        return plain

    # Merge consecutive runs with identical (bold, italic) formatting.
    spans: List[Tuple[bool, bool, List[str]]] = []
    for run in para.runs:
        bold, italic = bool(run.bold), bool(run.italic)
        if spans and spans[-1][0] == bold and spans[-1][1] == italic:
            spans[-1][2].append(run.text)
        else:
            spans.append((bold, italic, [run.text]))

    parts: List[str] = []
    for bold, italic, texts in spans:
        chunk = "".join(texts)
        if not chunk:
            continue
        if bold and italic:
            parts.append(f"***{chunk}***")
        elif bold:
            parts.append(f"**{chunk}**")
        elif italic:
            parts.append(f"*{chunk}*")
        else:
            parts.append(chunk)
    return "".join(parts)


def _extract_paragraphs(doc: Document) -> List[WordParagraphContent]:
    """Extract body paragraphs (skipping tables, headers, footers).

    Text keeps run-level bold/italic as ``**...**`` / ``*...*`` markers; see
    :func:`_render_paragraph_text` for the exact rules and simplifications.
    """
    paragraphs: List[WordParagraphContent] = []
    for para in doc.paragraphs:
        style_name = para.style.name if para.style else "Normal"
        text = _render_paragraph_text(para).strip()
        # Skip empty paragraphs (would just clutter result)
        if not text:
            continue
        paragraphs.append(
            WordParagraphContent(
                style=style_name,
                text=text,
                level=_extract_heading_level(style_name),
            )
        )
    return paragraphs


def _extract_tables(doc: Document) -> List[WordTableContent]:
    """Extract body tables (skipping nested tables)."""
    tables: List[WordTableContent] = []
    for table in doc.tables:
        rows: List[List[str]] = []
        for row in table.rows:
            cells: List[str] = []
            for cell in row.cells:
                cells.append(cell.text.strip())
            rows.append(cells)
        tables.append(WordTableContent(rows=rows))
    return tables


def _count_images(doc: Document) -> int:
    """Count inline pictures in the document body.

    python-docx exposes doc.inline_shapes as a sequence of InlineShape objects,
    one per picture (image or chart).
    """
    return len(doc.inline_shapes)


def _build_docx_summary(
    file_path: Path,
    *,
    document_id: str,
    workspace_path: str,
    generated_filename: Optional[str],
    original_filename: Optional[str],
    status: OfficeDocStatus,
    paragraph_count: int,
) -> OfficeDocumentSummary:
    """Construct a summary for a DOCX document."""
    now_ms = int(time.time() * 1000)
    return OfficeDocumentSummary(
        id=document_id,
        workspace_path=workspace_path,
        doc_type=OfficeDocType.WORD,
        original_filename=original_filename,
        generated_filename=generated_filename or file_path.name,
        status=status,
        created_at=now_ms,
        updated_at=now_ms,
        metadata=OfficeDocumentMetadata(
            page_count=None,  # DOCX doesn't expose page count without rendering
            table_count=None,
            paragraph_count=paragraph_count,
            file_size_bytes=file_path.stat().st_size,
        ),
    )


def read_docx(
    file_path: Path,
    *,
    document_id: Optional[str] = None,
    workspace_path: str = "",
    generated_filename: Optional[str] = None,
    original_filename: Optional[str] = None,
) -> OfficeWordReadResult:
    """Read a .docx file and return its structured content.

    Args:
        file_path: Absolute path to the .docx file.
        document_id: Optional UUID for the summary record. Defaults to file_path.stem.
        workspace_path: Required by storage layer; pass empty string for read-only tests.
        generated_filename: Filename as stored in workspace/office/<id>/.
        original_filename: User's uploaded filename.

    Returns:
        OfficeWordReadResult with summary + paragraphs + tables + image count
        + comments (round 2 R3; empty list when the file has no comments).

    Raises:
        OfficeFileNotFoundError: file doesn't exist.
        OfficeParseError: file exists but isn't a valid DOCX.
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise OfficeFileNotFoundError(file_path)
    if not file_path.is_file():
        raise OfficeParseError(f"Path is not a regular file: {file_path}", file_path=file_path)

    try:
        doc = Document(str(file_path))
    except Exception as exc:
        # python-docx raises zipfile.BadZipFile, lxml.etree.XMLSyntaxError, etc.
        raise OfficeParseError(f"Failed to parse DOCX: {exc}", file_path=file_path) from exc

    paragraphs = _extract_paragraphs(doc)
    tables = _extract_tables(doc)
    images = _count_images(doc)
    # Round 2 R3: comments ride along in the read result. A corrupt comments
    # part must not fail the whole read (body extraction already succeeded);
    # the dedicated read_docx_comments still surfaces it as OfficeParseError.
    try:
        comments = _extract_comments(doc, file_path)
    except Exception:  # noqa: BLE001 — 批注部分损坏不阻断正文读取
        logger.warning(
            "Failed to extract comments from %s; comments omitted", file_path.name, exc_info=True
        )
        comments = []

    doc_id = document_id or file_path.stem

    summary = _build_docx_summary(
        file_path,
        document_id=doc_id,
        workspace_path=workspace_path,
        generated_filename=generated_filename,
        original_filename=original_filename,
        status=OfficeDocStatus.PARSED,
        paragraph_count=len(paragraphs),
    )

    return OfficeWordReadResult(
        summary=summary,
        paragraphs=paragraphs,
        tables=tables,
        images=images,
        comments=comments,
    )


# ──────────────────────────────────────────────────────────────────────
# Comments reader (批次 3.3; round 2 R3 merged into read_docx)
# ──────────────────────────────────────────────────────────────────────
# WordCommentContent / WordCommentsResult live in models.py since round 2
# (batch 3 had them here because models.py was locked at the time); they are
# re-imported above so existing ``from backend.office.word import ...`` users
# keep working.


def _extract_comments(doc: Document, file_path: Path) -> List[WordCommentContent]:
    """Parse the ``word/comments.xml`` part of an opened document.

    Shared by :func:`read_docx` (fills ``OfficeWordReadResult.comments``) and
    :func:`read_docx_comments` (wraps the list in a
    :class:`~backend.office.models.WordCommentsResult`) so the OOXML is walked
    only once per read.

    Raises:
        OfficeParseError: a comments part exists but its XML is corrupt.
    """
    part = _find_comments_part(doc)
    if part is None:
        return []

    from docx.oxml.parser import parse_xml

    try:
        root = parse_xml(part.blob)
    except Exception as exc:
        raise OfficeParseError(
            f"Failed to parse comments part: {exc}", file_path=file_path
        ) from exc

    anchor_map = _collect_anchor_texts(doc.element)
    comments: List[WordCommentContent] = []
    for comment_el in root.findall(qn("w:comment")):
        cid = comment_el.get(qn("w:id")) or ""
        # 批注正文：w:comment 下各段文本，段内拼 run，段间以换行连接。
        para_texts = [
            "".join(t.text or "" for t in p.iter(qn("w:t")))
            for p in comment_el.findall(qn("w:p"))
        ]
        text = "\n".join(pt for pt in para_texts)
        anchor_text = anchor_map.get(cid, "") or _anchor_fallback_text(doc.element, cid)
        comments.append(
            WordCommentContent(
                id=cid,
                author=comment_el.get(qn("w:author")),
                date=comment_el.get(qn("w:date")),
                text=text,
                anchor_text=anchor_text,
            )
        )
    return comments


def _find_comments_part(doc: Document) -> Optional[Any]:
    """Locate the ``word/comments.xml`` part of an opened document, or None.

    python-docx 1.1.2 has no comments API; the part loads as a plain blob
    ``Part``. Iterate the document part's relationships by reltype (first
    match wins) instead of ``part_related_by`` — the latter raises on the
    (pathological) multiple-relationships case.
    """
    from docx.opc.constants import RELATIONSHIP_TYPE as RT

    for rel in doc.part.rels.values():
        if rel.reltype == RT.COMMENTS and not rel.is_external:
            return rel.target_part
    return None


def _collect_anchor_texts(doc_el: Any) -> Dict[str, str]:
    """Map comment id → text between its ``commentRangeStart`` / ``End``.

    Single pass over ``w:document`` in document order: track open ranges,
    and attribute every ``w:t`` seen while a range is open to that comment.
    Ranges may span paragraphs; ids with no ``w:t`` in range map to "".
    """
    anchors: Dict[str, List[str]] = {}
    open_ids: set = set()
    for el in doc_el.iter():
        tag = el.tag
        if tag == qn("w:commentRangeStart"):
            open_ids.add(el.get(qn("w:id")))
        elif tag == qn("w:commentRangeEnd"):
            open_ids.discard(el.get(qn("w:id")))
        elif tag == qn("w:t") and open_ids:
            text = el.text or ""
            if text:
                for cid in open_ids:
                    anchors.setdefault(cid, []).append(text)
    return {cid: "".join(parts) for cid, parts in anchors.items()}


def _paragraph_text_of(el: Any) -> str:
    """Nearest ``w:p`` ancestor's full text ('' when outside a paragraph)."""
    node = el
    while node is not None and node.tag != qn("w:p"):
        node = node.getparent()
    if node is None:
        return ""
    return "".join(t.text or "" for t in node.iter(qn("w:t")))


def _anchor_fallback_text(doc_el: Any, cid: str) -> str:
    """Paragraph context when a comment's anchored range carries no text.

    Prefers the paragraph holding the ``commentRangeStart``; a point comment
    without range markers falls back to the ``commentReference`` paragraph.
    """
    for tag in ("w:commentRangeStart", "w:commentReference"):
        for el in doc_el.iter(qn(tag)):
            if el.get(qn("w:id")) == cid:
                text = _paragraph_text_of(el)
                if text:
                    return text
    return ""


def read_docx_comments(file_path: Path) -> WordCommentsResult:
    """Read all comments from a .docx (批次 3.3).

    Each comment's anchoring text is resolved from the
    ``commentRangeStart/End`` pair with the same ``w:id`` in document.xml;
    comments anchored to an empty range (or a bare insertion point) report
    the surrounding paragraph text instead.

    Args:
        file_path: Absolute path to the .docx file.

    Returns:
        WordCommentsResult (empty ``comments`` list when the file has no
        comments part).

    Raises:
        OfficeFileNotFoundError: file doesn't exist.
        OfficeParseError: file exists but isn't a valid DOCX (or its comments
            part is corrupt).
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise OfficeFileNotFoundError(file_path)
    if not file_path.is_file():
        raise OfficeParseError(f"Path is not a regular file: {file_path}", file_path=file_path)

    try:
        doc = Document(str(file_path))
    except Exception as exc:
        raise OfficeParseError(f"Failed to parse DOCX: {exc}", file_path=file_path) from exc

    return WordCommentsResult(comments=_extract_comments(doc, file_path))


# ──────────────────────────────────────────────────────────────────────
# Generator (Phase 1.4 step 19, plan §4.1.4)
# ──────────────────────────────────────────────────────────────────────


#: WordParagraphSpec.align → docx enum（批次 2.3）。
_ALIGN_TO_DOCX = {
    "left": "LEFT",
    "center": "CENTER",
    "right": "RIGHT",
    "justify": "JUSTIFY",
}


def _normalize_hex_color(color: str) -> Optional[str]:
    """'FF0000' / '#ff0000' → 'FF0000'；非法返回 None（批次 2.3）。"""
    hex_text = str(color).strip().lstrip("#")
    if len(hex_text) != 6 or any(c not in "0123456789abcdefABCDEF" for c in hex_text):
        return None
    return hex_text.upper()


def _apply_paragraph_run_style(para, spec) -> int:
    """把 WordParagraphSpec 的可选样式（font_size/bold/italic/color/align）
    施加到刚创建段落的全部 runs（批次 2.3 样式分级 round a）。

    全部字段缺省时不做任何修改（保持既有生成物逐字节语义）。返回处理
    的 run 数。
    """
    fields = ("font_size", "bold", "italic", "color", "align")
    if all(getattr(spec, f, None) is None for f in fields):
        return 0

    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    align = getattr(spec, "align", None)
    if align is not None:
        para.alignment = getattr(WD_ALIGN_PARAGRAPH, _ALIGN_TO_DOCX[align])

    rgb = None
    color = getattr(spec, "color", None)
    if color is not None:
        normalized = _normalize_hex_color(color)
        if normalized is None:
            from .errors import OfficeGenerateError

            raise OfficeGenerateError(f"invalid_color: {color!r}（需 6 位 RGB hex）")
        rgb = RGBColor.from_string(normalized)

    font_size = getattr(spec, "font_size", None)
    for run in para.runs:
        if font_size is not None:
            run.font.size = Pt(float(font_size))
        if getattr(spec, "bold", None) is not None:
            run.font.bold = bool(spec.bold)
        if getattr(spec, "italic", None) is not None:
            run.font.italic = bool(spec.italic)
        if rgb is not None:
            run.font.color.rgb = rgb
    return len(para.runs)


def generate_docx(req, output_dir: Optional[str] = None) -> Path:
    """Generate a .docx file from structured Pydantic input.

    ``output_dir`` 提供时写入该任意目录（信任的用户指定目录，经
    :func:`resolve_output_path` 校验文件名）；``None`` 时保持现状写
    workspace 沙箱（``<workspace>/office/word/<id>/<name>``）。
    """
    import uuid

    from docx import Document as _Doc

    from .errors import OfficeGenerateError
    from .models import OfficeDocType
    from .path_safety import managed_document_path, resolve_output_path
    from .storage import validate_workspace

    if output_dir is not None:
        output_path = resolve_output_path(output_dir, OfficeDocType.WORD, req.filename)
    else:
        workspace = validate_workspace(Path(req.workspace_path))
        doc_id = uuid.uuid4().hex
        output_path = managed_document_path(workspace, OfficeDocType.WORD, doc_id, req.filename)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        doc = _Doc()
        # ★ 新增：显式设置字体（修"字体奇怪"bug）
        ascii_font = getattr(req, "ascii_font", None) or DEFAULT_ASCII_FONT
        ea_font = getattr(req, "font_family", None) or DEFAULT_EA_FONT
        set_doc_default_font(doc, ascii_font, ea_font)

        # Title
        doc.add_heading(req.title, level=0)
        # Body paragraphs
        for para in req.paragraphs:
            if para.heading == "h1":
                created = doc.add_heading(para.text, level=1)
            elif para.heading == "h2":
                created = doc.add_heading(para.text, level=2)
            elif para.heading == "h3":
                created = doc.add_heading(para.text, level=3)
            elif para.style == "bullet":
                # ★ 新增：bullet 列表
                created = doc.add_paragraph(para.text, style="List Bullet")
            elif para.style == "numbered":
                # ★ 新增：numbered 列表
                created = doc.add_paragraph(para.text, style="List Number")
            else:
                created = doc.add_paragraph(para.text)
            # 批次 2.3：可选段落级样式（无样式字段时零改动）
            _apply_paragraph_run_style(created, para)
        # Tables
        for table_spec in req.tables:
            table = doc.add_table(rows=1 + len(table_spec.rows), cols=len(table_spec.headers))
            # Header row
            for ci, header in enumerate(table_spec.headers):
                table.cell(0, ci).text = header
            # Data rows
            for ri, row in enumerate(table_spec.rows):
                for ci, cell in enumerate(row):
                    if ci < len(table_spec.headers):
                        table.cell(ri + 1, ci).text = cell
        # 批次 2.1：可选插图，按顺序追加在正文之后。
        images = list(getattr(req, "images", None) or [])
        if images:
            from .charts import image_bytes_to_stream, resolve_image_payload

            search_dirs = [output_path.parent]
            if req.workspace_path:
                search_dirs.insert(0, Path(req.workspace_path))
            from docx.shared import Inches

            for image in images:
                payload = resolve_image_payload(image.source, search_dirs=search_dirs)
                width = Inches(image.width_inches) if image.width_inches else None
                height = Inches(image.height_inches) if image.height_inches else None
                doc.add_picture(image_bytes_to_stream(payload), width=width, height=height)
        doc.save(str(output_path))
    except Exception as exc:
        raise OfficeGenerateError(f"Failed to generate DOCX: {exc}", file_path=output_path) from exc

    return output_path
