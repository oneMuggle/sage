"""Round-trip tests for Sprint 1 PR-1: generate_xlsx uses pandas internally.

These tests verify behaviour that the pandas-based generator guarantees
beyond what test_generators.py covers:

1. Generated XLSX is readable by openpyxl read_xlsx() — round-trip works
2. Ragged rows (different column counts) are padded with empty strings
3. Multiple sheets round-trip with sheet name preservation
4. Numeric strings ("007") stay as strings, not coerced to int 7
5. Sheet count + sheet name + cell values all survive the round trip

Locks down behaviour parity between pandas.DataFrame.to_excel() and the
previous openpyxl-cell-by-cell write loop.
"""

from __future__ import annotations

from pathlib import Path

from backend.office.excel import generate_xlsx, read_xlsx
from backend.office.models import (
    ExcelSheetSpec,
    OfficeExcelGenerateRequest,
)


def test_pandas_generate_then_openpyxl_read_roundtrip(tmp_path: Path) -> None:
    """Generate with pandas, read with openpyxl — values must survive.

    This is the canonical Sprint 1 PR-1 guarantee: the generator no longer
    writes cells directly, but the output must still be a valid xlsx that
    the existing openpyxl-based reader can parse.
    """
    req = OfficeExcelGenerateRequest(
        workspace_path=str(tmp_path),
        filename="pandas-roundtrip",
        sheets=[
            ExcelSheetSpec(
                name="Sales",
                headers=["Quarter", "Revenue"],
                rows=[
                    ["Q1", "100"],
                    ["Q2", "150"],
                    ["Q3", "200"],
                ],
            ),
        ],
    )
    output_path = generate_xlsx(req)
    assert output_path.exists()

    result = read_xlsx(output_path)
    assert len(result.sheets) == 1
    sheet = result.sheets[0]
    assert sheet.name == "Sales"
    # Pandas writes strings as strings — reader converts numeric strings via
    # str() so "100" stays "100" rather than 100.
    assert sheet.rows[0] == ["Quarter", "Revenue"]
    assert sheet.rows[1] == ["Q1", "100"]
    assert sheet.rows[2] == ["Q2", "150"]
    assert sheet.rows[3] == ["Q3", "200"]


def test_pandas_ragged_rows_padded_with_empty_strings(tmp_path: Path) -> None:
    """Ragged rows (different column counts) are padded, not truncated.

    pandas.DataFrame(rows, columns=headers) + fillna("") ensures short rows
    become ["a", "", ""] instead of raising an error or shifting columns.
    """
    req = OfficeExcelGenerateRequest(
        workspace_path=str(tmp_path),
        filename="ragged",
        sheets=[
            ExcelSheetSpec(
                name="Data",
                headers=["A", "B", "C"],
                rows=[
                    ["1", "2", "3"],
                    ["4"],  # short by 2 — pad with ""
                    ["7", "8", "9"],
                ],
            ),
        ],
    )
    output_path = generate_xlsx(req)
    result = read_xlsx(output_path)

    sheet = result.sheets[0]
    # Row 1: full
    assert sheet.rows[1] == ["1", "2", "3"]
    # Row 2: padded to 3 cols (pandas adds NaN, we fill with "")
    assert sheet.rows[2] == ["4", "", ""]
    # Row 3: full
    assert sheet.rows[3] == ["7", "8", "9"]


def test_pandas_multi_sheet_roundtrip_preserves_names_and_order(tmp_path: Path) -> None:
    """Multiple sheets round-trip with names + insertion order preserved."""
    req = OfficeExcelGenerateRequest(
        workspace_path=str(tmp_path),
        filename="multi",
        sheets=[
            ExcelSheetSpec(name="Alpha", headers=["x"], rows=[["a1"]]),
            ExcelSheetSpec(name="Beta", headers=["y"], rows=[["b1"], ["b2"]]),
            ExcelSheetSpec(name="Gamma", headers=["z"], rows=[]),
        ],
    )
    output_path = generate_xlsx(req)
    result = read_xlsx(output_path)

    assert [s.name for s in result.sheets] == ["Alpha", "Beta", "Gamma"]
    assert result.summary.metadata.sheet_count == 3

    # Alpha: 1 data row
    assert result.sheets[0].rows == [["x"], ["a1"]]
    # Beta: 2 data rows
    assert result.sheets[1].rows == [["y"], ["b1"], ["b2"]]
    # Gamma: empty sheet — only header, no data rows
    assert result.sheets[2].rows == [["z"]]


def test_pandas_preserves_leading_zero_numeric_strings(tmp_path: Path) -> None:
    """"007" stays "007" — pandas doesn't auto-coerce to int 7.

    This is a regression guard for the previous openpyxl-cell-by-cell loop
    which also preserved strings, but was prone to type coercion if the
    caller passed an int. With pandas, callers pass strings via the API
    and pandas keeps them as strings.
    """
    req = OfficeExcelGenerateRequest(
        workspace_path=str(tmp_path),
        filename="zeros",
        sheets=[
            ExcelSheetSpec(
                name="Codes",
                headers=["Code"],
                rows=[["007"], ["042"], ["100"]],
            ),
        ],
    )
    output_path = generate_xlsx(req)
    result = read_xlsx(output_path)

    sheet = result.sheets[0]
    # All three values stay as strings (read_xlsx always returns str via _cell_value_to_str)
    assert sheet.rows[1][0] == "007"
    assert sheet.rows[2][0] == "042"
    assert sheet.rows[3][0] == "100"


def test_pandas_empty_sheet_roundtrip(tmp_path: Path) -> None:
    """Sheet with no headers/rows still produces a valid readable xlsx."""
    req = OfficeExcelGenerateRequest(
        workspace_path=str(tmp_path),
        filename="empty-only",
        sheets=[ExcelSheetSpec(name="Blank")],
    )
    output_path = generate_xlsx(req)
    assert output_path.exists()

    result = read_xlsx(output_path)
    assert len(result.sheets) == 1
    assert result.sheets[0].name == "Blank"
    # Empty sheet — reader returns empty rows list (no data cells)
    assert result.sheets[0].rows == []


def test_pandas_mixed_type_rows_stay_strings(tmp_path: Path) -> None:
    """Rows with mixed-looking content stay as the strings the caller passed.

    pandas DataFrame() is given all-2D-str input; no type coercion happens.
    Verify that date-like strings, version-like strings, and number-like
    strings all stay strings end-to-end.
    """
    req = OfficeExcelGenerateRequest(
        workspace_path=str(tmp_path),
        filename="mixed",
        sheets=[
            ExcelSheetSpec(
                name="Mix",
                headers=["Date", "Version", "Score"],
                rows=[
                    ["2026-09-09", "v1.2.3", "9.5"],
                    ["2026-12-31", "v2.0.0", "10"],
                ],
            ),
        ],
    )
    output_path = generate_xlsx(req)
    result = read_xlsx(output_path)

    sheet = result.sheets[0]
    # All values are stringified by _cell_value_to_str on read
    assert sheet.rows[1] == ["2026-09-09", "v1.2.3", "9.5"]
    assert sheet.rows[2] == ["2026-12-31", "v2.0.0", "10"]
