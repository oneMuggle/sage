"""聊天附件 PDF 页级解析与图表抽取（2026-11-15）。

原聊天上传路径只用 PyMuPDF 逐页取文本后按换行拼接，页边界、插图与图注
全部丢失。本模块把 PDF 解析提升为「页感知 + 图清单」：

- ``extract_pdf_pages``：逐页取文本，纯图页复用 office OCR 兜底（SAGE_OCR 门控）；
- ``render_page_marked_text``：输出 ``--- page N ---`` 分隔文本，模型可标注页码；
- ``extract_pdf_figures``：抽取嵌入位图，过滤图标/整页扫描背景/重复图，附页内 bbox 与图注；
- ``get_or_build_figure_manifest``：裁图落 MediaStore，清单缓存到媒体旁
  ``<id>.figures.json``，供发送侧注入 ``<attached_figures>``。

解析失败一律 fail-safe：调用方拿到空结果继续聊天，绝不阻断主流程。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.services.multimodal.media_store import MediaKind, MediaRef, MediaStore

logger = logging.getLogger(__name__)

PAGE_MARKER_TEMPLATE = "--- page {page} ---"
_PAGE_MARKER_RE = re.compile(r"^--- page (\d+) ---$", re.MULTILINE)
#: 图注识别：中文「图 1」/「表 2」或英文 Figure/Fig./Table + 序号
_CAPTION_RE = re.compile(
    r"^\s*(图|表|Figure|Fig\.?|Table)\s*[0-9一二三四五六七八九十百]+",
    re.IGNORECASE,
)

FIGURES_MANIFEST_VERSION = 1
MAX_FIGURES = 40
MIN_FIGURE_WIDTH = 80
MIN_FIGURE_HEIGHT = 60
MAX_FIGURE_BYTES = 5 * 1024 * 1024
#: 图片占页面积 ≥ 该比例视为扫描背景/整页底图，不当作图引用
_FULL_PAGE_AREA_RATIO = 0.85
#: 图注在图片下方的搜索距离（pt）
_CAPTION_SEARCH_POINTS = 120.0

#: 注入到动态上下文的引用说明（整个请求只出现一次）
FIGURE_REFERENCE_HINT = (
    "[附件图片引用说明] 回答涉及 <attached_figures> 中的图片时，在对应位置"
    '使用 Markdown 图片语法 ![简短图注](media属性值 "第N页 · 图X") 内联展示原图；'
    "引用 PDF 正文时标注页码（例如「第 12 页」）。"
)


@dataclass(frozen=True)
class PdfPageText:
    """单页文本（page_number 为 1 起始的真实页码）。"""

    page_number: int
    text: str


@dataclass(frozen=True)
class ExtractedFigure:
    """抽取出的单张插图（尚未落盘）。"""

    page_number: int
    index_in_page: int
    image_bytes: bytes
    ext: str
    width: int
    height: int
    bbox: Tuple[float, float, float, float]
    caption: str


def _open_pdf(content: bytes) -> Any:
    """惰性打开内存 PDF（pymupdf 仅在上传/发送 PDF 时加载）。"""
    from backend.core.lazy import load_module

    pymupdf = load_module("pymupdf", "pymupdf", globals())
    return pymupdf.open(stream=content, filetype="pdf")


def extract_pdf_pages(content: bytes) -> List[PdfPageText]:
    """逐页取文本；文本层为空时走 office OCR 兜底（受 SAGE_OCR=1 门控）。"""
    doc = _open_pdf(content)
    pages: List[PdfPageText] = []
    try:
        # 运行期导入，便于测试 monkeypatch backend.office.ocr.ocr_page_if_needed
        from backend.office.ocr import ocr_page_if_needed

        for index in range(len(doc)):
            page = doc[index]
            text = page.get_text() or ""
            ocr_text = ocr_page_if_needed(page, text)
            if ocr_text is not None:
                text = ocr_text
            pages.append(PdfPageText(page_number=index + 1, text=text))
    finally:
        doc.close()
    return pages


def render_page_marked_text(pages: List[PdfPageText]) -> str:
    """把逐页文本渲染成 ``--- page N ---`` 分隔的注入文本；空页跳过。"""
    parts: List[str] = []
    for page in pages:
        stripped = (page.text or "").strip()
        if not stripped:
            continue
        parts.append(PAGE_MARKER_TEMPLATE.format(page=page.page_number) + "\n" + stripped)
    return "\n\n".join(parts)


def count_page_markers(text: str) -> int:
    """注入文本中的页标记数量（附件状态展示用）。"""
    return len(_PAGE_MARKER_RE.findall(text or ""))


def _text_blocks(page: Any) -> List[Tuple[float, float, float, float, str]]:
    """取页内文本块（x0, y0, x1, y1, text），忽略图片块与空块。"""
    try:
        raw_blocks = page.get_text("blocks")
    except Exception as exc:  # noqa: BLE001 — 布局解析失败按无文本处理
        logger.debug("PDF 文本块解析失败: %s", exc)
        return []
    blocks: List[Tuple[float, float, float, float, str]] = []
    for block in raw_blocks:
        if len(block) < 5:
            continue
        # blocks 元组第 7 位是块类型（0=文本，1=图片）
        if len(block) >= 7 and block[6] != 0:
            continue
        text = str(block[4] or "").strip()
        if not text:
            continue
        blocks.append((float(block[0]), float(block[1]), float(block[2]), float(block[3]), text))
    return blocks


def _caption_for_rect(
    blocks: List[Tuple[float, float, float, float, str]], rect: Any
) -> str:
    """在图片下方找图注：优先「图/表/Figure」开头，否则取最近的一段文本。"""
    below = [
        block
        for block in blocks
        if block[1] >= rect.y1 - 8.0 and block[1] <= rect.y1 + _CAPTION_SEARCH_POINTS
    ]
    below.sort(key=lambda block: block[1])
    for block in below:
        if _CAPTION_RE.match(block[4]):
            return block[4][:200]
    if below:
        return below[0][4][:120]
    return ""


def extract_pdf_figures(
    content: bytes,
    *,
    max_figures: int = MAX_FIGURES,
    min_width: int = MIN_FIGURE_WIDTH,
    min_height: int = MIN_FIGURE_HEIGHT,
    max_figure_bytes: int = MAX_FIGURE_BYTES,
) -> List[ExtractedFigure]:
    """抽取 PDF 内嵌位图（含页号/bbox/图注）。

    过滤：小图标、整页扫描背景、跨页/跨文档重复图；单文档限额 ``max_figures``。
    矢量图（Office 图表、LaTeX 绘图）不在本函数覆盖范围内。
    """
    doc = _open_pdf(content)
    figures: List[ExtractedFigure] = []
    seen_hashes: set = set()
    try:
        for page_index in range(len(doc)):
            page = doc[page_index]
            page_area = max(float(page.rect.width) * float(page.rect.height), 1.0)
            blocks = _text_blocks(page)
            seen_xrefs: set = set()
            index_in_page = 0
            for image_info in page.get_images(full=True):
                if len(image_info) < 3:
                    continue
                xref = int(image_info[0])
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)
                width, height = int(image_info[2]), int(image_info[3])
                if width < min_width or height < min_height:
                    continue
                rects = page.get_image_rects(xref)
                if not rects:
                    continue
                rect = rects[0]
                rect_area = max(float(rect.width), 0.0) * max(float(rect.height), 0.0)
                if rect_area <= 0 or rect_area / page_area >= _FULL_PAGE_AREA_RATIO:
                    continue
                try:
                    info = doc.extract_image(xref)
                except Exception as exc:  # noqa: BLE001 — 单张图失败跳过
                    logger.debug("PDF 图片提取失败 xref=%s: %s", xref, exc)
                    continue
                image_bytes = info.get("image") or b""
                if not image_bytes or len(image_bytes) > max_figure_bytes:
                    continue
                digest = hashlib.sha1(image_bytes).hexdigest()
                if digest in seen_hashes:
                    continue
                seen_hashes.add(digest)
                index_in_page += 1
                figures.append(
                    ExtractedFigure(
                        page_number=page_index + 1,
                        index_in_page=index_in_page,
                        image_bytes=image_bytes,
                        ext=str(info.get("ext") or "png").lstrip(".").lower() or "png",
                        width=width,
                        height=height,
                        bbox=(
                            float(rect.x0),
                            float(rect.y0),
                            float(rect.x1),
                            float(rect.y1),
                        ),
                        caption=_caption_for_rect(blocks, rect),
                    )
                )
                if len(figures) >= max_figures:
                    return figures
    finally:
        doc.close()
    return figures


def figures_manifest_path(media_file: Path) -> Path:
    """图表清单路径：与媒体文件同目录的 ``<stem>.figures.json``。"""
    media_file = Path(media_file)
    return media_file.with_name(media_file.stem + ".figures.json")


def _read_manifest(path: Path) -> Optional[List[Dict[str, Any]]]:
    """读缓存清单；版本不符/损坏/结构异常 → None（触发重建）。"""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != FIGURES_MANIFEST_VERSION:
        return None
    figures = data.get("figures")
    if not isinstance(figures, list):
        return None
    entries: List[Dict[str, Any]] = []
    for item in figures:
        if not isinstance(item, dict) or not item.get("media_id"):
            return None
        entries.append(item)
    return entries


def _write_manifest(path: Path, source_media_id: str, figures: List[Dict[str, Any]]) -> None:
    """原子写清单；失败仅告警（下次调用会重建）。"""
    payload = {
        "version": FIGURES_MANIFEST_VERSION,
        "source_media_id": source_media_id,
        "figures": figures,
    }
    tmp_path = path.with_name(path.name + ".tmp")
    try:
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(path)
    except OSError as exc:
        logger.warning("图表清单写入失败 %s: %s", path, exc)


def get_or_build_figure_manifest(
    store: MediaStore, media_ref: MediaRef, content: bytes
) -> List[Dict[str, Any]]:
    """读取或构建 PDF 图表清单（裁图落 MediaStore，清单缓存到媒体旁）。"""
    media_file = store.root / media_ref.file_path
    manifest_path = figures_manifest_path(media_file)
    cached = _read_manifest(manifest_path)
    if cached is not None:
        return cached

    try:
        extracted = extract_pdf_figures(content)
    except Exception as exc:  # noqa: BLE001 — 图抽取失败不阻断聊天
        logger.warning("PDF 图表抽取失败（跳过） %s: %s", media_ref.id, exc)
        extracted = []

    original = str((media_ref.metadata or {}).get("original_filename") or media_ref.id)
    stem = Path(original).stem or media_ref.id
    entries: List[Dict[str, Any]] = []
    for figure in extracted:
        figure_id = f"f-p{figure.page_number}-{figure.index_in_page}"
        try:
            figure_ref = store.save(
                figure.image_bytes,
                MediaKind.IMAGE,
                source="pdf_figure",
                metadata={
                    "original_filename": (
                        f"{stem}-p{figure.page_number}-f{figure.index_in_page}.{figure.ext}"
                    ),
                    "source_media_id": media_ref.id,
                    "page": figure.page_number,
                    "figure_id": figure_id,
                    "caption": figure.caption,
                },
                ext=figure.ext,
            )
        except Exception as exc:  # noqa: BLE001 — 单张图落盘失败跳过
            logger.warning("图表落盘失败 %s: %s", figure_id, exc)
            continue
        entries.append(
            {
                "figure_id": figure_id,
                "page": figure.page_number,
                "caption": figure.caption,
                "media_id": figure_ref.id,
                "media_url": figure_ref.api_url,
                "width": figure.width,
                "height": figure.height,
                "bbox": [round(value, 1) for value in figure.bbox],
            }
        )

    _write_manifest(manifest_path, media_ref.id, entries)
    return entries


def _safe_attr(value: str) -> str:
    """注入 XML 属性前的轻量清洗（去引号/尖括号/换行）。"""
    return (
        str(value)
        .replace("'", "’")
        .replace('"', "”")
        .replace("<", "")
        .replace(">", "")
        .replace("\n", " ")
        .strip()
    )


def render_figure_manifest_xml(filename: str, figures: List[Dict[str, Any]]) -> str:
    """渲染 ``<attached_figures>`` 注入块；无图返回空串。"""
    if not figures:
        return ""
    lines = [f'<attached_figures document="{_safe_attr(filename)}">']
    for figure in figures:
        figure_id = _safe_attr(str(figure.get("figure_id") or ""))
        page = int(figure.get("page") or 0)
        caption = _safe_attr(str(figure.get("caption") or ""))
        media = _safe_attr(str(figure.get("media_url") or ""))
        lines.append(
            f'<figure id="{figure_id}" page="{page}" caption="{caption}" media="{media}" />'
        )
    lines.append("</attached_figures>")
    return "\n".join(lines)
