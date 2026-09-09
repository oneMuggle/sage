"""XLSX reader using openpyxl + pandas.

Per plan §6 Q6 user decision: uses BOTH openpyxl (low-level cell access)
and pandas (DataFrame-style operations for future generators).

For READ, we primarily use openpyxl because:
- openpyxl gives fine-grained cell access (formulas, merged cells, types)
- data_only=True returns computed formula values (cached by Excel/LibreOffice)
- pandas.read_excel() is heavier and loads everything into a single DataFrame

pandas will be used in Phase 1.4 generators (ExcelSheetSpec → DataFrame → xlsx).

It does NOT extract:
- charts (counted but not data extracted)
- pivot tables
- macros / VBA
- data validation rules
- conditional formatting

These omissions are intentional per plan §1.3 "non-goals".
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from openpyxl import load_workbook

from .errors import OfficeFileNotFoundError, OfficeParseError
from .models import (
    ExcelSheetContent,
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
    OfficeExcelReadResult,
)

logger = logging.getLogger(__name__)

#: 公式单元格缺缓存值时附加在读取结果里的一行提示（openpyxl 不能计算公式，
#: 缓存值要等 Excel/LibreOffice 打开后重算写入）。Round2 R5：缺缓存值时
#: 先尝试 formulas 本地求值（excel_eval.evaluate_workbook），全部公式都
#: 解析出值的 sheet 不再附此提示；仍有未解析公式时保留。
_FORMULA_CACHE_NOTE = "公式计算值需在 Excel 中打开后生效"

#: 数值类型元组常量：py38 兼容（isinstance 的 ``int | float`` 写法需 3.10+），
#: 同时绕开 ruff UP038（同 errors.py 的 _WRITE_FAILURE_ERRORS 惯例）。
_NUMERIC_TYPES = (int, float)


def _cell_value_to_str(value: Any) -> str:
    """Convert any cell value to its string representation.

    - None → empty string
    - str → as-is (stripped)
    - int/float/bool → str(value)
    - datetime/date → ISO format
    - other → repr(value)
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        # bool is subclass of int; check first
        return "true" if value else "false"
    if isinstance(value, _NUMERIC_TYPES):
        return str(value)
    # datetime / date
    try:
        # Check for datetime-like without importing datetime explicitly
        iso = value.isoformat()  # type: ignore[attr-defined]
        return str(iso)
    except AttributeError:
        return repr(value)


def _extract_sheet_rows(ws) -> tuple[List[List[str]], int, int]:
    """Extract all rows from a worksheet as List[List[str]] + max_row + max_col.

    Merged cells: only the top-left cell has the value; other cells in the
    merge return None. We surface empty strings for those positions to give
    callers a consistent grid (callers can still detect merged ranges via
    ws.merged_cells.ranges if needed).
    """
    rows: List[List[str]] = []
    max_row = ws.max_row or 0
    max_col = ws.max_column or 0

    for row_idx in range(1, max_row + 1):
        row: List[str] = []
        for col_idx in range(1, max_col + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            row.append(_cell_value_to_str(cell.value))
        # Skip rows that are entirely empty (all cells blank)
        if any(cell != "" for cell in row):
            rows.append(row)

    return rows, max_row, max_col


def _extract_sheet_formulas(ws_formula, ws_values) -> tuple[List[str], bool]:
    """Collect formula cells as ``CELL=formula_text`` entries + missing-cache flag.

    ``ws_formula`` is the ``data_only=False`` worksheet (formulas visible),
    ``ws_values`` the matching ``data_only=True`` one (cached values only).
    openpyxl cannot evaluate formulas — a cached value is present only when
    Excel/LibreOffice already saved the file, so it is appended where
    available:

        no cache   ->  "B4=SUM(B2:B3)"
        cache hit  ->  "B4=SUM(B2:B3) → 30"

    Returns ``(entries, any_cache_missing)``. Array formulas (stored as
    ``ArrayFormula`` objects, not str) are skipped.
    """
    entries: List[str] = []
    any_cache_missing = False
    for row in ws_formula.iter_rows():
        for cell in row:
            value = cell.value
            if not isinstance(value, str) or not value.startswith("="):
                continue
            cached = ws_values.cell(row=cell.row, column=cell.column).value
            # 去掉开头的 '='，用单个 '=' 连接坐标 → "B4=SUM(B2:B3)"
            body = value[1:]
            if cached is None:
                entries.append(f"{cell.coordinate}={body}")
                any_cache_missing = True
            else:
                entries.append(
                    f"{cell.coordinate}={body} → {_cell_value_to_str(cached)}"
                )
    return entries, any_cache_missing


def _apply_local_eval(
    entries: List[str], resolved: Optional[Dict[str, Any]]
) -> List[str]:
    """R5（Round2）：把本地求值结果回填进缺缓存值的公式条目。

    ``B4=SUM(B2:B3)`` → ``B4=SUM(B2:B3) → 30 (本地求值)``。只处理还没有
    ``→ 值`` 标记（即缺缓存值）的条目；坐标未命中或求值结果为 None 时
    视为未解析、保持原样（读取侧据此决定是否保留缓存提示行）。
    """
    if not resolved:
        return entries
    out: List[str] = []
    for entry in entries:
        coord, sep, body = entry.partition("=")
        value = resolved.get(coord) if sep else None
        if sep and value is not None and " → " not in body:
            out.append(f"{coord}={body} → {_cell_value_to_str(value)} (本地求值)")
        else:
            out.append(entry)
    return out


def _build_xlsx_summary(
    file_path: Path,
    *,
    document_id: str,
    workspace_path: str,
    generated_filename: Optional[str],
    original_filename: Optional[str],
    status: OfficeDocStatus,
    sheet_count: int,
) -> OfficeDocumentSummary:
    """Construct a summary for an XLSX document."""
    now_ms = int(time.time() * 1000)
    return OfficeDocumentSummary(
        id=document_id,
        workspace_path=workspace_path,
        doc_type=OfficeDocType.EXCEL,
        original_filename=original_filename,
        generated_filename=generated_filename or file_path.name,
        status=status,
        created_at=now_ms,
        updated_at=now_ms,
        metadata=OfficeDocumentMetadata(
            page_count=None,
            sheet_count=sheet_count,
            table_count=None,
            paragraph_count=None,
            file_size_bytes=file_path.stat().st_size,
        ),
    )


def read_xlsx(
    file_path: Path,
    *,
    document_id: Optional[str] = None,
    workspace_path: str = "",
    generated_filename: Optional[str] = None,
    original_filename: Optional[str] = None,
    include_formulas: bool = False,
) -> OfficeExcelReadResult:
    """Read a .xlsx file and return its structured content.

    Args:
        file_path: Absolute path to the .xlsx file.
        document_id: Optional UUID for the summary record. Defaults to file_path.stem.
        workspace_path: Required by storage layer; pass empty string for read-only tests.
        generated_filename: Filename as stored in workspace/office/<id>/.
        original_filename: User's uploaded filename.
        include_formulas: 公式视图（Item 1.4）。True 时再加载一份
            ``data_only=False`` 工作簿，把每个公式单元格以
            ``CELL=formula_text`` 形式列进该 sheet 的 ``formulas``
            （有缓存值时为 ``CELL=formula → cached``）；存在无缓存值的
            公式时在 ``note`` 附上「公式计算值需在 Excel 中打开后生效」。
            openpyxl 不能自行计算公式，缺缓存值属正常现象。
            R5（Round2）：存在缺缓存值公式时用 ``formulas`` 库本地求值
            （见 :mod:`.excel_eval`，全 fail-safe），求出值的条目升级为
            ``CELL=formula → value (本地求值)``；某 sheet 的公式全部解析
            出值时不再附 ``note``。求值仅在 include_formulas=True 且至少
            一个缓存值缺失时触发，且有公式数/超时上限。

    Returns:
        OfficeExcelReadResult with summary + sheets array (each with name + rows
        + max_row + max_col, plus formulas/note when ``include_formulas``).

    Raises:
        OfficeFileNotFoundError: file doesn't exist.
        OfficeParseError: file exists but isn't a valid XLSX.
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise OfficeFileNotFoundError(file_path)
    if not file_path.is_file():
        raise OfficeParseError(f"Path is not a regular file: {file_path}", file_path=file_path)

    try:
        # data_only=True: read computed values instead of formula strings
        wb = load_workbook(str(file_path), data_only=True)
    except Exception as exc:
        # openpyxl raises zipfile.BadZipFile, lxml.etree.XMLSyntaxError, etc.
        raise OfficeParseError(f"Failed to parse XLSX: {exc}", file_path=file_path) from exc

    wb_formulas = None
    if include_formulas:
        try:
            # data_only=False: 公式文本可见（缓存值走上面的 wb）
            wb_formulas = load_workbook(str(file_path), data_only=False)
        except Exception as exc:
            raise OfficeParseError(f"Failed to parse XLSX: {exc}", file_path=file_path) from exc

    # R5（Round2）：先收集各 sheet 的公式条目；任一 sheet 存在缺缓存值的
    # 公式时，才用 formulas 库做一次整簿本地求值（evaluate_workbook 内部
    # 全 fail-safe，失败返回 None → 行为与不引入求值时完全一致）。
    collected: List[Tuple[str, List[List[str]], int, int, Optional[List[str]]]] = []
    any_cache_missing = False
    for ws in wb.worksheets:
        rows, max_row, max_col = _extract_sheet_rows(ws)
        entries: Optional[List[str]] = None
        if wb_formulas is not None and ws.title in wb_formulas.sheetnames:
            formula_entries, sheet_cache_missing = _extract_sheet_formulas(
                wb_formulas[ws.title], ws
            )
            if formula_entries:
                entries = formula_entries
                if sheet_cache_missing:
                    any_cache_missing = True
        collected.append((ws.title, rows, max_row, max_col, entries))

    evaluated: Optional[Dict[str, Dict[str, Any]]] = None
    if any_cache_missing:
        from .excel_eval import evaluate_workbook

        evaluated = evaluate_workbook(file_path)

    sheets: List[ExcelSheetContent] = []
    for title, rows, max_row, max_col, entries in collected:
        formulas_out: Optional[List[str]] = None
        note: Optional[str] = None
        if entries:
            if evaluated:
                formulas_out = _apply_local_eval(entries, evaluated.get(title))
            else:
                formulas_out = entries
            # 缓存提示只对仍有「无缓存值且求值未解析」公式的 sheet 保留；
            # 全部公式都解析出值时省略。
            if any(" → " not in entry for entry in formulas_out):
                note = _FORMULA_CACHE_NOTE
        sheets.append(
            ExcelSheetContent(
                name=title,
                rows=rows,
                max_row=max_row,
                max_col=max_col,
                formulas=formulas_out,
                note=note,
            )
        )

    doc_id = document_id or file_path.stem

    summary = _build_xlsx_summary(
        file_path,
        document_id=doc_id,
        workspace_path=workspace_path,
        generated_filename=generated_filename,
        original_filename=original_filename,
        status=OfficeDocStatus.PARSED,
        sheet_count=len(sheets),
    )

    return OfficeExcelReadResult(summary=summary, sheets=sheets)


# ──────────────────────────────────────────────────────────────────────
# Generator (Phase 1.4 step 19, plan §4.1.4)
# ──────────────────────────────────────────────────────────────────────


def _mark_formula_cells(wb) -> int:
    """把以 '=' 开头的字符串单元格改写为真正的公式（Item 1.4）。

    openpyxl 只在 ``Cell.value`` 赋值时按 '=' 前缀推断公式类型；pandas
    ``df.to_excel`` 的写入路径（随版本不同）可能把这些单元格留成纯文本。
    生成完成后统一兜底：对仍是字符串且以 '=' 开头的单元格重新赋值一次，
    触发 openpyxl 的公式类型标记。返回改写数量（诊断用）。

    Write-only 工作簿（pandas 部分版本使用）不可随机访问单元格，其
    append 路径本身按赋值语义写入（'=' 前缀已是公式），直接跳过。
    """
    if getattr(wb, "write_only", False):
        return 0
    count = 0
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                value = cell.value
                if (
                    isinstance(value, str)
                    and value.startswith("=")
                    and cell.data_type != "f"
                ):
                    cell.value = value  # 重新赋值触发公式类型推断
                    count += 1
    return count


def _apply_sheet_column_widths(writer, req) -> int:
    """批次 2.3：把 ExcelSheetSpec.column_widths 写入对应 worksheet。

    在 ``pd.ExcelWriter`` 上下文内、工作簿保存前调用；宽度单位为 Excel
    字符宽度（与 openpyxl ``column_dimensions[..].width`` 一致）。返回
    设置的列数（诊断用）。
    """
    from openpyxl.utils import get_column_letter

    applied = 0
    for sheet_spec in getattr(req, "sheets", None) or ():
        widths = getattr(sheet_spec, "column_widths", None)
        if not widths:
            continue
        ws = writer.sheets.get(sheet_spec.name[:31])
        if ws is None:
            continue
        for col_idx, width in enumerate(widths[:200], start=1):
            ws.column_dimensions[get_column_letter(col_idx)].width = float(width)
            applied += 1
    return applied


def _apply_generate_charts(writer, req) -> int:
    """批次 2.1：工作簿保存前挂载 ``req.charts`` 的 Excel 原生图表。

    ``chart_spec.sheet`` 缺省挂到第一个 sheet。 Raises ValueError（由
    generate_xlsx 折算为 OfficeGenerateError）。
    """
    from .charts import build_openpyxl_chart

    applied = 0
    book = writer.book
    for chart_spec in getattr(req, "charts", None) or ():
        name = getattr(chart_spec, "sheet", None) or (
            book.sheetnames[0] if book.sheetnames else None
        )
        if not name or name not in book.sheetnames:
            raise ValueError(f"chart_sheet_not_found: {getattr(chart_spec, 'sheet', None)!r}")
        build_openpyxl_chart(book[name], chart_spec)
        applied += 1
    return applied


def generate_xlsx(req, output_dir: Optional[str] = None) -> Path:
    """Generate a .xlsx file from structured Pydantic input.

    ``output_dir`` 提供时写入该任意目录（信任的用户指定目录，经
    :func:`resolve_output_path` 校验文件名）；``None`` 时保持现状写
    workspace 沙箱（``<workspace>/office/excel/<uuid>/<name>``）。

    Per user Q6, uses both openpyxl (low-level sheet creation) and pandas
    (DataFrame-based row writing for ergonomic bulk insert).

    Item 1.4: 以 '=' 开头的字符串单元格写为真正的 Excel 公式（隐式约定，
    无需开关）；读取侧用 ``read_xlsx(include_formulas=True)`` 查看公式。
    """
    import uuid

    from openpyxl import Workbook

    from .errors import OfficeGenerateError
    from .models import OfficeDocType
    from .path_safety import managed_document_path, resolve_output_path
    from .storage import validate_workspace

    if output_dir is not None:
        output_path = resolve_output_path(output_dir, OfficeDocType.EXCEL, req.filename)
    else:
        workspace = validate_workspace(Path(req.workspace_path))
        doc_id = uuid.uuid4().hex
        output_path = managed_document_path(workspace, OfficeDocType.EXCEL, doc_id, req.filename)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Per Sprint 1 PR-1 (sage-excel-capability-assessment-2026-09-09):
        # generate_xlsx now actually uses pandas. We build a one-row-or-more
        # DataFrame per sheet and let pandas.ExcelWriter + df.to_excel
        # handle file format, sheet creation, and cell-by-cell writes.
        # This still depends on openpyxl under the hood (the engine), but
        # pandas gives us:
        #  - automatic row/column alignment (ragged rows become NaN → "")
        #  - type coercion (numeric strings stay strings; "007" is preserved)
        #  - ergonomic bulk insert for future multi-sheet templates
        # Behaviour parity with the previous openpyxl-cell-by-loop is locked
        # down by backend/tests/{unit,integration}/office/test_*_*.py.

        # ``ExcelWriter(engine="openpyxl")`` creates an empty workbook on
        # disk; df.to_excel(writer, sheet_name=...) adds each sheet.
        # Note: ExcelWriter does NOT emit a default Sheet — sheets are
        # only created by to_excel calls. Empty-sheet cases (zero to_excel
        # calls) would leave a corrupt/empty .xlsx, so we fall back to
        # openpyxl Workbook creation in that pathological case.
        if not req.sheets:
            # Defensive: Pydantic constrains sheets to min_length=1, so this
            # branch is unreachable through the API. Kept for direct callers.
            wb = Workbook()
            wb.remove(wb.active)
            wb.save(str(output_path))
            return output_path

        # Build all DataFrames first so we can detect the all-empty case
        # before opening the writer (avoids writing a file with no sheets).
        sheet_specs: list[tuple[str, pd.DataFrame, bool]] = []
        for sheet_spec in req.sheets:
            name = sheet_spec.name[:31]  # Excel 31-char sheet-name cap
            headers = sheet_spec.headers
            rows = sheet_spec.rows

            if headers or rows:
                # Build DataFrame. With columns=headers, pandas enforces the
                # column count and pads/truncates ragged rows with NaN. We
                # fill NaN with "" so the reader (which returns "" for empty
                # cells) sees the same string grid as before.
                df = pd.DataFrame(rows, columns=headers).fillna("")
            else:
                # Empty sheet: still need a sheet object but no data.
                df = pd.DataFrame()

            sheet_specs.append((name, df, bool(headers)))

        # Pathological case: all sheets are empty AND we have at least one.
            # ExcelWriter + zero to_excel calls would produce an empty file,
            # which openpyxl can't read back as a valid workbook. Fall back
            # to a minimal openpyxl Workbook with one empty sheet.
            if all(df.empty and not has_headers for _, df, has_headers in sheet_specs):
                wb = Workbook()
                wb.remove(wb.active)
                for name, _, _ in sheet_specs:
                    wb.create_sheet(title=name)
                wb.save(str(output_path))
                return output_path

        with pd.ExcelWriter(str(output_path), engine="openpyxl") as writer:
            for name, df, has_headers in sheet_specs:
                df.to_excel(
                    writer,
                    sheet_name=name,
                    index=False,
                    header=has_headers,
                )
            # Item 1.4: '=' 前缀的字符串单元格统一兜底为真公式
            # （无公式时零改动；见 _mark_formula_cells）。
            _mark_formula_cells(writer.book)
            # 批次 2.3：按 sheet 写入可选列宽；批次 2.1：挂载原生图表
            # （必须在 writer 保存前，图表才会随工作簿序列化）。
            _apply_sheet_column_widths(writer, req)
            _apply_generate_charts(writer, req)
    except Exception as exc:
        raise OfficeGenerateError(f"Failed to generate XLSX: {exc}", file_path=output_path) from exc

    return output_path
