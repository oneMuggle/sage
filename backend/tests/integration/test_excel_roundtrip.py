"""Excel round-trip integration tests.

Sprint 1 PR-4 (sage-excel-capability-assessment-2026-09-09 P1-1).

Covers the end-to-end Excel pipeline that the agent LLM can drive:
    generate_xlsx → read_xlsx → update_xlsx → read_xlsx

Why this matters
----------------
The existing unit tests split Excel into two halves:
    - test_excel.py — reader only (read_xlsx)
    - test_edit.py  — editor only (update_xlsx)
    - test_generators.py — generator only (generate_xlsx)

A bug that survives one half but breaks the round-trip (e.g. write loses
cached formula values, multi-sheet name collisions, sheet-name truncation
mismatched between read and write) would silently regress. These tests
exercise the whole path and lock down the behaviour the LLM actually
sees.

Conventions
-----------
- Generate into a real temp workspace (matches ``backend.office.tool_service``
  managed-document layout).
- Read after each write to verify state on disk, not just return value.
- Document each known caveat (``data_only`` drops formulas; openpyxl
  drops cached formula values on save) with a test that *fixes* it
  rather than skipping it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from backend.office.edit import update_xlsx
from backend.office.excel import generate_xlsx, read_xlsx
from backend.office.models import ExcelSheetSpec, OfficeExcelGenerateRequest

# ─────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """Per-test scratch workspace matching ``managed_document_path`` layout."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


def _read_rows(path: Path, sheet: str) -> list[list[str]]:
    """Read a single sheet's rows via the public reader (string grid)."""
    result = read_xlsx(
        path,
        workspace_path=str(path.parent),
        generated_filename=path.name,
        original_filename=None,
    )
    for s in result.sheets:
        if s.name == sheet:
            return s.rows
    raise AssertionError(f"sheet {sheet!r} not found in {path}")


# ─────────────────────────────────────────────────────────────────────────
# generate → read
# ─────────────────────────────────────────────────────────────────────────


def test_generate_then_read_preserves_rows(workspace: Path) -> None:
    """Generated workbook reads back identically."""
    req = OfficeExcelGenerateRequest(
        workspace_path=str(workspace),
        filename="roundtrip-basic",
        sheets=[
            ExcelSheetSpec(
                name="Sales",
                headers=["Quarter", "Revenue"],
                rows=[["Q1", "100"], ["Q2", "150"], ["Q3", "200"]],
            ),
        ],
    )
    path = generate_xlsx(req)

    rows = _read_rows(path, "Sales")
    assert rows[0] == ["Quarter", "Revenue"]
    assert rows[1:] == [["Q1", "100"], ["Q2", "150"], ["Q3", "200"]]


def test_generate_then_read_multi_sheet_preserves_order_and_names(
    workspace: Path,
) -> None:
    """Multi-sheet workbook reads with same order and the 31-char name cap.

    Note: ``ExcelSheetSpec.name`` is validated by Pydantic against the 31-char
    Excel sheet-name cap *at request time*, so callers must pre-truncate
    (Sprint 3 P2-1 may surface this in the LLM-facing tool schema). This test
    asserts that an already-31-char name round-trips losslessly.
    """
    long_name = "This_Is_A_Very_Long_Sheet_Name_That_Exceeds_Limits_For_Real"
    truncated = long_name[:31]
    req = OfficeExcelGenerateRequest(
        workspace_path=str(workspace),
        filename="roundtrip-multi",
        sheets=[
            ExcelSheetSpec(name="First", headers=["a"], rows=[["1"]]),
            ExcelSheetSpec(name=truncated, headers=["b"], rows=[["2"]]),
        ],
    )
    path = generate_xlsx(req)

    result = read_xlsx(
        path,
        workspace_path=str(path.parent),
        generated_filename=path.name,
        original_filename=None,
    )
    names = [s.name for s in result.sheets]
    assert names[0] == "First"
    assert names[1] == truncated
    # 31-char cap holds end-to-end
    assert len(names[1]) == 31


# ─────────────────────────────────────────────────────────────────────────
# generate → read → edit → read
# ─────────────────────────────────────────────────────────────────────────


def test_roundtrip_set_cells_then_read(workspace: Path) -> None:
    """set_cells edits survive a read-back."""
    req = OfficeExcelGenerateRequest(
        workspace_path=str(workspace),
        filename="roundtrip-edit-set",
        sheets=[
            ExcelSheetSpec(
                name="Data",
                headers=["Name", "Score"],
                rows=[["Alice", "90"], ["Bob", "85"]],
            ),
        ],
    )
    path = generate_xlsx(req)

    saved, results = update_xlsx(
        path,
        [
            {
                "op": "set_cells",
                "sheet": "Data",
                "cells": [
                    {"addr": "A3", "value": "Carol"},
                    {"addr": "B3", "value": "95"},
                ],
            }
        ],
    )
    assert saved
    assert all(r["ok"] for r in results)

    rows = _read_rows(path, "Data")
    assert rows[2] == ["Carol", "95"]
    # Original rows still there
    assert rows[0] == ["Name", "Score"]
    assert rows[1] == ["Alice", "90"]


def test_roundtrip_append_rows_then_read(workspace: Path) -> None:
    """append_rows appends at next empty row, doesn't clobber existing."""
    req = OfficeExcelGenerateRequest(
        workspace_path=str(workspace),
        filename="roundtrip-edit-append",
        sheets=[
            ExcelSheetSpec(
                name="Data",
                headers=["A", "B"],
                rows=[["x", "1"], ["y", "2"]],
            ),
        ],
    )
    path = generate_xlsx(req)

    saved, results = update_xlsx(
        path,
        [{"op": "append_rows", "sheet": "Data", "rows": [["z", "3"], ["w", "4"]]}],
    )
    assert saved
    assert results[0]["ok"]

    rows = _read_rows(path, "Data")
    assert rows == [["A", "B"], ["x", "1"], ["y", "2"], ["z", "3"], ["w", "4"]]


def test_roundtrip_add_rename_delete_sheet(workspace: Path) -> None:
    """add_sheet + rename_sheet + delete_sheet survive a read-back."""
    req = OfficeExcelGenerateRequest(
        workspace_path=str(workspace),
        filename="roundtrip-edit-sheets",
        sheets=[
            ExcelSheetSpec(name="Data", headers=["A"], rows=[["1"]]),
            ExcelSheetSpec(name="Backup", headers=["B"], rows=[["2"]]),
        ],
    )
    path = generate_xlsx(req)

    saved, results = update_xlsx(
        path,
        [
            {"op": "add_sheet", "name": "Summary", "headers": ["Total"], "rows": [["99"]]},
            {"op": "rename_sheet", "from": "Backup", "to": "OldBackup"},
            {"op": "delete_sheet", "name": "OldBackup"},
        ],
    )
    assert saved
    assert all(r["ok"] for r in results)

    result = read_xlsx(
        path,
        workspace_path=str(path.parent),
        generated_filename=path.name,
        original_filename=None,
    )
    names = sorted(s.name for s in result.sheets)
    assert names == ["Data", "Summary"]
    summary_rows = next(s.rows for s in result.sheets if s.name == "Summary")
    assert summary_rows == [["Total"], ["99"]]


# ─────────────────────────────────────────────────────────────────────────
# Known caveat lock-downs
# ─────────────────────────────────────────────────────────────────────────


def test_roundtrip_formula_survives_edit_but_cached_value_drops(
    workspace: Path,
) -> None:
    """Lock down the documented caveat.

    openpyxl's ``load_workbook(data_only=False)`` (used by ``update_xlsx``)
    preserves formulas. But after save, cached values written by Excel
    are dropped, so a subsequent ``load_workbook(data_only=True)`` (used
    by ``read_xlsx``) returns ``None`` for the formula cell.

    We assert the *formula* survives (low-level openpyxl check) and the
    reader emits ``None`` as empty string (string-grid contract).
    """
    # Build a workbook with a formula by hand (generator doesn't expose
    # formula API yet — see Sprint 3 P2-1).
    path = workspace / "roundtrip-formula.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Calc"
    ws["A1"] = 1
    ws["A2"] = 2
    ws["A3"] = "=SUM(A1:A2)"
    wb.save(path)

    # Edit a non-formula cell
    saved, results = update_xlsx(
        path,
        [{"op": "set_cells", "sheet": "Calc", "cells": [{"addr": "A4", "value": "100"}]}],
    )
    assert saved

    # Formula must still be present
    wb2 = load_workbook(str(path), data_only=False)
    ws2 = wb2["Calc"]
    assert ws2["A3"].value == "=SUM(A1:A2)"
    # update_xlsx.set_cells coerces "100" → int 100 (matches Excel entry
    # semantics; see backend/tests/unit/office/test_edit.py
    # test_xlsx_set_cells_coerces_numbers).
    assert ws2["A4"].value == 100

    # Reader (data_only=True) drops the formula row because openpyxl
    # strips cached values on save. We assert the row that *contains*
    # the formula is no longer present (A3 cached value was None → row
    # dropped), while the integer set via update_xlsx survives.
    rows = _read_rows(path, "Calc")
    # A1, A2 are integers from the hand-built workbook; A4 was set to
    # int 100 via update_xlsx's numeric coercion.
    assert rows == [["1"], ["2"], ["100"]]


def test_roundtrip_preserves_empty_sheet(workspace: Path) -> None:
    """A sheet created with no rows still reads as empty (not a missing sheet)."""
    req = OfficeExcelGenerateRequest(
        workspace_path=str(workspace),
        filename="roundtrip-empty",
        sheets=[ExcelSheetSpec(name="Empty", headers=[], rows=[])],
    )
    path = generate_xlsx(req)

    saved, results = update_xlsx(
        path,
        [{"op": "append_rows", "sheet": "Empty", "rows": [["first", "row"]]}],
    )
    assert saved

    rows = _read_rows(path, "Empty")
    assert rows == [["first", "row"]]
