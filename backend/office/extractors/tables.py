"""Table helpers shared by the extraction backends (M6b).

Two concerns live here:

- ``table_markdown`` — the canonical rows → Markdown rendering used by every
  backend that emits ``type="table"`` blocks.
- ``assess_table_complexity`` — the policy that decides whether a document's
  tables are "complex" enough to warrant a higher-fidelity backend.

Complexity is judged from the diagnostics measured by ``backend.office.pdf``
(null cells, unusual geometry, truncated grids, pages whose tables can only
be seen through whitespace alignment). The reason codes are stable strings so
callers can branch on them and so warnings can quote them verbatim.
"""

from __future__ import annotations

from typing import Any, List, Mapping, Sequence

__all__ = [
    "COMPLEX_REASON_LABELS",
    "COMPLEX_REASONS",
    "COMPLEX_TABLE_MAX_COLS",
    "COMPLEX_TABLE_MAX_ROWS",
    "assess_table_complexity",
    "describe_complexity",
    "table_markdown",
]

#: A table wider than this many columns is unusual enough that the vector-rule
#: reconstruction is likely to be wrong.
COMPLEX_TABLE_MAX_COLS = 12
#: Same for very long tables.
COMPLEX_TABLE_MAX_ROWS = 40

#: Reason codes produced by :func:`assess_table_complexity`.
COMPLEX_REASONS = (
    "merged_cells",
    "cell_cap_truncated",
    "wide_table",
    "tall_table",
    "table_detection_failed",
    "borderless_table_candidate",
)

#: Human-readable labels for the reason codes (used in warnings).
COMPLEX_REASON_LABELS = {
    "merged_cells": "合并单元格或缺格造成表格空洞",
    "cell_cap_truncated": "表格过大已被截断",
    "wide_table": "超宽表格",
    "tall_table": "超长表格",
    "table_detection_failed": "部分页面的表格识别失败",
    "borderless_table_candidate": "疑似无边框表格",
}


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def table_markdown(rows: Sequence[Sequence[Any]]) -> str:
    """Render table rows as a GitHub-flavoured Markdown table."""
    if not rows:
        return ""
    lines = ["| " + " | ".join(_cell(cell) for cell in rows[0]) + " |"]
    lines.append("| " + " | ".join("---" for _ in rows[0]) + " |")
    for row in rows[1:]:
        lines.append("| " + " | ".join(_cell(cell) for cell in row) + " |")
    return "\n".join(lines)


def assess_table_complexity(diagnostics: Mapping[str, Any]) -> List[str]:
    """Return the reason codes explaining why the tables are complex.

    An empty list means the tables are plain enough for the light backend.
    Unknown / missing keys are treated as "not complex" — the diagnostics
    are advisory, never a reason to fail an extraction.
    """
    if not diagnostics:
        return []
    reasons: List[str] = []
    if int(diagnostics.get("null_cells") or 0) > 0:
        reasons.append("merged_cells")
    if diagnostics.get("truncated"):
        reasons.append("cell_cap_truncated")
    if int(diagnostics.get("max_cols") or 0) >= COMPLEX_TABLE_MAX_COLS:
        reasons.append("wide_table")
    if int(diagnostics.get("max_rows") or 0) >= COMPLEX_TABLE_MAX_ROWS:
        reasons.append("tall_table")
    if int(diagnostics.get("failed_pages") or 0) > 0:
        reasons.append("table_detection_failed")
    if diagnostics.get("borderless_candidate_pages"):
        reasons.append("borderless_table_candidate")
    return reasons


def describe_complexity(reasons: Sequence[str]) -> str:
    """Render reason codes as a short Chinese phrase for warnings."""
    if not reasons:
        return ""
    return "、".join(COMPLEX_REASON_LABELS.get(code, code) for code in reasons)
