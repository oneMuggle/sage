# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Office 数据分析工具（Office Parity Batch-2 item 2.2，对标 ChatGPT 数据分析）。

``office_analyze`` 把已验证的本地 Excel 分析能力接入 LLM 工具面：
pandas 读 xlsx → 按序执行 1-5 个分析操作（describe / value_counts /
aggregate / corr）→ 结果以紧凑 markdown 表格进 ToolResult；可选
``write_report=true`` 把完整结果落成 ``<stem>-analysis.xlsx`` 分析报告
（summary sheet + 每 op 一个 sheet + aggregate 原生柱状图）。

安全姿态与 :mod:`backend.tools.office_pdf_tool` 的读工具一致：

1. ``requires_tool_context = True``（读类工具，同 office_read_pdf）：
   registry 在无活动 ``ToolExecutionContext`` 时隐藏 schema；execute()
   顶部再 fail-closed。file_path 模式同样要求已绑定上下文（batch-1
   读工具先例 —— 分析本身就需要工作区语境）。
2. doc_id 模式经 session-workspace binding 解析（EXCEL 类型），未知 /
   归档 / 跨工作区 / 过期 generation / 类型不符一律折叠为
   ``document_not_found``；file_path 模式经 ``_enforce_workspace`` +
   扩展名白名单把守。
3. 分析报告是「派生产物」：永远写在源文件同目录、文件名固定为
   ``<stem>-analysis.xlsx``（LLM 不能自选写入落点），file_path 模式下
   再经 ``resolve_within`` containment 复核；覆盖写走「临时名 +
   ``os.replace``」原子语义。写入成功记 Artifacts（静默失败不阻断）。
4. 输出按 ``policy.max_output_bytes`` 截断（``_bounded`` 语义同
   tool_service / office_pdf_tool），每个表格自身再按行数/宽度截断。
5. LLM 面不回显 binding 绝对 workspace_path：doc_id 模式下源文件名
   替换为受管 ``generated_filename``。

依赖姿态：pandas 是主渠道依赖（requirements.txt）但不进 Win7/py38
bundle —— 与 charts.py 的 matplotlib 懒加载同理，pandas / openpyxl 都
延迟到 execute() 内 import；pandas 缺失返回干净的工具错误
（"数据分析需要 pandas（本机未安装）"）而不是崩溃。原生图表经
:func:`backend.office.charts.build_openpyxl_chart`（charts.py 机制），
best-effort：图表失败不影响报告写入。

Public surface:

    OfficeAnalyzeTool(policy=None)   # name="office_analyze"
"""

from __future__ import annotations

import contextlib
import json
import math
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from backend.data.database import get_database
from backend.domain.risk import RiskClass
from backend.office.errors import (
    OfficeError,
    OfficeFileNotFoundError,
    OfficePathError,
    OfficeSizeLimitError,
)
from backend.office.models import OfficeDocType
from backend.office.session_workspace import (
    get_active_workspace,
    get_document_in_workspace,
)
from backend.office.storage import document_path
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.context import ToolExecutionContext, current_tool_context
from backend.tools.file_tool import _record_artifact_safely

# ──────────────────────────────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────────────────────────────

#: 支持的操作类型（LLM 面取值）
_OP_KINDS = ("describe", "value_counts", "aggregate", "corr")
#: aggregate.agg 合法取值
_AGGS = ("sum", "mean", "count", "min", "max")
#: operations 数量上限
_MAX_OPS = 5
#: 单表渲染行数上限（超出截断并注明）
_MAX_TABLE_ROWS = 40
#: value_counts 默认 / 最大 top_n
_DEFAULT_TOP_N = 10
_MAX_TOP_N = 100
#: describe / corr 矩阵的列数上限（宽表截断，防 token 爆炸）
_MAX_MATRIX_COLS = 12
#: markdown 单元格字符宽度上限
_MAX_CELL_CHARS = 50
#: 顶层 columns 名单回显上限
_MAX_COLUMN_NAMES = 50

#: Excel sheet 名非法字符
_SHEET_NAME_INVALID = re.compile(r"[\[\]\:\*\?\/\\]")

#: isinstance 元组常量：py38 兼容 + 绕开 UP038（同 excel._NUMERIC_TYPES 惯例）
_STR_BOOL_TYPES = (bool, str)
#: 数值类型元组常量：py38 兼容 + 绕开 UP038
_NUMERIC_TYPES = (int, float)


# ──────────────────────────────────────────────────────────────────────
# 共享小助手（office_pdf_tool.py 内有镜像副本，保持模块自包含）
# ──────────────────────────────────────────────────────────────────────


def _resolve_bound_document(
    ctx: ToolExecutionContext,
    doc_id: str,
    expected_doc_type: OfficeDocType,
) -> Optional[Tuple[Path, str, Any]]:
    """binding 内解析 doc_id → (on-disk path, workspace_path, summary)。"""
    try:
        conn = get_database().get_connection()
    except Exception:
        return None
    binding = get_active_workspace(
        conn, ctx.session_id, expected_generation=ctx.binding_generation
    )
    if binding is None:
        return None
    doc = get_document_in_workspace(conn, doc_id, binding.workspace_path)
    if doc is None or doc.doc_type is not expected_doc_type:
        return None
    return document_path(doc), binding.workspace_path, doc


def _resolve_active_workspace(ctx: Optional[ToolExecutionContext]) -> Optional[Path]:
    """有活动绑定 → 绑定工作区 Path；否则 ``None``（DB 不可用同样吞掉）。"""
    if ctx is None or not ctx.session_id:
        return None
    try:
        conn = get_database().get_connection()
        binding = get_active_workspace(
            conn, ctx.session_id, expected_generation=ctx.binding_generation
        )
    except Exception:
        return None
    if binding is None:
        return None
    return Path(binding.workspace_path)


def _workspace_for_input(
    ctx: Optional[ToolExecutionContext], input_path: Path
) -> Path:
    """file_path 模式的 workspace 取值：优先绑定工作区，回退输入父目录。"""
    binding_ws = _resolve_active_workspace(ctx)
    if binding_ws is not None:
        return binding_ws
    return input_path.parent


def _bounded(data: Dict[str, Any], max_bytes: int) -> Dict[str, Any]:
    """超 ``max_bytes`` 时退化为 bounded head，语义同 tool_service。"""
    serialized = json.dumps(data, ensure_ascii=False, default=str)
    raw = serialized.encode("utf-8")
    if len(raw) <= max_bytes:
        return data
    head = raw[:max_bytes].decode("utf-8", errors="ignore")
    return {"truncated": True, "max_output_bytes": max_bytes, "head": head}


def _office_error_result(exc: Exception, fallback: str) -> ToolResult:
    """Office 异常 → 安全错误码。"""
    if isinstance(exc, OfficeFileNotFoundError):
        code = "file_not_found"
    elif isinstance(exc, OfficeSizeLimitError):
        code = "file_too_large"
    elif isinstance(exc, OfficePathError):
        code = "path_invalid"
    else:
        code = fallback
    message = str(exc)
    return ToolResult(success=False, error=f"{code}: {message}" if message else code)


def _resolve_xlsx_input(  # noqa: PLR0911 — 错误早退路径多，保持线性可读
    tool: BaseTool,
    ctx: Optional[ToolExecutionContext],
    doc_id: Optional[str],
    file_path: Optional[str],
) -> Union[Tuple[Path, str, Any], ToolResult]:
    """解析 doc_id / file_path 双模式输入（doc_id 优先，EXCEL 类型）。"""
    if isinstance(doc_id, str) and doc_id.strip():
        if ctx is None:
            return ToolResult(success=False, error="missing_tool_context")
        found = _resolve_bound_document(ctx, doc_id.strip(), OfficeDocType.EXCEL)
        if found is None:
            return ToolResult(success=False, error="document_not_found")
        return found
    if isinstance(file_path, str) and file_path.strip():
        blocked = tool._enforce_workspace(file_path)
        if blocked is not None:
            return blocked
        path = Path(file_path).expanduser()
        if not path.is_absolute():
            return ToolResult(
                success=False,
                error="file_path_absolute_required: 请传绝对路径",
            )
        if path.suffix.lower() != ".xlsx":
            return ToolResult(
                success=False,
                error="unsupported_file_type: 仅支持 .xlsx",
            )
        workspace = _workspace_for_input(ctx, path)
        return path, str(workspace), None
    return ToolResult(success=False, error="doc_id_or_file_path_required")


# ──────────────────────────────────────────────────────────────────────
# 参数校验 + 值清洗 + 渲染小助手
# ──────────────────────────────────────────────────────────────────────


def _validate_operations(operations: Any) -> Union[List[Dict[str, Any]], ToolResult]:  # noqa: PLR0911 — 错误早退路径多，保持线性可读
    """fail-fast 校验 operations（1-5 个、kind 合法、必填参数齐备）。"""
    if not isinstance(operations, list) or not operations:
        return ToolResult(success=False, error="operations_required")
    if len(operations) > _MAX_OPS:
        return ToolResult(
            success=False,
            error=f"too_many_operations: 最多 {_MAX_OPS} 个操作",
        )
    normalized: List[Dict[str, Any]] = []
    for idx, op in enumerate(operations):
        if not isinstance(op, dict):
            return ToolResult(
                success=False, error=f"operation_invalid: 第 {idx + 1} 个操作不是对象"
            )
        kind = op.get("kind")
        if kind not in _OP_KINDS:
            return ToolResult(
                success=False,
                error=(
                    f"unsupported_operation: {kind!r}（支持 "
                    f"{'/'.join(_OP_KINDS)}）"
                ),
            )
        clean: Dict[str, Any] = {"kind": kind}
        if kind == "value_counts":
            column = op.get("column")
            if not isinstance(column, str) or not column.strip():
                return ToolResult(
                    success=False, error="value_counts_column_required"
                )
            clean["column"] = column.strip()
            top_n = op.get("top_n", _DEFAULT_TOP_N)
            if not isinstance(top_n, int) or isinstance(top_n, bool) or top_n < 1:
                top_n = _DEFAULT_TOP_N
            clean["top_n"] = min(int(top_n), _MAX_TOP_N)
        elif kind == "aggregate":
            group_by = op.get("group_by")
            if not isinstance(group_by, str) or not group_by.strip():
                return ToolResult(
                    success=False, error="aggregate_group_by_required"
                )
            clean["group_by"] = group_by.strip()
            agg = op.get("agg", "sum")
            if agg not in _AGGS:
                return ToolResult(
                    success=False,
                    error=(
                        f"unsupported_agg: {agg!r}（支持 {'/'.join(_AGGS)}）"
                    ),
                )
            clean["agg"] = agg
            column = op.get("column")
            if column is not None:
                if not isinstance(column, str) or not column.strip():
                    return ToolResult(
                        success=False, error="aggregate_column_invalid"
                    )
                column = column.strip()
            if agg != "count" and not column:
                return ToolResult(
                    success=False,
                    error=(
                        "aggregate_column_required: "
                        f"agg={agg} 需要指定数值列 column"
                    ),
                )
            clean["column"] = column
        normalized.append(clean)
    return normalized


def _clean_value(value: Any) -> Any:
    """numpy/pandas 标量 → JSON/Excel 友好的原生类型。

    str/bool/None 原样返回（避免 "123" 这类字符串取值被误转成数字）；
    数值标量统一转 float（np.int64 不是 Python int，isinstance 会漏）；
    NaN → None；其余对象转 str 兜底。
    """
    if value is None or isinstance(value, _STR_BOOL_TYPES):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isnan(number):
        return None
    return number


def _fmt(value: Any, max_chars: int = _MAX_CELL_CHARS) -> str:
    """单元格渲染：None→""，浮点 6 位有效数字，长文本截断。"""
    text: str
    if value is None:
        text = ""
    elif isinstance(value, float):
        if value == int(value) and abs(value) < 1e15:
            text = str(int(value))
        else:
            text = f"{value:.6g}"
    else:
        text = str(value)
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return text


def _render_markdown_table(columns: List[str], rows: List[List[Any]]) -> str:
    """渲染紧凑 markdown 表（``| col | ... |`` 形态）。"""
    lines = [
        "| " + " | ".join(_fmt(c) for c in columns) + " |",
        "|" + "---|" * len(columns),
    ]
    for row in rows:
        lines.append("| " + " | ".join(_fmt(c) for c in row) + " |")
    return "\n".join(lines)


def _sheet_label(base: str, used: set) -> str:
    """合法且不重复的 sheet 名（非法字符替换 + 31 字符截断 + 去重）。"""
    name = _SHEET_NAME_INVALID.sub("_", base).strip() or "sheet"
    name = name[:31]
    candidate = name
    counter = 2
    while candidate.lower() in used:
        suffix = f"-{counter}"
        candidate = name[: 31 - len(suffix)] + suffix
        counter += 1
    used.add(candidate.lower())
    return candidate


def _column_names_preview(df: Any) -> Tuple[List[str], Optional[str]]:
    """顶层回显的列名名单（截断到 _MAX_COLUMN_NAMES）。"""
    names = [str(c) for c in list(df.columns)[:_MAX_COLUMN_NAMES]]
    note = None
    total = len(df.columns)
    if total > _MAX_COLUMN_NAMES:
        note = f"共 {total} 列，仅显示前 {_MAX_COLUMN_NAMES} 个列名"
    return names, note


def _require_column(df: Any, column: str) -> Optional[ToolResult]:
    """列存在性校验；缺失时错误信息带可用列名（截断）。"""
    if column in [str(c) for c in df.columns]:
        return None
    names, _ = _column_names_preview(df)
    return ToolResult(
        success=False,
        error=(
            f"column_not_found: {column!r} 不存在（可用列: "
            f"{', '.join(names)}）"
        ),
    )


# ──────────────────────────────────────────────────────────────────────
# 分析操作（每个 op 返回 result dict：columns/rows 原生值 + table 文本）
# ──────────────────────────────────────────────────────────────────────


def _op_describe(df: Any) -> Dict[str, Any]:
    """数值列统计摘要（count/mean/std/min/四分位/max）+ 各列非空计数。"""
    numeric = df.select_dtypes(include="number")
    columns: List[str] = []
    rows: List[List[Any]] = []
    notes: List[str] = []
    if numeric.shape[1] == 0:
        notes.append("无数值列，describe 表为空")
    else:
        desc = numeric.describe()
        shown_cols = list(desc.columns)
        columns = ["stat"] + [str(c) for c in shown_cols]
        for stat_name in desc.index:
            rows.append(
                [str(stat_name)]
                + [_clean_value(desc.loc[stat_name, col]) for col in shown_cols]
            )
        if numeric.shape[1] > _MAX_MATRIX_COLS:
            notes.append(
                f"共 {numeric.shape[1]} 个数值列，仅显示前 {_MAX_MATRIX_COLS} 个"
            )

    # 各列非空计数（含字符串列）——直接并进同一结果文本。
    overview_columns = ["column", "dtype", "非空"]
    overview_rows = [
        [str(col), str(df[col].dtype), int(df[col].notna().sum())]
        for col in list(df.columns)[:_MAX_TABLE_ROWS]
    ]
    parts = []
    if columns:
        parts.append("**数值列 describe**\n" + _render_markdown_table(columns, rows))
    parts.append(
        "**各列非空计数**\n" + _render_markdown_table(overview_columns, overview_rows)
    )
    if len(df.columns) > _MAX_TABLE_ROWS:
        notes.append(f"非空计数表仅显示前 {_MAX_TABLE_ROWS} 列")
    return {
        "kind": "describe",
        "title": "describe（数值列统计摘要）",
        "columns": columns,
        "rows": rows,
        "overview_columns": overview_columns,
        "overview_rows": overview_rows,
        "table": "\n\n".join(parts),
        "notes": notes,
    }


def _op_value_counts(df: Any, column: str, top_n: int) -> Dict[str, Any]:
    """列取值频次 Top N。"""
    vc = df[column].value_counts(dropna=False)
    total_unique = int(df[column].nunique(dropna=False))
    shown = vc.head(top_n)
    rows = [[_clean_value(k), int(v)] for k, v in shown.items()]
    notes: List[str] = []
    if total_unique > len(rows):
        notes.append(
            f"共 {total_unique} 个不同取值，仅显示前 {len(rows)} 个（top_n={top_n}）"
        )
    table = _render_markdown_table([column, "count"], rows)
    return {
        "kind": "value_counts",
        "title": f"value_counts({column})",
        "columns": [column, "count"],
        "rows": rows,
        "table": table,
        "notes": notes,
    }


def _op_aggregate(df: Any, group_by: str, column: Optional[str], agg: str) -> Dict[str, Any]:
    """groupby 聚合；count 无需数值列（按组计数）。"""
    if agg == "count" and not column:
        grouped = df.groupby(group_by, dropna=False).size()
        value_header = "count"
    else:
        grouped = df.groupby(group_by, dropna=False)[column].agg(agg)
        value_header = f"{agg}({column})"
    grouped = grouped.sort_values(ascending=False)
    total_groups = int(len(grouped))
    shown = grouped.head(_MAX_TABLE_ROWS)
    rows = [[_clean_value(k), _clean_value(v)] for k, v in shown.items()]
    notes: List[str] = []
    if total_groups > len(rows):
        notes.append(
            f"共 {total_groups} 组，仅显示前 {len(rows)} 组（按 {value_header} 降序）"
        )
    table = _render_markdown_table([group_by, value_header], rows)
    return {
        "kind": "aggregate",
        "title": f"aggregate: {value_header} by {group_by}",
        "columns": [group_by, value_header],
        "rows": rows,
        "table": table,
        "notes": notes,
    }


def _op_corr(df: Any) -> Dict[str, Any]:
    """数值列相关性矩阵（紧凑，列数截断）。"""
    numeric = df.select_dtypes(include="number")
    notes: List[str] = []
    if numeric.shape[1] == 0:
        return {
            "kind": "corr",
            "title": "corr（相关性矩阵）",
            "columns": [],
            "rows": [],
            "table": "（无数值列，无法计算相关性）",
            "notes": notes,
        }
    shown_cols = list(numeric.columns)[:_MAX_MATRIX_COLS]
    corr = numeric[shown_cols].corr()
    columns = [""] + [str(c) for c in shown_cols]
    rows = [
        [str(c)] + [_clean_value(corr.loc[c, c2]) for c2 in shown_cols]
        for c in shown_cols
    ]
    if numeric.shape[1] > _MAX_MATRIX_COLS:
        notes.append(
            f"共 {numeric.shape[1]} 个数值列，矩阵仅含前 {_MAX_MATRIX_COLS} 个"
        )
    return {
        "kind": "corr",
        "title": "corr（相关性矩阵）",
        "columns": columns,
        "rows": rows,
        "table": _render_markdown_table(columns, rows),
        "notes": notes,
    }


# ──────────────────────────────────────────────────────────────────────
# 分析报告（<stem>-analysis.xlsx）
# ──────────────────────────────────────────────────────────────────────


def _write_table_to_sheet(ws: Any, columns: List[str], rows: List[List[Any]]) -> None:
    """把 op 结果表（原生值）写入 worksheet（首行表头）。"""
    ws.append([str(c) for c in columns])
    for row in rows:
        ws.append(list(row))


def _build_analysis_report(
    output_path: Path,
    *,
    source_name: str,
    sheet_name: str,
    row_count: int,
    column_count: int,
    column_names: List[str],
    results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """生成分析报告 xlsx 并原子落盘；返回写入 info（供 content 回显）。

    summary sheet：来源信息 + 行列数 + 各列非空计数；随后每个 op 一个
    sheet；aggregate sheet 追加原生柱状图（charts.py 的
    ``build_openpyxl_chart``，best-effort —— 失败不影响报告）。
    """
    from openpyxl import Workbook

    from backend.office.charts import build_openpyxl_chart

    used: set = set()
    wb = Workbook()
    ws_summary = wb.active
    ws_summary.title = _sheet_label("summary", used)
    ws_summary.append(["项目", "值"])
    ws_summary.append(["来源文件", source_name])
    ws_summary.append(["分析 sheet", sheet_name])
    ws_summary.append(["数据行数", row_count])
    ws_summary.append(["列数", column_count])
    ws_summary.append(["生成工具", "office_analyze"])
    for result in results:
        if result.get("kind") == "describe":
            ws_summary.append([])
            ws_summary.append(["各列非空计数"])
            _write_table_to_sheet(
                ws_summary,
                result.get("overview_columns") or [],
                result.get("overview_rows") or [],
            )
            break

    chart_embedded = False
    for result in results:
        if not result.get("columns"):
            continue
        ws = wb.create_sheet(title=_sheet_label(str(result["kind"]), used))
        _write_table_to_sheet(ws, result["columns"], result["rows"])
        for note in result.get("notes") or ():
            ws.append([])
            ws.append([note])
        if result.get("kind") == "aggregate" and result["rows"]:
            # 原生柱状图（Excel 打开可见、可再编辑）：数据列 B（含表头），
            # 类别列 A（数据行）。best-effort：图表失败不回滚报告。
            n_rows = len(result["rows"])
            spec = {
                "type": "bar",
                "anchor": "D2",
                "data_ref": {
                    "min_col": 2,
                    "min_row": 1,
                    "max_col": 2,
                    "max_row": n_rows + 1,
                },
                "titles_from_data": True,
                "categories_ref": {
                    "min_col": 1,
                    "min_row": 2,
                    "max_col": 1,
                    "max_row": n_rows + 1,
                },
                "title": str(result["title"])[:200],
            }
            try:
                build_openpyxl_chart(ws, spec)
                chart_embedded = True
            except Exception:  # noqa: BLE001 — 图表属锦上添花
                pass

    # 临时名 + os.replace 原子覆盖（派生产物，重跑分析直接刷新）。
    tmp_path = output_path.parent / f".analysis-{uuid.uuid4().hex}.xlsx"
    try:
        wb.save(str(tmp_path))
        tmp_path.replace(output_path)
    except Exception:
        with contextlib.suppress(OSError):
            tmp_path.unlink(missing_ok=True)
        raise
    return {
        "path": str(output_path),
        "filename": output_path.name,
        "bytes": output_path.stat().st_size,
        "sheets": list(wb.sheetnames),
        "chart_embedded": chart_embedded,
    }


# ──────────────────────────────────────────────────────────────────────
# 工具
# ──────────────────────────────────────────────────────────────────────


class OfficeAnalyzeTool(BaseTool):
    """Analyze an Excel sheet locally with pandas (describe/counts/agg/corr)."""

    requires_tool_context = True
    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_analyze",
            description=(
                "Analyze an Excel (.xlsx) sheet locally with pandas and "
                "return compact result tables: describe (numeric column "
                "stats), value_counts, group-by aggregation, correlation "
                "matrix. Optionally write a full analysis report xlsx "
                "(<name>-analysis.xlsx next to the source). Data never "
                "leaves this machine. Locate the file by doc_id (from "
                "office_list) or absolute file_path."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "description": "Excel document id from office_list.",
                    },
                    "file_path": {
                        "type": "string",
                        "description": (
                            "ABSOLUTE path to a .xlsx inside the active "
                            "chat workspace (when no doc_id)."
                        ),
                    },
                    "sheet": {
                        "type": "string",
                        "description": (
                            "Sheet name to analyze (default: first sheet)."
                        ),
                    },
                    "operations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "kind": {
                                    "type": "string",
                                    "enum": list(_OP_KINDS),
                                    "description": (
                                        "describe = numeric column stats; "
                                        "value_counts = top-N value counts; "
                                        "aggregate = group-by aggregation; "
                                        "corr = numeric correlation matrix."
                                    ),
                                },
                                "column": {
                                    "type": "string",
                                    "description": (
                                        "value_counts: 目标列；aggregate: "
                                        "被聚合的数值列（agg=count 时可省）。"
                                    ),
                                },
                                "top_n": {
                                    "type": "integer",
                                    "description": (
                                        "value_counts: 返回前 N 个取值"
                                        "（默认 10，最大 100）。"
                                    ),
                                },
                                "group_by": {
                                    "type": "string",
                                    "description": "aggregate: 分组列。",
                                },
                                "agg": {
                                    "type": "string",
                                    "enum": list(_AGGS),
                                    "description": (
                                        "aggregate: 聚合方式（默认 sum）。"
                                    ),
                                },
                            },
                            "required": ["kind"],
                        },
                        "description": (
                            "1-5 个分析操作，按顺序执行。示例: "
                            '[{"kind":"describe"},'
                            '{"kind":"aggregate","group_by":"品类",'
                            '"column":"销量","agg":"sum"}]'
                        ),
                    },
                    "write_report": {
                        "type": "boolean",
                        "description": (
                            "Also write an analysis report xlsx "
                            "(<source-stem>-analysis.xlsx, same directory "
                            "as the source; overwrite allowed). Default "
                            "false."
                        ),
                        "default": False,
                    },
                },
                "required": ["operations"],
            },
        )

    def execute(  # noqa: PLR0911 — 错误早退路径多，保持线性可读
        self,
        operations: Optional[Any] = None,
        doc_id: Optional[str] = None,
        file_path: Optional[str] = None,
        sheet: Optional[str] = None,
        write_report: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        ctx = current_tool_context()
        if ctx is None:
            return ToolResult(success=False, error="missing_tool_context")

        normalized_ops = _validate_operations(operations)
        if isinstance(normalized_ops, ToolResult):
            return normalized_ops

        resolved = _resolve_xlsx_input(self, ctx, doc_id, file_path)
        if isinstance(resolved, ToolResult):
            return resolved
        path, _workspace_str, doc = resolved

        # pandas 懒加载（主渠道依赖；Win7/py38 bundle 不含）——缺失时返回
        # 干净的工具错误而非 ImportError 崩溃。
        try:
            import pandas as pd
        except ImportError:
            return ToolResult(
                success=False,
                error="pandas_missing: 数据分析需要 pandas（本机未安装）",
            )

        # 读 sheet（openpyxl 引擎）；sheet 名缺失时报可用名单。
        sheet_name = sheet.strip() if isinstance(sheet, str) and sheet.strip() else None
        try:
            frame = pd.read_excel(
                str(path),
                sheet_name=sheet_name if sheet_name is not None else 0,
                engine="openpyxl",
            )
        except ValueError as exc:
            # pandas 对未知 sheet 名抛 ValueError；openpyxl 缺失抛 ImportError。
            return self._sheet_error(path, sheet_name, exc)
        except Exception as exc:  # noqa: BLE001 — 损坏文件等按干净错误返回
            return ToolResult(success=False, error=f"read_failed: {exc}")

        if frame.empty:
            return ToolResult(
                success=False,
                error=(
                    f"sheet_empty: {sheet_name or '第一个 sheet'} 没有可分析的数据行"
                ),
            )

        # 按序执行操作；列缺失等数据错误整单失败（错误信息带可用列名）。
        results: List[Dict[str, Any]] = []
        for op in normalized_ops:
            kind = op["kind"]
            try:
                if kind == "describe":
                    results.append(_op_describe(frame))
                elif kind == "value_counts":
                    missing = _require_column(frame, op["column"])
                    if missing is not None:
                        return missing
                    results.append(
                        _op_value_counts(frame, op["column"], op["top_n"])
                    )
                elif kind == "aggregate":
                    missing = _require_column(frame, op["group_by"])
                    if missing is not None:
                        return missing
                    if op.get("column"):
                        missing = _require_column(frame, op["column"])
                        if missing is not None:
                            return missing
                    results.append(
                        _op_aggregate(
                            frame, op["group_by"], op.get("column"), op["agg"]
                        )
                    )
                else:  # corr
                    results.append(_op_corr(frame))
            except Exception as exc:  # noqa: BLE001 — 分析失败按干净错误返回
                return ToolResult(
                    success=False,
                    error=f"analysis_failed: {kind} 执行失败（{exc}）",
                )

        row_count, column_count = int(frame.shape[0]), int(frame.shape[1])
        column_names, columns_note = _column_names_preview(frame)
        source_name = (
            doc.generated_filename if doc is not None else path.name
        )
        content: Dict[str, Any] = {
            "file": {
                "filename": source_name,
                "sheet": sheet_name or "（第一个 sheet）",
                "rows": row_count,
                "columns": column_count,
                "column_names": column_names,
            },
            "results": [
                {
                    "kind": r["kind"],
                    "title": r["title"],
                    "rows_shown": len(r["rows"]),
                    "notes": r.get("notes") or [],
                    "table": r["table"],
                }
                for r in results
            ],
        }
        if columns_note:
            content["file"]["columns_note"] = columns_note

        if write_report:
            report_path = path.parent / f"{path.stem}-analysis.xlsx"
            report_error: Optional[str] = None
            try:
                from backend.office.path_safety import resolve_within

                report_path = resolve_within(Path(_workspace_str), report_path)
            except OfficeError as exc:
                report_error = f"report_failed: {exc}"
            if report_error is None:
                try:
                    report_info = _build_analysis_report(
                        report_path,
                        source_name=str(source_name),
                        sheet_name=sheet_name or "（第一个 sheet）",
                        row_count=row_count,
                        column_count=column_count,
                        column_names=column_names,
                        results=results,
                    )
                    content["report"] = report_info
                    # 记录 Artifacts（无 tool_context 时静默跳过，不阻断）。
                    _record_artifact_safely(
                        str(report_path), int(report_info["bytes"])
                    )
                except Exception as exc:  # noqa: BLE001 — 报告失败不吞分析结果
                    content["report"] = {
                        "success": False,
                        "error": f"report_failed: {exc}",
                    }

        return ToolResult(
            success=True, content=_bounded(content, self._policy.max_output_bytes)
        )

    @staticmethod
    def _sheet_error(path: Path, sheet_name: Optional[str], exc: ValueError) -> ToolResult:
        """sheet 名错误 → sheet_not_found + 可用 sheet 名单；其余原样透传。"""
        available: Optional[List[str]] = None
        try:
            from openpyxl import load_workbook

            wb = load_workbook(str(path), read_only=True)
            try:
                available = list(wb.sheetnames)
            finally:
                wb.close()
        except Exception:  # noqa: BLE001 — 名单拿不到就退回原始错误
            available = None
        if sheet_name is not None and available is not None and sheet_name not in available:
            return ToolResult(
                success=False,
                error=(
                    f"sheet_not_found: {sheet_name!r} 不存在"
                    f"（可用: {', '.join(available)}）"
                ),
            )
        return ToolResult(success=False, error=f"read_failed: {exc}")


__all__ = ["OfficeAnalyzeTool"]
