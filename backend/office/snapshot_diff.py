"""Round B P2: 快照 vs 当前版本的结构化可视 diff。

与 :mod:`backend.office.diff_preview`（op 驱动的 dry-run 预览）互补：
快照对比没有 ops 可归因，做的是 **state-vs-state** 差异 ——

- word : 段落序列 difflib.SequenceMatcher 对齐（equal 跳过，
  replace → changed，delete → removed，insert → added），表格逐格比对；
- excel: 逐 sheet 逐格比对（含 sheet 增删）；
- ppt  : 逐页标题/要点/备注比对（含页增删）。

条目形状复用 ``DiffPreviewChange``（op 字段放差异类别），前端红绿渲染
逻辑与编辑预览弹窗共享。上限 ``MAX_CHANGES`` 同 diff_preview 口径。

失败契约：**永不 raise** —— 解析失败/快照缺失折叠为 ok=False。
快照 id 校验与 :func:`storage.restore_from_snapshot` 同规则（拒绝
路径穿越分隔符）。

Python 3.8-compatible syntax，可回流 release/win7。
"""

from __future__ import annotations

import difflib
import logging
from pathlib import Path
from typing import Any, List, Optional

from .diff_preview import MAX_CHANGES, DiffPreviewChange, DiffPreviewResult
from .models import OfficeDocType, OfficeDocumentSummary
from .storage import _snapshot_dir_for, document_path

logger = logging.getLogger(__name__)

__all__ = ["diff_snapshot"]

#: 文本片段展示上限（与 diff_preview._SNIPPET_LIMIT 视觉口径一致）。
_SNIPPET = 80


def _clip(text: object) -> str:
    s = str(text).strip()
    return s if len(s) <= _SNIPPET else s[: _SNIPPET - 1] + "…"


def _word_changes(before: Any, after: Any) -> List[DiffPreviewChange]:
    """段落序列对齐 + 表格逐格比对。before=快照，after=当前。"""
    changes: List[DiffPreviewChange] = []
    old = [p.text for p in before.paragraphs]
    new = [p.text for p in after.paragraphs]
    matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace":
            for off in range(max(i2 - i1, j2 - j1)):
                b = old[i1 + off] if i1 + off < i2 else None
                a = new[j1 + off] if j1 + off < j2 else None
                changes.append(
                    DiffPreviewChange(
                        op="changed" if b is not None and a is not None
                        else ("removed" if a is None else "added"),
                        target=f"paragraph[{(i1 + off) if b is not None else (j1 + off)}]",
                        before=_clip(b) if b is not None else None,
                        after=_clip(a) if a is not None else None,
                    )
                )
        elif tag == "delete":
            for i in range(i1, i2):
                changes.append(
                    DiffPreviewChange(op="removed", target=f"paragraph[{i}]", before=_clip(old[i]))
                )
        elif tag == "insert":
            for j in range(j1, j2):
                changes.append(
                    DiffPreviewChange(op="added", target=f"paragraph[{j}]", after=_clip(new[j]))
                )
    # 表格：数量差异 + 共同表格逐格比对
    old_tables = before.tables or []
    new_tables = after.tables or []
    for ti in range(max(len(old_tables), len(new_tables))):
        if ti >= len(old_tables):
            changes.append(
                DiffPreviewChange(op="added", target=f"table[{ti}]", summary="新增表格")
            )
            continue
        if ti >= len(new_tables):
            changes.append(
                DiffPreviewChange(op="removed", target=f"table[{ti}]", summary="删除表格")
            )
            continue
        o_rows, n_rows = old_tables[ti].rows or [], new_tables[ti].rows or []
        for r in range(max(len(o_rows), len(n_rows))):
            o_row = o_rows[r] if r < len(o_rows) else []
            n_row = n_rows[r] if r < len(n_rows) else []
            for c in range(max(len(o_row), len(n_row))):
                o_cell = o_row[c] if c < len(o_row) else None
                n_cell = n_row[c] if c < len(n_row) else None
                if o_cell == n_cell:
                    continue
                changes.append(
                    DiffPreviewChange(
                        op="changed" if o_cell is not None and n_cell is not None
                        else ("removed" if n_cell is None else "added"),
                        target=f"table[{ti}].cell({r},{c})",
                        before=_clip(o_cell) if o_cell is not None else None,
                        after=_clip(n_cell) if n_cell is not None else None,
                    )
                )
    return changes


def _excel_changes(before: Any, after: Any) -> List[DiffPreviewChange]:
    """逐 sheet 逐格比对；sheet 增删单独成条。"""
    changes: List[DiffPreviewChange] = []
    old_sheets = {s.name: s for s in before.sheets}
    new_sheets = {s.name: s for s in after.sheets}
    for name in old_sheets:
        if name not in new_sheets:
            changes.append(DiffPreviewChange(op="removed", target=name, summary="删除工作表"))
    for name in new_sheets:
        if name not in old_sheets:
            changes.append(DiffPreviewChange(op="added", target=name, summary="新增工作表"))
    for name, old_sheet in old_sheets.items():
        new_sheet = new_sheets.get(name)
        if new_sheet is None:
            continue
        o_rows, n_rows = old_sheet.rows or [], new_sheet.rows or []
        for r in range(max(len(o_rows), len(n_rows))):
            o_row = o_rows[r] if r < len(o_rows) else []
            n_row = n_rows[r] if r < len(n_rows) else []
            for c in range(max(len(o_row), len(n_row))):
                o_cell = o_row[c] if c < len(o_row) else None
                n_cell = n_row[c] if c < len(n_row) else None
                if o_cell == n_cell:
                    continue
                col_letter = _col_letter(c)
                changes.append(
                    DiffPreviewChange(
                        op="changed" if o_cell is not None and n_cell is not None
                        else ("removed" if n_cell is None else "added"),
                        target=f"{name}!{col_letter}{r + 1}",
                        before=_clip(o_cell) if o_cell is not None else None,
                        after=_clip(n_cell) if n_cell is not None else None,
                    )
                )
    return changes


def _col_letter(index: int) -> str:
    """0-based 列号 → Excel 列字母（0→A, 25→Z, 26→AA）。"""
    letters = ""
    n = index
    while True:
        n, rem = divmod(n, 26)
        letters = chr(ord("A") + rem) + letters
        if n == 0:
            return letters
        n -= 1


def _ppt_changes(before: Any, after: Any) -> List[DiffPreviewChange]:
    """逐页标题/要点/备注比对；页增删单独成条。"""
    changes: List[DiffPreviewChange] = []
    old_slides = before.slides or []
    new_slides = after.slides or []
    for i in range(max(len(old_slides), len(new_slides))):
        if i >= len(old_slides):
            changes.append(
                DiffPreviewChange(
                    op="added",
                    target=f"slide[{i}]",
                    after=_clip(new_slides[i].title or ""),
                    summary="新增幻灯片",
                )
            )
            continue
        if i >= len(new_slides):
            changes.append(
                DiffPreviewChange(
                    op="removed",
                    target=f"slide[{i}]",
                    before=_clip(old_slides[i].title or ""),
                    summary="删除幻灯片",
                )
            )
            continue
        o, n = old_slides[i], new_slides[i]
        if (o.title or "") != (n.title or ""):
            changes.append(
                DiffPreviewChange(
                    op="changed",
                    target=f"slide[{i}].title",
                    before=_clip(o.title or ""),
                    after=_clip(n.title or ""),
                )
            )
        o_text = "\n".join(o.text_blocks or [])
        n_text = "\n".join(n.text_blocks or [])
        if o_text != n_text:
            changes.append(
                DiffPreviewChange(
                    op="changed",
                    target=f"slide[{i}].content",
                    before=_clip(o_text),
                    after=_clip(n_text),
                )
            )
        if (getattr(o, "notes", None) or "") != (getattr(n, "notes", None) or ""):
            changes.append(
                DiffPreviewChange(
                    op="changed",
                    target=f"slide[{i}].notes",
                    before=_clip(getattr(o, "notes", "") or ""),
                    after=_clip(getattr(n, "notes", "") or ""),
                )
            )
    return changes


def diff_snapshot(
    summary: OfficeDocumentSummary, snapshot_id: str
) -> DiffPreviewResult:
    """比对快照与当前文档，返回结构化差异清单（快照=before，当前=after）。

    永不 raise —— 一切失败折叠为 ``DiffPreviewResult(ok=False, error=…)``。
    """
    try:
        return _diff_inner(summary, snapshot_id)
    except Exception as exc:  # noqa: BLE001 — 契约：绝不向路由层抛异常
        logger.exception("diff_snapshot crashed unexpectedly")
        return DiffPreviewResult(
            ok=False, error=f"快照对比失败：内部错误（{type(exc).__name__}，详见日志）"
        )


def _diff_inner(summary: OfficeDocumentSummary, snapshot_id: str) -> DiffPreviewResult:
    # 快照 id 校验与 restore_from_snapshot 同规则
    if any(sep in snapshot_id for sep in ("/", "\\", "..")):
        return DiffPreviewResult(ok=False, error=f"无效的快照 id: {snapshot_id}")
    snapshot_dir = _snapshot_dir_for(summary)
    snapshot_path: Optional[Path] = (
        snapshot_dir / snapshot_id if snapshot_dir is not None else None
    )
    if snapshot_path is None or not snapshot_path.is_file():
        return DiffPreviewResult(ok=False, error=f"快照不存在: {snapshot_id}")
    current_path = document_path(summary)
    if not current_path.is_file():
        return DiffPreviewResult(ok=False, error="当前文档文件不在盘上")

    doc_type = summary.doc_type
    try:
        if doc_type is OfficeDocType.WORD:
            from .word import read_docx

            changes = _word_changes(read_docx(snapshot_path), read_docx(current_path))
        elif doc_type is OfficeDocType.EXCEL:
            from .excel import read_xlsx

            changes = _excel_changes(read_xlsx(snapshot_path), read_xlsx(current_path))
        elif doc_type is OfficeDocType.PPT:
            from .ppt import read_ppt

            changes = _ppt_changes(read_ppt(snapshot_path), read_ppt(current_path))
        else:
            return DiffPreviewResult(
                ok=False, error=f"不支持的文档类型: {doc_type.value}（仅 word/excel/ppt）"
            )
    except Exception as exc:  # noqa: BLE001 — 解析失败折叠为 ok=False
        return DiffPreviewResult(ok=False, error=f"文档解析失败: {exc}")

    truncated = len(changes) > MAX_CHANGES
    if truncated:
        changes = changes[:MAX_CHANGES]
    return DiffPreviewResult(ok=True, changes=changes, truncated=truncated)
