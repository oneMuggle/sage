"""Unit tests for M4 Excel formula health, read symmetry, and new edit ops."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.office.edit import update_xlsx
from backend.office.errors import OfficeParseError, OfficePathError
from backend.office.excel import read_xlsx
from backend.office.excel_health import (
    ExcelFormulaHealthRequest,
    _is_error_value,
    check_formula_health,
)


def _workbook(path: Path) -> Path:
    from openpyxl import Workbook

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "数据"
    worksheet["A1"] = 1
    worksheet["A2"] = 2
    worksheet["A3"] = "=SUM(A1:A2)"
    workbook.save(str(path))
    return path


def test_formula_health_flags_missing_cache(tmp_path: Path) -> None:
    path = _workbook(tmp_path / "book.xlsx")

    result = check_formula_health(
        ExcelFormulaHealthRequest(workspace_path=str(tmp_path), file_path=str(path))
    )

    assert result.ok is True
    assert result.total_formulas == 1
    assert result.error_count == 0
    assert result.missing_cache_count == 1
    assert result.missing_cache[0].cell == "A3"
    assert any(w["code"] == "missing_formula_cache" for w in result.warnings)


def test_formula_health_no_formulas(tmp_path: Path) -> None:
    from openpyxl import Workbook

    path = tmp_path / "plain.xlsx"
    workbook = Workbook()
    workbook.active["A1"] = "hello"
    workbook.save(str(path))

    result = check_formula_health(
        ExcelFormulaHealthRequest(workspace_path=str(tmp_path), file_path=str(path))
    )

    assert result.ok is True
    assert result.total_formulas == 0
    assert result.warnings == []


def test_error_value_classifier() -> None:
    assert _is_error_value("#REF!")
    assert _is_error_value("#DIV/0!")
    assert not _is_error_value("42")
    assert not _is_error_value(None)


def test_formula_health_rejects_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "outside.xlsx"
    outside.write_bytes(b"not an xlsx")

    with pytest.raises(OfficePathError):
        check_formula_health(
            ExcelFormulaHealthRequest(
                workspace_path=str(workspace), file_path=str(outside)
            )
        )


def test_formula_health_rejects_non_xlsx(tmp_path: Path) -> None:
    source = tmp_path / "notes.csv"
    source.write_text("a,b\n1,2\n", encoding="utf-8")

    with pytest.raises(OfficeParseError):
        check_formula_health(
            ExcelFormulaHealthRequest(workspace_path=str(tmp_path), file_path=str(source))
        )


def test_formula_health_counts_beyond_report_cap(tmp_path: Path) -> None:
    from openpyxl import Workbook

    path = tmp_path / "many.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    for row in range(1, 202):
        worksheet.cell(row=row, column=1, value="=1+1")
    workbook.save(str(path))

    result = check_formula_health(
        ExcelFormulaHealthRequest(workspace_path=str(tmp_path), file_path=str(path))
    )

    assert result.total_formulas == 201
    assert result.missing_cache_count == 201
    assert len(result.missing_cache) == 200
    assert result.issue_truncated is True


def test_read_xlsx_exposes_charts_conditional_formats_and_validations(
    tmp_path: Path,
) -> None:
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, Reference
    from openpyxl.formatting.rule import CellIsRule
    from openpyxl.worksheet.datavalidation import DataValidation

    path = tmp_path / "rich.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "报表"
    worksheet["A1"] = "Q1"
    worksheet["A2"] = 10
    chart = BarChart()
    chart.add_data(Reference(worksheet, min_col=1, min_row=1, max_row=2))
    worksheet.add_chart(chart, "D2")
    worksheet.conditional_formatting.add(
        "A1:A2", CellIsRule(operator="greaterThan", formula=["0"])
    )
    validation = DataValidation(type="list", formula1='"A,B"', allow_blank=True)
    worksheet.add_data_validation(validation)
    validation.add("B1:B2")
    workbook.save(str(path))

    result = read_xlsx(path)
    sheet = result.sheets[0]

    assert sheet.charts
    assert sheet.charts[0]["type"] == "BarChart"
    assert sheet.conditional_formats
    assert sheet.conditional_formats[0]["range"] == "A1:A2"
    assert sheet.data_validations
    assert sheet.data_validations[0]["type"] == "list"
    assert sheet.data_validations[0]["formula1"] == '"A,B"'


def test_insert_and_delete_rows_shift_cells(tmp_path: Path) -> None:
    path = _workbook(tmp_path / "book.xlsx")

    saved, results = update_xlsx(
        path, [{"op": "insert_rows", "sheet": "数据", "index": 2, "amount": 1}]
    )
    assert saved is True
    assert results[0]["ok"] is True

    sheet = read_xlsx(path).sheets[0]
    assert sheet.max_row == 4
    assert [row[0] for row in sheet.rows] == ["1", "2"]

    saved, results = update_xlsx(
        path, [{"op": "delete_rows", "sheet": "数据", "index": 2, "amount": 1}]
    )
    assert saved is True
    sheet = read_xlsx(path).sheets[0]
    assert sheet.max_row == 3
    assert [row[0] for row in sheet.rows] == ["1", "2"]


def test_merge_and_unmerge_cells(tmp_path: Path) -> None:
    path = _workbook(tmp_path / "book.xlsx")

    saved, results = update_xlsx(
        path, [{"op": "merge_cells", "sheet": "数据", "range": "A1:B1"}]
    )
    assert saved is True
    from openpyxl import load_workbook

    workbook = load_workbook(str(path))
    assert "A1:B1" in {str(item) for item in workbook["数据"].merged_cells.ranges}
    workbook.close()

    saved, results = update_xlsx(
        path,
        [{"op": "merge_cells", "sheet": "数据", "range": "A1:B1", "merge": False}],
    )
    assert saved is True
    workbook = load_workbook(str(path))
    assert "A1:B1" not in {str(item) for item in workbook["数据"].merged_cells.ranges}
    workbook.close()


def test_invalid_row_index_leaves_file_untouched(tmp_path: Path) -> None:
    path = _workbook(tmp_path / "book.xlsx")
    before = path.read_bytes()

    saved, results = update_xlsx(
        path, [{"op": "insert_rows", "sheet": "数据", "index": 0}]
    )

    assert saved is False
    assert results[0]["ok"] is False
    assert path.read_bytes() == before
