"""已有 Word 文档套用样式模板（样式画像）。

与生成期 ``apply_format_spec`` 的差别：

- 只应用样式定义（页面/正文/标题），不触碰目录/编号/参考文献等生成期
  特性，也不改写既有页眉页脚文本——避免覆盖用户原文；
- 题注/表格文字样式只对生成期内容生效，对既有文档跳过并给出 warning；
- 可选清除 run 级直接字体格式（``w:rFonts`` / ``w:sz`` / ``w:szCs`` /
  ``w:color``），保留加粗/斜体等语义强调——直接格式会覆盖样式定义，
  是 markdown 转出的文档最常见的样式漂移来源；
- 默认输出 ``<stem>-styled.docx``，``overwrite=True`` 时临时文件原子替换；
- 支持 ``dry_run``（只看会改哪些样式，不落盘）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ._docx_lazy import Document, qn
from .errors import OfficeGenerateError
from .models import WordFormatSpec
from .path_safety import resolve_within
from .storage import validate_workspace
from .word_layout import _HEADING_STYLE_NAMES, apply_style_definitions
from .word_lint import _style_font_names

#: 套用样式的大小上限（与批量审校同量级）
MAX_STYLE_APPLY_BYTES = 50 * 1024 * 1024

#: 快照覆盖的样式：正文/标题/各级标题
_TRACKED_STYLES = ("Normal", "Title") + tuple(_HEADING_STYLE_NAMES.values())

#: 清理直接格式时移除的 run 级元素（字体/字号/颜色；保留 b/i/u 语义强调）
_CLEAR_RUN_TAGS = ("w:rFonts", "w:sz", "w:szCs", "w:color")


def _line_spacing_repr(value: Any) -> Any:
    """行距归一为可比较值：固定行距 → pt 数值；倍数 → 四舍五入浮点。"""
    if value is None:
        return None
    if hasattr(value, "pt"):
        return round(float(value.pt), 2)
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):  # pragma: no cover — 防御
        return value


def _style_snapshot(doc: Document) -> Dict[str, Dict[str, Any]]:
    snapshot: Dict[str, Dict[str, Any]] = {}
    for name in _TRACKED_STYLES:
        try:
            style = doc.styles[name]
        except KeyError:
            continue
        east_font, ascii_font = _style_font_names(style)
        fmt = style.paragraph_format
        alignment = fmt.alignment
        snapshot[name] = {
            "font_family": east_font,
            "ascii_font": ascii_font,
            "font_size_pt": (
                round(float(style.font.size.pt), 2)
                if style.font.size is not None
                else None
            ),
            "bold": (
                bool(style.font.bold) if style.font.bold is not None else None
            ),
            "line_spacing": _line_spacing_repr(fmt.line_spacing),
            "align": alignment.name.lower() if alignment is not None else None,
        }
    return snapshot


def _style_changes(
    before: Dict[str, Dict[str, Any]], after: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    changes: List[Dict[str, Any]] = []
    for name, prior in before.items():
        current = after.get(name)
        if current is None:
            continue
        fields = {
            key: {"before": prior[key], "after": current[key]}
            for key in prior
            if prior[key] != current[key]
        }
        if fields:
            changes.append({"style": name, "fields": fields})
    return changes


def _clear_run_direct_formatting(doc: Document) -> int:
    """清除正文/表格 runs 的直接字体格式，返回清理的 run 数。"""
    count = 0

    def clean(paragraph: Any) -> None:
        nonlocal count
        for run in paragraph.runs:
            rPr = run._r.find(qn("w:rPr"))
            if rPr is None:
                continue
            touched = False
            for tag in _CLEAR_RUN_TAGS:
                element = rPr.find(qn(tag))
                if element is not None:
                    rPr.remove(element)
                    touched = True
            if touched:
                count += 1

    for paragraph in doc.paragraphs:
        clean(paragraph)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    clean(paragraph)
    return count


def _resolve_document_path(
    file_path: Path, workspace_path: Optional[str]
) -> Path:
    raw = Path(file_path)
    if workspace_path:
        workspace = validate_workspace(Path(workspace_path))
        candidate = raw if raw.is_absolute() else workspace / raw
        candidate = resolve_within(workspace, candidate)
    elif raw.is_absolute():
        candidate = raw
    else:
        raise OfficeGenerateError("file_path 需为绝对路径或提供 workspace_path")
    if candidate.suffix.lower() != ".docx":
        raise OfficeGenerateError(f"仅支持 .docx 文档: {candidate.name}")
    if not candidate.is_file():
        raise OfficeGenerateError(f"文档不存在: {candidate}")
    if candidate.stat().st_size > MAX_STYLE_APPLY_BYTES:
        raise OfficeGenerateError(
            f"文档超过 {MAX_STYLE_APPLY_BYTES // (1024 * 1024)}MB: {candidate}"
        )
    return candidate


def apply_style_to_document(
    file_path: Path,
    spec: WordFormatSpec,
    *,
    workspace_path: Optional[str] = None,
    clear_direct_formatting: bool = False,
    dry_run: bool = False,
    overwrite: bool = False,
    output_filename: Optional[str] = None,
) -> Dict[str, Any]:
    """按样式画像重排已有文档的样式定义。

    返回 dict（ok / dry_run / saved / output_path / styles_changed /
    direct_runs_cleared / warnings）。``styles_changed`` 为逐样式字段
    before/after 列表，幂等应用时为空。
    """
    if spec is None:
        raise OfficeGenerateError("style/apply 需要样式规范（preset 或 format_spec）")
    from .edit import _atomic_replace

    source = _resolve_document_path(file_path, workspace_path)
    try:
        doc = Document(str(source))
    except Exception as exc:
        raise OfficeGenerateError(
            f"无法打开文档: {exc}", file_path=source
        ) from exc

    before = _style_snapshot(doc)
    apply_style_definitions(doc, spec)
    cleared = _clear_run_direct_formatting(doc) if clear_direct_formatting else 0
    after = _style_snapshot(doc)
    changes = _style_changes(before, after)

    warnings: List[str] = []
    if spec.caption is not None:
        warnings.append("caption 样式只对生成期题注生效，已有文档题注不做批量重排")
    if spec.table_text is not None:
        warnings.append("table_text 样式只对生成期表格生效，已有文档表格不做批量重排")

    result: Dict[str, Any] = {
        "ok": True,
        "dry_run": dry_run,
        "saved": False,
        "output_path": None,
        "styles_changed": changes,
        "direct_runs_cleared": cleared,
        "warnings": warnings,
    }
    if dry_run:
        return result

    if overwrite:
        target = source
    else:
        name = output_filename or f"{source.stem}-styled{source.suffix}"
        if Path(name).name != name or not name.lower().endswith(".docx"):
            raise OfficeGenerateError(f"输出文件名非法: {name}")
        target = source.parent / name
    _atomic_replace(doc, target, lambda d, path: d.save(path))
    result["saved"] = True
    result["output_path"] = str(target)
    return result


__all__ = ["apply_style_to_document"]
