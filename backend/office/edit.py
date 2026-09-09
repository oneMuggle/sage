# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""In-place editors for Office documents (Office CRUD 的「改 / 删文件内元素」能力).

Each editor loads the document, applies a list of structured operations
(ops) to the in-memory object, and — only when **every** op succeeds —
atomically replaces the on-disk file (write temp file in the same
directory, then ``os.replace``). A failed op therefore leaves the
original file untouched: the edit is all-or-nothing per call.

Ops are plain dicts (not Pydantic models) so the LLM-facing tool layer
can pass them through verbatim; each op is runtime-validated and unknown
/ malformed ops come back as per-op failure results instead of raising.

Word / Excel / PPT op reference (see the office_update tool schema for
the LLM-facing version):

    word:
        replace_text      {find, replace}                 — body paragraphs + table cells
        append_paragraphs {paragraphs:[{text, heading?}]} — same shape as generate
        append_table      {headers, rows}                 — same shape as generate
        set_table_cell    {table_index, row, col, text}   — row 0 = header row
        delete_paragraph  {find, all?}                    — case-insensitive "contains"
        add_image         {path|base64, width_inches?, height_inches?}
                          — 文档末尾插图；path 相对文档目录（管理布局下再回退
                            工作区根），base64 可带 data:image/ 前缀；≤10MB
        set_paragraph_style {index|match, font_size?, bold?, italic?, color?, align?}
                          — 样式作用于该段全部 runs；index 0-based 对应
                            doc.paragraphs；match 为大小写不敏感的包含匹配

    excel:
        set_cells   {sheet, cells:[{addr, value}]} — A1 notation; numeric-looking
                      strings are converted (Excel-typing semantics); strings
                      starting with '=' are written as formulas
        append_rows {sheet, rows}                  — '=' strings become formulas
        add_sheet   {name, headers?, rows?}
        rename_sheet{from, to}
        delete_sheet{name}                          — refuses to delete the last sheet
        add_chart   {sheet, type: 'line'|'bar'|'pie', anchor: 'A10',
                     data_ref: {min_col, min_row, max_col, max_row},
                     titles_from_data?, from_rows?, categories_ref?, title?}
                      — openpyxl 原生图表（Excel 打开可见、可再编辑）
        set_column_width {sheet, column: 'A'|1, width}
        set_number_format {sheet, cells: 'B2' | 'B2:B10' | [..], format}
        set_fill    {sheet, cells, color: 'FF0000'（可带 #）} — solid 填充
        freeze_panes {sheet, cell: 'B2' | 'A1'(取消冻结)}

    ppt (slide ``index`` is 0-based, matching read_ppt):
        replace_text    {find, replace}     — all shapes' text frames
        set_slide_title {index, title}
        set_slide_bullets {index, bullets}
        set_slide_notes {index, notes}
        append_slide    {title, bullets?, notes?}
        delete_slide    {index}
        add_picture     {index|slide, path|base64, width_inches?, height_inches?}
                          — 插到标题区下方（与生成器正文几何对齐）

Non-goals: 宏编辑与 track-changes 仍不支持。样式 / 图表 / 图片已于
批次 2 支持（word.set_paragraph_style、excel.add_chart、word.add_image、
ppt.add_picture 等，见上表）。
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .errors import OfficeEditError, OfficeFileNotFoundError, OfficeParseError

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────────────────────────────


def _atomic_replace(doc_obj: Any, target: Path, saver: Callable[[Any, str], None]) -> None:
    """Save ``doc_obj`` over ``target`` atomically.

    Writes to a temp file in the same directory (so ``os.replace`` stays
    on one filesystem) then swaps it in. On any failure the temp file is
    removed and the original is left untouched.
    """
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.stem}.", suffix=f".tmp{target.suffix}", dir=str(target.parent)
    )
    os.close(fd)
    try:
        saver(doc_obj, tmp_name)
        # Windows: 刚写完的文件可能被 Defender 等实时扫描短暂锁住,
        # os.replace 报 WinError 5；高 CPU 负载(如 pytest-xdist 并行)下
        # 竞态窗口更大。短暂退避重试；POSIX 上一次成功,行为不变。
        for attempt in range(5):
            try:
                Path(tmp_name).replace(target)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.2 * (attempt + 1))
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def _not_applied(op_name: str) -> Dict[str, Any]:
    return {"op": op_name, "ok": False, "error": "not_applied: 前序操作失败，未保存"}


def _apply_all(
    ops: List[Dict[str, Any]],
    dispatcher: Callable[[Dict[str, Any]], Dict[str, Any]],
) -> Tuple[bool, List[Dict[str, Any]]]:
    """Run ops in order; stop at the first failure.

    Returns ``(all_ok, results)``. Remaining ops after a failure are
    reported as ``not_applied`` — the caller must not save the document
    when ``all_ok`` is False.
    """
    results: List[Dict[str, Any]] = []
    for op in ops:
        op_name = op.get("op") if isinstance(op, dict) else None
        try:
            result = dispatcher(op)
        except Exception as exc:  # noqa: BLE001 — op 级异常折算为该 op 失败
            result = {"op": str(op_name), "ok": False, "error": f"op_error: {exc}"}
        results.append(result)
        if not result.get("ok"):
            results.extend(_not_applied(str(o.get("op"))) for o in ops[len(results) :])
            return False, results
    return True, results


_INT_RE = re.compile(r"^-?(0|[1-9]\d*)$")
_FLOAT_RE = re.compile(r"^-?(\d+\.\d*|\.\d+)([eE][+-]?\d+)?$|^-?\d+[eE][+-]?\d+$")


def _coerce_scalar(value: Any) -> Any:
    """Coerce a cell value the way Excel does when a user types it in.

    Numeric-looking strings become int/float ("42" → 42) so LLM round-
    trips through the string-typed reader output don't turn a numeric
    column into text. Everything else (bool, numbers, None, other
    strings — including leading-zero strings like "007") passes through.

    公式保留（Item 1.4）：以 '=' 开头的字符串原样返回（仅去掉首尾空白，
    保证 openpyxl 能识别 '=' 前缀），openpyxl 赋值时会将其标记为公式
    单元格（data_type='f'）。必须在数值 coerce 之前短路，避免任何路径
    把公式文本改写成数字/文本。
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.startswith("="):
        return text
    if _INT_RE.match(text):
        return int(text)
    if _FLOAT_RE.match(text):
        return float(text)
    return value


def _require_fields(op: Dict[str, Any], fields: Tuple[str, ...]) -> Optional[str]:
    """Return an error string when any required field is missing/None."""
    for name in fields:
        if op.get(name) is None:
            return f"missing_field: {name}"
    return None


def _image_search_dirs(doc_path: Path) -> List[Path]:
    """图片相对路径的候选目录：文档所在目录优先，管理布局再回退工作区根。

    管理布局为 ``<workspace>/office/word|excel|ppt/<doc_id>/file.docx``，
    此时 parents[3] 是工作区根（LLM 常引用 ``@workspace`` 里的图片）。
    非管理布局（如桌面文件）只提供文档所在目录。
    """
    dirs = [doc_path.parent]
    parents = doc_path.parents
    if len(parents) >= 4 and parents[2].name == "office" and parents[1].name in (
        "word",
        "excel",
        "ppt",
    ):
        dirs.append(parents[3])
    return dirs


def _image_payload_from_op(op: Dict[str, Any], doc_path: Optional[Path]) -> bytes:
    """按 op 的 ``base64`` / ``path`` 键解析图片字节（二者必传其一）。

    Raises ValueError with a stable message (折算为该 op 的失败结果)。
    """
    from .charts import decode_image_base64, resolve_image_payload

    base64_payload = op.get("base64")
    if base64_payload:
        return decode_image_base64(str(base64_payload))
    path = op.get("path")
    if path:
        search_dirs = _image_search_dirs(doc_path) if doc_path is not None else []
        return resolve_image_payload(str(path), search_dirs=search_dirs)
    raise ValueError("path_or_base64_required")


# ──────────────────────────────────────────────────────────────────────
# Word (.docx)
# ──────────────────────────────────────────────────────────────────────


def _docx_replace_in_paragraph(para: Any, find: str, replace: str) -> int:
    """Replace ``find`` in one python-docx paragraph; returns hit count.

    Pass 1 edits run text in place (formatting preserved). Pass 2 — only
    when pass 1 found nothing but the joined paragraph text matches —
    rewrites the paragraph text, collapsing its runs into one.
    """
    count = 0
    for run in para.runs:
        if find in run.text:
            count += run.text.count(find)
            run.text = run.text.replace(find, replace)
    if count:
        return count
    if find in para.text:
        count = para.text.count(find)
        para.text = para.text.replace(find, replace)
    return count


def _apply_docx_set_paragraph_style(doc: Any, op: Dict[str, Any], op_name: Any) -> Dict[str, Any]:  # noqa: PLR0911 — 逐分支早退是 op 校验链的可读形式
    """``set_paragraph_style`` 实现：定位段落并对其全部 runs 施加样式。

    定位：``index``（0-based 对应 doc.paragraphs）优先；否则 ``match``
    （大小写不敏感包含匹配，取第一个命中段）。样式字段至少一个：
    font_size（磅）/ bold / italic / color（6 位 RGB hex）/ align
    （left|center|right|justify）。
    """
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    index, match = op.get("index"), op.get("match")
    if index is None and not match:
        return {"op": op_name, "ok": False, "error": "index_or_match_required"}
    if all(op.get(f) is None for f in ("font_size", "bold", "italic", "color", "align")):
        return {"op": op_name, "ok": False, "error": "style_field_required"}

    if index is not None:
        idx = int(index)
        if not (0 <= idx < len(doc.paragraphs)):
            return {"op": op_name, "ok": False, "error": f"paragraph_index_out_of_range: {idx}"}
        para = doc.paragraphs[idx]
    else:
        needle = str(match).casefold()
        para = next((p for p in doc.paragraphs if needle in p.text.casefold()), None)
        if para is None:
            return {"op": op_name, "ok": False, "error": f"text_not_found: {match!r}"}

    runs = para.runs
    if not runs:
        return {"op": op_name, "ok": False, "error": "paragraph_has_no_runs"}

    align = op.get("align")
    if align is not None:
        alignments = {
            "left": WD_ALIGN_PARAGRAPH.LEFT,
            "center": WD_ALIGN_PARAGRAPH.CENTER,
            "right": WD_ALIGN_PARAGRAPH.RIGHT,
            "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
        }
        if align not in alignments:
            return {"op": op_name, "ok": False, "error": f"invalid_align: {align!r}"}
        para.alignment = alignments[align]

    color = op.get("color")
    rgb = None
    if color is not None:
        hex_text = str(color).strip().lstrip("#")
        if len(hex_text) != 6 or any(c not in "0123456789abcdefABCDEF" for c in hex_text):
            return {"op": op_name, "ok": False, "error": f"invalid_color: {color!r}"}
        rgb = RGBColor.from_string(hex_text.upper())

    font_size = op.get("font_size")
    for run in runs:
        if font_size is not None:
            run.font.size = Pt(float(font_size))
        if op.get("bold") is not None:
            run.font.bold = bool(op["bold"])
        if op.get("italic") is not None:
            run.font.italic = bool(op["italic"])
        if rgb is not None:
            run.font.color.rgb = rgb
    return {"op": op_name, "ok": True, "runs": len(runs)}


def _apply_docx_op(doc: Any, op: Dict[str, Any], doc_path: Optional[Path] = None) -> Dict[str, Any]:  # noqa: PLR0911 — op 分发表
    op_name = op.get("op")

    if op_name == "replace_text":
        missing = _require_fields(op, ("find",))
        if missing:
            return {"op": op_name, "ok": False, "error": missing}
        find, replace = str(op["find"]), str(op.get("replace", ""))
        hits = 0
        for para in doc.paragraphs:
            hits += _docx_replace_in_paragraph(para, find, replace)
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        hits += _docx_replace_in_paragraph(para, find, replace)
        if hits == 0:
            return {"op": op_name, "ok": False, "error": f"text_not_found: {find!r}"}
        return {"op": op_name, "ok": True, "replacements": hits}

    if op_name == "append_paragraphs":
        paragraphs = op.get("paragraphs")
        if not isinstance(paragraphs, list) or not paragraphs:
            return {"op": op_name, "ok": False, "error": "paragraphs_required"}
        for spec in paragraphs:
            if not isinstance(spec, dict) or not str(spec.get("text", "")).strip():
                return {"op": op_name, "ok": False, "error": "paragraph_text_required"}
        for spec in paragraphs:
            heading = spec.get("heading")
            text = str(spec["text"])
            if heading == "h1":
                doc.add_heading(text, level=1)
            elif heading == "h2":
                doc.add_heading(text, level=2)
            elif heading == "h3":
                doc.add_heading(text, level=3)
            else:
                doc.add_paragraph(text)
        return {"op": op_name, "ok": True, "appended": len(paragraphs)}

    if op_name == "append_table":
        headers = op.get("headers")
        rows = op.get("rows") or []
        if not isinstance(headers, list) or not headers:
            return {"op": op_name, "ok": False, "error": "headers_required"}
        table = doc.add_table(rows=1 + len(rows), cols=len(headers))
        for ci, header in enumerate(headers):
            table.cell(0, ci).text = str(header)
        for ri, row in enumerate(rows):
            for ci, cell in enumerate(row):
                if ci < len(headers):
                    table.cell(ri + 1, ci).text = str(cell)
        return {"op": op_name, "ok": True, "rows": 1 + len(rows)}

    if op_name == "set_table_cell":
        missing = _require_fields(op, ("table_index", "row", "col", "text"))
        if missing:
            return {"op": op_name, "ok": False, "error": missing}
        ti, ri, ci = int(op["table_index"]), int(op["row"]), int(op["col"])
        if not (0 <= ti < len(doc.tables)):
            return {"op": op_name, "ok": False, "error": f"table_index_out_of_range: {ti}"}
        table = doc.tables[ti]
        if not (0 <= ri < len(table.rows) and 0 <= ci < len(table.columns)):
            return {"op": op_name, "ok": False, "error": f"cell_out_of_range: ({ri}, {ci})"}
        table.cell(ri, ci).text = str(op["text"])
        return {"op": op_name, "ok": True}

    if op_name == "delete_paragraph":
        missing = _require_fields(op, ("find",))
        if missing:
            return {"op": op_name, "ok": False, "error": missing}
        find = str(op["find"]).casefold()
        all_matches = bool(op.get("all", False))
        removed = 0
        for para in list(doc.paragraphs):
            if find and find in para.text.casefold():
                para._element.getparent().remove(para._element)
                removed += 1
                if not all_matches:
                    break
        if removed == 0:
            return {"op": op_name, "ok": False, "error": f"text_not_found: {find!r}"}
        return {"op": op_name, "ok": True, "removed": removed}

    if op_name == "add_image":
        # 批次 2.1：文档末尾插图（新段落承载 inline picture）。
        from docx.shared import Inches

        from .charts import image_bytes_to_stream

        try:
            payload = _image_payload_from_op(op, doc_path)
        except ValueError as exc:
            return {"op": op_name, "ok": False, "error": str(exc)}
        width_inches, height_inches = op.get("width_inches"), op.get("height_inches")
        width = Inches(float(width_inches)) if width_inches else None
        height = Inches(float(height_inches)) if height_inches else None
        doc.add_picture(image_bytes_to_stream(payload), width=width, height=height)
        return {"op": op_name, "ok": True}

    if op_name == "set_paragraph_style":
        # 批次 2.3：按 index / match 定位段落，样式作用于全部 runs。
        return _apply_docx_set_paragraph_style(doc, op, op_name)

    return {"op": str(op_name), "ok": False, "error": f"unsupported_op: {op_name}"}


def update_docx(file_path: Path, ops: List[Dict[str, Any]]) -> Tuple[bool, List[Dict[str, Any]]]:
    """Apply ops to a .docx in place. Returns ``(saved, per_op_results)``.

    Raises:
        OfficeFileNotFoundError / OfficeParseError: file-level failures.
        OfficeEditError: the save step failed (original file untouched).
    """
    from docx import Document

    file_path = Path(file_path)
    if not file_path.is_file():
        raise OfficeFileNotFoundError(file_path)
    try:
        doc = Document(str(file_path))
    except Exception as exc:
        raise OfficeParseError(f"Failed to parse DOCX: {exc}", file_path=file_path) from exc

    all_ok, results = _apply_all(ops, lambda op: _apply_docx_op(doc, op, file_path))
    if not all_ok:
        return False, results
    try:
        _atomic_replace(doc, file_path, lambda d, p: d.save(p))
    except Exception as exc:
        raise OfficeEditError(f"Failed to save DOCX: {exc}", file_path=file_path) from exc
    return True, results


# ──────────────────────────────────────────────────────────────────────
# Excel (.xlsx)
# ──────────────────────────────────────────────────────────────────────

#: A1 风格单元格引用（1-3 位列字母 + 行号，行号 ≥1）。
_CELL_REF_RE = re.compile(r"^[A-Za-z]{1,3}[1-9][0-9]*$")


def _normalize_argb(color: Any) -> Optional[str]:
    """'FF0000' / '#FF0000' / 8 位 ARGB → openpyxl aRGB 字符串；非法返回 None。"""
    if not isinstance(color, str):
        return None
    hex_text = color.strip().lstrip("#")
    if not all(c in "0123456789abcdefABCDEF" for c in hex_text):
        return None
    if len(hex_text) == 6:
        return "FF" + hex_text.upper()
    if len(hex_text) == 8:
        return hex_text.upper()
    return None


def _expand_cell_targets(ws: Any, cells: Any) -> List[Any]:
    """把 'B2' / 'B2:B10' / ['A1', 'C1:C3'] 展开为 openpyxl cell 列表。

    Raises ValueError on any malformed address/range（op 层折算为失败结果）。
    """
    if isinstance(cells, str):
        cells = [cells]
    if not isinstance(cells, list) or not cells:
        raise ValueError("cells_required")
    targets: List[Any] = []
    for item in cells:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"invalid_cells: {item!r}")
        ref = item.strip()
        parts = ref.split(":")
        if len(parts) == 1:
            if not _CELL_REF_RE.match(parts[0]):
                raise ValueError(f"invalid_cells: {ref!r}")
            targets.append(ws[parts[0].upper()])
        elif len(parts) == 2 and all(_CELL_REF_RE.match(p) for p in parts):
            for row in ws[f"{parts[0].upper()}:{parts[1].upper()}"]:
                targets.extend(row)
        else:
            raise ValueError(f"invalid_cells: {ref!r}")
    return targets


def _apply_xlsx_op(wb: Any, op: Dict[str, Any]) -> Dict[str, Any]:  # noqa: PLR0911 — op 分发表
    op_name = op.get("op")

    if op_name == "set_cells":
        missing = _require_fields(op, ("sheet", "cells"))
        if missing:
            return {"op": op_name, "ok": False, "error": missing}
        if op["sheet"] not in wb.sheetnames:
            return {"op": op_name, "ok": False, "error": f"sheet_not_found: {op['sheet']!r}"}
        cells = op["cells"]
        if not isinstance(cells, list) or not cells:
            return {"op": op_name, "ok": False, "error": "cells_required"}
        ws = wb[op["sheet"]]
        for spec in cells:
            if not isinstance(spec, dict) or not spec.get("addr"):
                return {"op": op_name, "ok": False, "error": "cell_addr_required"}
            ws[str(spec["addr"])] = _coerce_scalar(spec.get("value"))
        return {"op": op_name, "ok": True, "cells": len(cells)}

    if op_name == "append_rows":
        missing = _require_fields(op, ("sheet", "rows"))
        if missing:
            return {"op": op_name, "ok": False, "error": missing}
        if op["sheet"] not in wb.sheetnames:
            return {"op": op_name, "ok": False, "error": f"sheet_not_found: {op['sheet']!r}"}
        rows = op["rows"]
        if not isinstance(rows, list) or not rows:
            return {"op": op_name, "ok": False, "error": "rows_required"}
        ws = wb[op["sheet"]]
        for row in rows:
            if not isinstance(row, list):
                return {"op": op_name, "ok": False, "error": "row_must_be_array"}
            ws.append([_coerce_scalar(v) for v in row])
        return {"op": op_name, "ok": True, "rows": len(rows), "max_row": ws.max_row}

    if op_name == "add_sheet":
        missing = _require_fields(op, ("name",))
        if missing:
            return {"op": op_name, "ok": False, "error": missing}
        name = str(op["name"])[:31]  # Excel sheet-name limit
        if name in wb.sheetnames:
            return {"op": op_name, "ok": False, "error": f"sheet_exists: {name!r}"}
        ws = wb.create_sheet(title=name)
        headers = op.get("headers") or []
        for ci, header in enumerate(headers):
            ws.cell(row=1, column=ci + 1, value=header)
        for ri, row in enumerate(op.get("rows") or []):
            for ci, cell in enumerate(row):
                ws.cell(row=ri + 2, column=ci + 1, value=_coerce_scalar(cell))
        return {"op": op_name, "ok": True, "name": name}

    if op_name == "rename_sheet":
        missing = _require_fields(op, ("from", "to"))
        if missing:
            return {"op": op_name, "ok": False, "error": missing}
        old, new = str(op["from"]), str(op["to"])[:31]
        if old not in wb.sheetnames:
            return {"op": op_name, "ok": False, "error": f"sheet_not_found: {old!r}"}
        if new in wb.sheetnames and new != old:
            return {"op": op_name, "ok": False, "error": f"sheet_exists: {new!r}"}
        wb[old].title = new
        return {"op": op_name, "ok": True, "from": old, "to": new}

    if op_name == "delete_sheet":
        missing = _require_fields(op, ("name",))
        if missing:
            return {"op": op_name, "ok": False, "error": missing}
        name = str(op["name"])
        if name not in wb.sheetnames:
            return {"op": op_name, "ok": False, "error": f"sheet_not_found: {name!r}"}
        if len(wb.sheetnames) == 1:
            return {"op": op_name, "ok": False, "error": "cannot_delete_last_sheet"}
        wb.remove(wb[name])
        return {"op": op_name, "ok": True, "name": name}

    if op_name == "add_chart":
        # 批次 2.1：openpyxl 原生图表（Excel 打开可见、可再编辑）。
        missing = _require_fields(op, ("sheet", "type", "anchor", "data_ref"))
        if missing:
            return {"op": op_name, "ok": False, "error": missing}
        if op["sheet"] not in wb.sheetnames:
            return {"op": op_name, "ok": False, "error": f"sheet_not_found: {op['sheet']!r}"}
        from .charts import build_openpyxl_chart

        try:
            build_openpyxl_chart(wb[op["sheet"]], op)
        except ValueError as exc:
            return {"op": op_name, "ok": False, "error": str(exc)}
        return {"op": op_name, "ok": True, "type": op["type"], "anchor": str(op["anchor"])}

    if op_name == "set_column_width":
        missing = _require_fields(op, ("sheet", "column", "width"))
        if missing:
            return {"op": op_name, "ok": False, "error": missing}
        if op["sheet"] not in wb.sheetnames:
            return {"op": op_name, "ok": False, "error": f"sheet_not_found: {op['sheet']!r}"}
        from openpyxl.utils import get_column_letter

        column = op["column"]
        if isinstance(column, str) and column.strip().isalpha():
            letter = column.strip().upper()
        else:
            try:
                idx = int(column)
            except (TypeError, ValueError):
                return {"op": op_name, "ok": False, "error": f"invalid_column: {column!r}"}
            if idx < 1:
                return {"op": op_name, "ok": False, "error": f"invalid_column: {column!r}"}
            letter = get_column_letter(idx)
        try:
            width = float(op["width"])
        except (TypeError, ValueError):
            return {"op": op_name, "ok": False, "error": f"invalid_width: {op['width']!r}"}
        if width <= 0:
            return {"op": op_name, "ok": False, "error": f"invalid_width: {op['width']!r}"}
        wb[op["sheet"]].column_dimensions[letter].width = width
        return {"op": op_name, "ok": True, "column": letter, "width": width}

    if op_name in ("set_number_format", "set_fill"):
        missing = _require_fields(op, ("sheet", "cells"))
        if missing:
            return {"op": op_name, "ok": False, "error": missing}
        if op["sheet"] not in wb.sheetnames:
            return {"op": op_name, "ok": False, "error": f"sheet_not_found: {op['sheet']!r}"}
        ws = wb[op["sheet"]]
        try:
            targets = _expand_cell_targets(ws, op["cells"])
        except ValueError as exc:
            return {"op": op_name, "ok": False, "error": str(exc)}
        if not targets:
            return {"op": op_name, "ok": False, "error": "cells_required"}
        if op_name == "set_number_format":
            fmt = op.get("format")
            if not fmt:
                return {"op": op_name, "ok": False, "error": "missing_field: format"}
            for cell in targets:
                cell.number_format = str(fmt)
            return {"op": op_name, "ok": True, "cells": len(targets), "format": str(fmt)}
        # set_fill：solid 填充，颜色接受 6/8 位 hex（可带 #），6 位补 FF alpha。
        argb = _normalize_argb(op.get("color"))
        if argb is None:
            return {"op": op_name, "ok": False, "error": f"invalid_color: {op.get('color')!r}"}
        from openpyxl.styles import PatternFill

        fill = PatternFill(fill_type="solid", start_color=argb, end_color=argb)
        for cell in targets:
            cell.fill = fill
        return {"op": op_name, "ok": True, "cells": len(targets), "color": argb}

    if op_name == "freeze_panes":
        missing = _require_fields(op, ("sheet", "cell"))
        if missing:
            return {"op": op_name, "ok": False, "error": missing}
        if op["sheet"] not in wb.sheetnames:
            return {"op": op_name, "ok": False, "error": f"sheet_not_found: {op['sheet']!r}"}
        cell = str(op["cell"]).strip()
        # 'A1' 语义上等于「不冻结」（openpyxl 冻结基准在 A1 即无冻结窗格）。
        if cell.upper() in ("A1", "NONE", "NULL"):
            wb[op["sheet"]].freeze_panes = None
            return {"op": op_name, "ok": True, "frozen_at": None}
        if not _CELL_REF_RE.match(cell):
            return {"op": op_name, "ok": False, "error": f"invalid_cell: {cell!r}"}
        wb[op["sheet"]].freeze_panes = cell.upper()
        return {"op": op_name, "ok": True, "frozen_at": cell.upper()}

    return {"op": str(op_name), "ok": False, "error": f"unsupported_op: {op_name}"}


def update_xlsx(file_path: Path, ops: List[Dict[str, Any]]) -> Tuple[bool, List[Dict[str, Any]]]:
    """Apply ops to a .xlsx in place. Returns ``(saved, per_op_results)``.

    The workbook is loaded with ``data_only=False`` so existing formulas
    survive the edit, and ``set_cells`` / ``append_rows`` / ``add_sheet``
    write '=' prefixed strings as real formulas (Item 1.4, see
    :func:`_coerce_scalar`). Note openpyxl does not preserve Excel's cached
    formula results when saving — apps recompute on open, and
    ``read_xlsx(include_formulas=True)`` is the way to inspect formula text.
    """
    from openpyxl import load_workbook

    file_path = Path(file_path)
    if not file_path.is_file():
        raise OfficeFileNotFoundError(file_path)
    try:
        wb = load_workbook(str(file_path))
    except Exception as exc:
        raise OfficeParseError(f"Failed to parse XLSX: {exc}", file_path=file_path) from exc

    all_ok, results = _apply_all(ops, lambda op: _apply_xlsx_op(wb, op))
    if not all_ok:
        return False, results
    try:
        _atomic_replace(wb, file_path, lambda w, p: w.save(p))
    except Exception as exc:
        raise OfficeEditError(f"Failed to save XLSX: {exc}", file_path=file_path) from exc
    return True, results


# ──────────────────────────────────────────────────────────────────────
# PowerPoint (.pptx)
# ──────────────────────────────────────────────────────────────────────

#: Same textbox geometry generate_ppt uses, so edits blend into generated decks.
_TITLE_BOX_GEOMETRY = (914400, 274638, 9144000, 1143000)
_BODY_BOX_GEOMETRY = (914400, 1600200, 9144000, 4572000)


def _pptx_replace_in_text_frame(tf: Any, find: str, replace: str) -> int:
    """python-pptx counterpart of :func:`_docx_replace_in_paragraph`."""
    count = 0
    for para in tf.paragraphs:
        for run in para.runs:
            if find in run.text:
                count += run.text.count(find)
                run.text = run.text.replace(find, replace)
    if count:
        return count
    for para in tf.paragraphs:
        if find in para.text:
            count += para.text.count(find)
            para.text = para.text.replace(find, replace)
    return count


def _slide_text_shapes(slide: Any) -> List[Any]:
    """Shapes that carry a text frame, in z-order (title box is added first)."""
    return [sh for sh in slide.shapes if sh.has_text_frame]


def _fill_text_frame(tf: Any, lines: List[str]) -> None:
    """Rewrite a text frame with one paragraph per line (formatting collapses)."""
    if not lines:
        return
    tf.text = lines[0]
    for line in lines[1:]:
        tf.add_paragraph().text = line


def _apply_pptx_op(prs: Any, op: Dict[str, Any], doc_path: Optional[Path] = None) -> Dict[str, Any]:  # noqa: PLR0911 — op 分发表
    op_name = op.get("op")
    slides = prs.slides

    def _slide_at(idx: int) -> Any:
        if not (0 <= idx < len(slides)):
            raise ValueError(f"slide_index_out_of_range: {idx}")
        return slides[idx]

    if op_name == "replace_text":
        missing = _require_fields(op, ("find",))
        if missing:
            return {"op": op_name, "ok": False, "error": missing}
        find, replace = str(op["find"]), str(op.get("replace", ""))
        hits = 0
        for slide in slides:
            for shape in _slide_text_shapes(slide):
                hits += _pptx_replace_in_text_frame(shape.text_frame, find, replace)
        if hits == 0:
            return {"op": op_name, "ok": False, "error": f"text_not_found: {find!r}"}
        return {"op": op_name, "ok": True, "replacements": hits}

    if op_name in ("set_slide_title", "set_slide_bullets", "set_slide_notes"):
        missing = _require_fields(op, ("index",))
        if missing:
            return {"op": op_name, "ok": False, "error": missing}
        try:
            slide = _slide_at(int(op["index"]))
        except ValueError as exc:
            return {"op": op_name, "ok": False, "error": str(exc)}

        if op_name == "set_slide_notes":
            missing = _require_fields(op, ("notes",))
            if missing:
                return {"op": op_name, "ok": False, "error": missing}
            slide.notes_slide.notes_text_frame.text = str(op["notes"])
            return {"op": op_name, "ok": True}

        if op_name == "set_slide_title":
            missing = _require_fields(op, ("title",))
            if missing:
                return {"op": op_name, "ok": False, "error": missing}
            title = str(op["title"])
            title_shape = slide.shapes.title
            if title_shape is not None:
                title_shape.text_frame.text = title
            elif _slide_text_shapes(slide):
                # Generated decks use plain textboxes; the first one is the title.
                _slide_text_shapes(slide)[0].text_frame.text = title
            else:
                box = slide.shapes.add_textbox(*_TITLE_BOX_GEOMETRY)
                box.text_frame.text = title
            return {"op": op_name, "ok": True}

        # set_slide_bullets
        bullets = op.get("bullets")
        if not isinstance(bullets, list):
            return {"op": op_name, "ok": False, "error": "bullets_required"}
        bullets = [str(b) for b in bullets]
        title_shape = slide.shapes.title
        text_shapes = _slide_text_shapes(slide)
        skip = 1 if (title_shape is None and text_shapes) else 0
        body_shapes = text_shapes[skip:]
        if body_shapes:
            _fill_text_frame(body_shapes[0].text_frame, bullets)
        else:
            box = slide.shapes.add_textbox(*_BODY_BOX_GEOMETRY)
            _fill_text_frame(box.text_frame, bullets)
        return {"op": op_name, "ok": True, "bullets": len(bullets)}

    if op_name == "append_slide":
        title = str(op.get("title") or "")
        bullets = [str(b) for b in op.get("bullets") or []]
        notes = op.get("notes")
        layouts = prs.slide_layouts
        blank = layouts[6] if len(layouts) > 6 else layouts[len(layouts) - 1]
        slide = slides.add_slide(blank)
        if title:
            box = slide.shapes.add_textbox(*_TITLE_BOX_GEOMETRY)
            box.text_frame.text = title
        if bullets:
            box = slide.shapes.add_textbox(*_BODY_BOX_GEOMETRY)
            _fill_text_frame(box.text_frame, bullets)
        if notes:
            slide.notes_slide.notes_text_frame.text = str(notes)
        return {"op": op_name, "ok": True, "index": len(slides) - 1}

    if op_name == "delete_slide":
        missing = _require_fields(op, ("index",))
        if missing:
            return {"op": op_name, "ok": False, "error": missing}
        idx = int(op["index"])
        if not (0 <= idx < len(slides)):
            return {"op": op_name, "ok": False, "error": f"slide_index_out_of_range: {idx}"}
        sld_id_lst = slides._sldIdLst
        sld_ids = list(sld_id_lst)
        sld_id_lst.remove(sld_ids[idx])
        return {"op": op_name, "ok": True, "index": idx, "remaining": len(slides)}

    if op_name == "add_picture":
        # 批次 2.1：定位 slide（index 优先，兼容 'slide' 键名），插入图片。
        slide_index = op.get("index")
        if slide_index is None:
            slide_index = op.get("slide")
        if slide_index is None:
            return {"op": op_name, "ok": False, "error": "missing_field: index"}
        try:
            slide = _slide_at(int(slide_index))
        except ValueError as exc:
            return {"op": op_name, "ok": False, "error": str(exc)}
        from pptx.util import Inches

        from .charts import image_bytes_to_stream

        try:
            payload = _image_payload_from_op(op, doc_path)
        except ValueError as exc:
            return {"op": op_name, "ok": False, "error": str(exc)}
        width_inches, height_inches = op.get("width_inches"), op.get("height_inches")
        # 缺省位置：正文区左上角（与生成器 _BODY_BOX_GEOMETRY 对齐，避免盖标题）。
        left, top = 914400, 1600200
        width = Inches(float(width_inches)) if width_inches else None
        height = Inches(float(height_inches)) if height_inches else None
        slide.shapes.add_picture(
            image_bytes_to_stream(payload), left, top, width=width, height=height
        )
        return {"op": op_name, "ok": True, "slide": int(slide_index)}

    return {"op": str(op_name), "ok": False, "error": f"unsupported_op: {op_name}"}


def update_pptx(file_path: Path, ops: List[Dict[str, Any]]) -> Tuple[bool, List[Dict[str, Any]]]:
    """Apply ops to a .pptx in place. Returns ``(saved, per_op_results)``."""
    from pptx import Presentation

    file_path = Path(file_path)
    if not file_path.is_file():
        raise OfficeFileNotFoundError(file_path)
    try:
        prs = Presentation(str(file_path))
    except Exception as exc:
        raise OfficeParseError(f"Failed to parse PPTX: {exc}", file_path=file_path) from exc

    all_ok, results = _apply_all(ops, lambda op: _apply_pptx_op(prs, op, file_path))
    if not all_ok:
        return False, results
    try:
        _atomic_replace(prs, file_path, lambda p, path: p.save(path))
    except Exception as exc:
        raise OfficeEditError(f"Failed to save PPTX: {exc}", file_path=file_path) from exc
    return True, results


# ──────────────────────────────────────────────────────────────────────
# Dispatch
# ──────────────────────────────────────────────────────────────────────

#: OfficeDocType value → editor. Populated lazily to avoid importing the
#: backend domain layer from the (domain-pure) office package unexpectedly.
Editors = Dict[str, Callable[[Path, List[Dict[str, Any]]], Tuple[bool, List[Dict[str, Any]]]]]


def update_document(
    doc_type: str, file_path: Path, ops: List[Dict[str, Any]]
) -> Tuple[bool, List[Dict[str, Any]]]:
    """Dispatch to the right editor by ``doc_type`` ("word"/"excel"/"ppt")."""
    editors: Editors = {
        "word": update_docx,
        "excel": update_xlsx,
        "ppt": update_pptx,
    }
    editor = editors.get((doc_type or "").lower())
    if editor is None:
        raise OfficeEditError(f"unsupported doc_type: {doc_type}", file_path=file_path)
    return editor(file_path, ops)


__all__ = [
    "update_docx",
    "update_xlsx",
    "update_pptx",
    "update_document",
]
