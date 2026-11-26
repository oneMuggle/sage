"""Word 模板整块结构填充（P0）：无占位符模板的段落克隆与内容替换。

与 ``word_template_profile_fill``（占位符/内容控件/书签槽位）互补：
真实模板（软著说明书、合同、公文体）通常没有占位符，只有带直接格式的
示例段落。本模块把模板中的 h1/h2/h3/正文/加粗段落当作“块模板”，按
内容块列表深拷贝并替换文字，保留模板的段落直接格式与样式。

安全约定：
- 输出永不覆盖模板或已存在文件；临时文件 + 原子替换；
- 模板/输出均需落在 workspace 内（``resolve_within``）；
- 含书签/域/分节符的块模板拒绝使用（克隆会复制冲突 id）。
"""

from __future__ import annotations

import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .errors import (
    OfficeFileNotFoundError,
    OfficeParseError,
    OfficePathError,
    OfficeTemplateFillError,
)
from .path_safety import resolve_within
from .word_template import _validate_docx_zip

#: 块类型（与 models.WordTemplateBlock.kind 对齐）
_BLOCK_KINDS = ("h1", "h2", "h3", "body", "bold")

#: 禁止克隆的段落内容（域在克隆时会复制缓存值与指令，打断文档语义；
#: 书签与 lastRenderedPageBreak 在克隆时剥离而非拒绝——真实模板的标题
#: 段落常带历史 TOC 书签锚点）
_FORBIDDEN_TAGS = ("w:fldChar", "w:fldSimple")

#: 克隆时从副本中移除的元素（避免重复 id / 陈旧分页标记）
_STRIPPED_TAGS = ("w:bookmarkStart", "w:bookmarkEnd", "w:lastRenderedPageBreak")


# docx 仅在真正执行填充时加载（启动路径不触发）
def __getattr__(name: str) -> Any:
    from backend.core.lazy import load_attr

    if name == "Document":
        return load_attr("docx", "Document", globals())
    if name == "OxmlElement":
        return load_attr("docx.oxml", "OxmlElement", globals())
    if name == "qn":
        return load_attr("docx.oxml.ns", "qn", globals())
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _check_output_name(name: str) -> str:
    value = (name or "").strip()
    if not value:
        raise OfficeTemplateFillError("output_filename 不能为空")
    if Path(value).is_absolute() or "/" in value or "\\" in value:
        raise OfficeTemplateFillError("output_filename 不能包含路径分隔符")
    if value in (".", ".."):
        raise OfficeTemplateFillError("output_filename 非法")
    return value


def _outline_level(paragraph) -> Optional[int]:
    """段落有效大纲级别：直接格式 w:outlineLvl 优先，其次 Heading N 样式名。"""
    from backend.core.lazy import load_attr

    qn = load_attr("docx.oxml.ns", "qn", globals())
    pPr = paragraph._p.pPr
    if pPr is not None:
        ol = pPr.find(qn("w:outlineLvl"))
        if ol is not None:
            try:
                return int(ol.get(qn("w:val")))
            except (TypeError, ValueError):
                return None
    style_name = (getattr(paragraph.style, "name", "") or "").lower()
    if style_name.startswith("heading "):
        try:
            return int(style_name.split()[-1]) - 1
        except ValueError:
            return None
    return None


def _max_run_size(paragraph) -> float:
    sizes = [r.font.size.pt for r in paragraph.runs if r.font.size is not None]
    return max(sizes) if sizes else 0.0


def _is_bold(paragraph) -> bool:
    runs = [r for r in paragraph.runs if (r.text or "").strip()]
    return bool(runs) and all(bool(r.bold) for r in runs)


def _has_first_line_indent(paragraph) -> bool:
    from backend.core.lazy import load_attr

    qn = load_attr("docx.oxml.ns", "qn", globals())
    pPr = paragraph._p.pPr
    if pPr is None:
        return False
    ind = pPr.find(qn("w:ind"))
    if ind is None:
        return False
    return bool(ind.get(qn("w:firstLine")) or ind.get(qn("w:firstLineChars")))


def _heading_anchors(paragraphs: List[Any]) -> Dict[str, int]:
    anchors: Dict[str, int] = {}
    for index, paragraph in enumerate(paragraphs):
        level = _outline_level(paragraph)
        if level in (0, 1, 2):
            anchors.setdefault(("h1", "h2", "h3")[level], index)
    return anchors


def _body_anchors(paragraphs: List[Any], start: int, end: int) -> Dict[str, int]:
    body_index: Optional[int] = None
    bold_index: Optional[int] = None
    for index in range(start, end):
        paragraph = paragraphs[index]
        if not paragraph.text.strip() or _outline_level(paragraph) is not None:
            continue
        size = _max_run_size(paragraph)
        if size and size > 14:
            continue
        if body_index is None and _has_first_line_indent(paragraph) and not _is_bold(
            paragraph
        ):
            body_index = index
        if bold_index is None and _is_bold(paragraph):
            bold_index = index
    if body_index is None:
        for index in range(start, end):
            paragraph = paragraphs[index]
            if paragraph.text.strip() and _outline_level(paragraph) is None:
                body_index = index
                break
    anchors: Dict[str, int] = {}
    if body_index is not None:
        anchors["body"] = body_index
    if bold_index is not None:
        anchors["bold"] = bold_index
    return anchors


def _find_text(paragraphs: List[Any], text: str, start: int = 0) -> int:
    needle = (text or "").strip()
    if not needle:
        return -1
    for index in range(start, len(paragraphs)):
        if paragraphs[index].text.strip().startswith(needle):
            return index
    return -1


def _validate_anchor(key: str, value: Any, count: int, source: str) -> int:
    if key not in _BLOCK_KINDS:
        raise OfficeTemplateFillError(f"未知的锚点类型: {key}")
    if isinstance(value, bool) or not isinstance(value, int):
        raise OfficeTemplateFillError(f"{source}锚点 {key} 必须是段落索引（整数）")
    if value < 0 or value >= count:
        raise OfficeTemplateFillError(
            f"{source}锚点 {key}={value} 越界（共 {count} 段）"
        )
    return value


def _assert_cloneable(paragraph, kind: str) -> None:
    from backend.core.lazy import load_attr

    qn = load_attr("docx.oxml.ns", "qn", globals())
    element = paragraph._p
    for tag in _FORBIDDEN_TAGS:
        if element.find(qn(tag)) is not None:
            raise OfficeTemplateFillError(
                f"块模板 {kind} 含域（fldChar/fldSimple），克隆会复制域指令；"
                "请用 anchors 指定其他段落"
            )
    pPr = element.pPr
    if pPr is not None and pPr.find(qn("w:sectPr")) is not None:
        raise OfficeTemplateFillError(
            f"块模板 {kind} 含分节符，不能用于克隆；请用 anchors 指定其他段落"
        )
    if paragraph.text.strip() and not element.findall(qn("w:r")):
        raise OfficeTemplateFillError(
            f"块模板 {kind} 为复杂结构（超链接/控件），暂不支持克隆"
        )


def _clone_with_text(template_element, text: str):
    from backend.core.lazy import load_attr

    qn = load_attr("docx.oxml.ns", "qn", globals())
    OxmlElement = load_attr("docx.oxml", "OxmlElement", globals())
    new_element = deepcopy(template_element)
    # 剥离书签/分页标记：克隆会产生重复 bookmark id 或陈旧分页断点
    for tag in _STRIPPED_TAGS:
        for element in list(new_element.iter(qn(tag))):
            element.getparent().remove(element)
    runs = new_element.findall(qn("w:r"))
    if runs:
        first = runs[0]
        for child in list(first):
            if child.tag != qn("w:rPr"):
                first.remove(child)
        new_text = OxmlElement("w:t")
        new_text.set(qn("xml:space"), "preserve")
        new_text.text = text
        first.append(new_text)
        for extra in runs[1:]:
            new_element.remove(extra)
    else:
        run = OxmlElement("w:r")
        new_text = OxmlElement("w:t")
        new_text.set(qn("xml:space"), "preserve")
        new_text.text = text
        run.append(new_text)
        new_element.append(run)
    return new_element


def _normalize_blocks(blocks: Any) -> List[Tuple[str, str]]:
    if not isinstance(blocks, (list, tuple)) or not blocks:  # noqa: UP038
        raise OfficeTemplateFillError("blocks 不能为空")
    if len(blocks) > 5000:
        raise OfficeTemplateFillError("blocks 数量超过上限（5000）")
    normalized: List[Tuple[str, str]] = []
    for index, block in enumerate(blocks):
        if isinstance(block, dict):
            kind = block.get("kind")
            text = block.get("text")
        else:
            kind = getattr(block, "kind", None)
            text = getattr(block, "text", None)
        if kind not in _BLOCK_KINDS:
            raise OfficeTemplateFillError(f"blocks[{index}].kind 非法: {kind!r}")
        if not isinstance(text, str) or not text.strip():
            raise OfficeTemplateFillError(f"blocks[{index}].text 不能为空")
        if len(text) > 10000:
            raise OfficeTemplateFillError(f"blocks[{index}].text 过长")
        normalized.append((kind, text))
    return normalized


def fill_word_template_blocks(
    template_path: Path,
    blocks: Any,
    output_filename: str,
    *,
    workspace_path: str,
    anchors: Optional[Dict[str, int]] = None,
    start_anchor_text: Optional[str] = None,
    end_anchor_text: Optional[str] = None,
    start_paragraph: Optional[int] = None,
    end_paragraph: Optional[int] = None,
) -> Dict[str, Any]:
    """按内容块列表克隆模板段落并写出新 .docx（模板永不修改）。"""
    root = Path(workspace_path).resolve()
    if not root.is_dir():
        raise OfficeParseError("工作区目录不存在")
    template = Path(template_path)
    if not template.is_file():
        raise OfficeFileNotFoundError(template)
    if template.suffix.lower() != ".docx":
        raise OfficeParseError("仅支持 .docx 模板")
    resolved = resolve_within(root, template)
    _validate_docx_zip(resolved)

    block_items = _normalize_blocks(blocks)
    wanted = tuple(dict.fromkeys(kind for kind, _ in block_items))

    from backend.core.lazy import load_attr

    Document = load_attr("docx", "Document", globals())
    qn = load_attr("docx.oxml.ns", "qn", globals())
    try:
        document = Document(str(resolved))
    except Exception as exc:  # noqa: BLE001
        raise OfficeParseError(f"Failed to parse DOCX template: {exc}") from exc

    paragraphs = list(document.paragraphs)
    if not paragraphs:
        raise OfficeTemplateFillError("模板没有正文段落")

    detected = _heading_anchors(paragraphs)
    explicit = dict(anchors or {})
    for key, value in explicit.items():
        explicit[key] = _validate_anchor(key, value, len(paragraphs), "显式")

    start = None
    if start_paragraph is not None:
        start = _validate_anchor("body", start_paragraph, len(paragraphs), "start_")
    elif start_anchor_text:
        start = _find_text(paragraphs, start_anchor_text)
        if start < 0:
            raise OfficeTemplateFillError(
                f"未找到起始锚点文本: {start_anchor_text}"
            )
    elif "h1" in explicit:
        start = explicit["h1"]
    elif "h1" in detected:
        start = detected["h1"]
    if start is None:
        raise OfficeTemplateFillError(
            "无法确定正文起点：请提供 start_paragraph / start_anchor_text / h1 锚点"
        )

    if end_paragraph is not None:
        if (
            isinstance(end_paragraph, bool)
            or not isinstance(end_paragraph, int)
            or end_paragraph < 0
            or end_paragraph > len(paragraphs)
        ):
            raise OfficeTemplateFillError(
                f"end_锚点越界: end_paragraph={end_paragraph}（共 {len(paragraphs)} 段，允许等于段数）"
            )
        end = end_paragraph
        if end < start:
            raise OfficeTemplateFillError("end_paragraph 不能小于起点")
    elif end_anchor_text:
        end = _find_text(paragraphs, end_anchor_text, start + 1)
        if end < 0:
            raise OfficeTemplateFillError(f"未找到结束锚点文本: {end_anchor_text}")
    else:
        end = len(paragraphs)

    merged = dict(detected)
    merged.update(_body_anchors(paragraphs, start, end))
    merged.update(explicit)

    missing = [kind for kind in wanted if kind not in merged]
    if missing:
        raise OfficeTemplateFillError(
            "缺少块模板段落: " + ", ".join(missing) + "；可用 anchors 显式指定"
        )
    for kind in wanted:
        _assert_cloneable(paragraphs[merged[kind]], kind)

    body = document.element.body
    insert_before = (
        paragraphs[end]._p
        if end < len(paragraphs)
        else body.find(qn("w:sectPr"))
    )
    for index in range(start, end):
        paragraphs[index]._p.getparent().remove(paragraphs[index]._p)
    for kind, text in block_items:
        element = _clone_with_text(paragraphs[merged[kind]]._p, text)
        if insert_before is not None:
            insert_before.addprevious(element)
        else:
            body.append(element)

    output_name = _check_output_name(output_filename)
    try:
        target = resolve_within(root, resolved.parent / output_name)
    except OfficePathError as exc:
        raise OfficeTemplateFillError("输出路径不在工作区内") from exc
    if target == resolved:
        raise OfficeTemplateFillError("输出文件不能覆盖模板")
    if target.exists():
        raise OfficeTemplateFillError("输出文件已存在，拒绝覆盖")

    work_path = target.with_name(f".{target.stem}.{uuid.uuid4().hex}.refill.docx")
    try:
        document.save(str(work_path))
        work_path.replace(target)
    except OSError as exc:
        raise OfficeTemplateFillError(f"写入输出文件失败: {exc}") from exc
    finally:
        try:
            if work_path.exists():
                work_path.unlink()
        except OSError:
            pass

    warnings: List[Dict[str, str]] = []
    if "bold" in wanted and merged.get("bold") == merged.get("body"):
        warnings.append(
            {
                "code": "bold_fallback_body",
                "message": "模板未识别到独立加粗段落，bold 块沿用正文段落样式",
            }
        )
    return {
        "ok": True,
        "template_path": _rel(resolved, root),
        "output_path": target.relative_to(root).as_posix(),
        "filename": output_name,
        "inserted_blocks": len(block_items),
        "removed_paragraphs": end - start,
        "anchors": merged,
        "warnings": warnings,
    }


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.name


__all__ = ["fill_word_template_blocks"]
