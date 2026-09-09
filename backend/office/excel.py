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
from typing import Any, List, Optional

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
    if isinstance(value, int | float):
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
) -> OfficeExcelReadResult:
    """Read a .xlsx file and return its structured content.

    Args:
        file_path: Absolute path to the .xlsx file.
        document_id: Optional UUID for the summary record. Defaults to file_path.stem.
        workspace_path: Required by storage layer; pass empty string for read-only tests.
        generated_filename: Filename as stored in workspace/office/<id>/.
        original_filename: User's uploaded filename.

    Returns:
        OfficeExcelReadResult with summary + sheets array (each with name + rows
        + max_row + max_col).

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

    sheets: List[ExcelSheetContent] = []
    for ws in wb.worksheets:
        rows, max_row, max_col = _extract_sheet_rows(ws)
        sheets.append(
            ExcelSheetContent(
                name=ws.title,
                rows=rows,
                max_row=max_row,
                max_col=max_col,
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


def generate_xlsx(req, output_dir: Optional[str] = None) -> Path:
    """Generate a .xlsx file from structured Pydantic input.

    ``output_dir`` 提供时写入该任意目录（信任的用户指定目录，经
    :func:`resolve_output_path` 校验文件名）；``None`` 时保持现状写
    workspace 沙箱（``<workspace>/office/excel/<uuid>/<name>``）。

    Per user Q6, uses both openpyxl (low-level sheet creation) and pandas
    (DataFrame-based row writing for ergonomic bulk insert).
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
    except Exception as exc:
        raise OfficeGenerateError(f"Failed to generate XLSX: {exc}", file_path=output_path) from exc

    return output_path
