"""Excel formula health (M4): detect error values and missing caches.

``openpyxl`` writes formulas without cached results; after a LibreOffice
recalc (``excel_recalc``) values exist, but nothing currently checks them.
This module scans a workbook twice — formulas (``data_only=False``) and
cached values (``data_only=True``) — and reports:

- formula cells whose cached value is an Excel error (``#REF!`` …)
- formula cells with no cached value (needs recalc/open in Excel)

Never raises for scan problems at the tool layer: callers get a result with
warnings instead.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .errors import OfficeFileNotFoundError, OfficeParseError, OfficeSizeLimitError
from .path_safety import resolve_within
from .storage import validate_workspace

logger = logging.getLogger(__name__)

__all__ = [
    "ExcelFormulaHealthRequest",
    "ExcelFormulaHealthResult",
    "ExcelFormulaIssue",
    "check_formula_health",
    "scan_formula_health",
]

#: 单次扫描的公式单元格上限（防止超大工作簿拖垮接口）。
MAX_FORMULA_CELLS = 50_000

#: 公式健康检查的源文件上限（与 Office 编辑/渲染上限同口径）。
MAX_XLSX_BYTES = 50 * 1024 * 1024

#: 返回给调用方的错误条目上限。
MAX_REPORTED_ISSUES = 200

_ERROR_VALUES = {
    "#NULL!",
    "#DIV/0!",
    "#VALUE!",
    "#REF!",
    "#NAME?",
    "#NUM!",
    "#N/A",
    "#GETTING_DATA",
    "#SPILL!",
    "#CALC!",
    "#FIELD!",
    "#BLOCKED!",
    "#CONNECT!",
    "#BUSY!",
    "#UNKNOWN!",
}


class ExcelFormulaIssue(BaseModel):
    """One problematic formula cell."""

    model_config = ConfigDict(extra="forbid")

    sheet: str
    cell: str
    formula: Optional[str] = None
    cached_value: Optional[str] = None
    issue: Literal["formula_error", "missing_cache"]


class ExcelFormulaHealthRequest(BaseModel):
    """POST /office/excel/formula-health request."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str
    max_cells: int = Field(default=MAX_FORMULA_CELLS, ge=1, le=200_000)


class ExcelFormulaHealthResult(BaseModel):
    """Formula health summary."""

    model_config = ConfigDict(extra="forbid")

    ok: bool = Field(description="无公式错误值（缺缓存不等同于错误）")
    source_path: str
    total_formulas: int = 0
    error_count: int = 0
    missing_cache_count: int = 0
    errors: List[ExcelFormulaIssue] = Field(default_factory=list)
    missing_cache: List[ExcelFormulaIssue] = Field(default_factory=list)
    truncated: bool = False
    issue_truncated: bool = Field(
        default=False, description="错误/缺缓存条目超过 200 条，列表已截断（计数仍准确）"
    )
    warnings: List[Dict[str, str]] = Field(default_factory=list)


def _is_error_value(value: Any) -> bool:
    return isinstance(value, str) and value.strip().upper() in _ERROR_VALUES


def _is_formula(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("=")


def scan_formula_health(
    file_path: Path, *, max_cells: int = MAX_FORMULA_CELLS
) -> tuple:
    """Scan a workbook; returns (total, errors, missing, truncated).

    ``errors`` / ``missing`` are lists of ``ExcelFormulaIssue``.
    """
    from openpyxl import load_workbook  # noqa: PLC0415 — heavy import

    formulas = load_workbook(str(file_path), data_only=False)
    try:
        cached = load_workbook(str(file_path), data_only=True)
        try:
            total = 0
            errors: List[ExcelFormulaIssue] = []
            missing: List[ExcelFormulaIssue] = []
            error_count = 0
            missing_count = 0
            truncated = False
            issue_truncated = False
            for sheet in formulas.worksheets:
                cached_sheet = cached[sheet.title]
                for row in sheet.iter_rows():
                    for cell in row:
                        if not _is_formula(cell.value):
                            continue
                        if total >= max_cells:
                            truncated = True
                            break
                        total += 1
                        cached_value = cached_sheet[cell.coordinate].value
                        if cached_value is None:
                            missing_count += 1
                            if len(missing) < MAX_REPORTED_ISSUES:
                                missing.append(
                                    ExcelFormulaIssue(
                                        sheet=sheet.title,
                                        cell=cell.coordinate,
                                        formula=str(cell.value),
                                        issue="missing_cache",
                                    )
                                )
                            else:
                                issue_truncated = True
                        elif _is_error_value(cached_value):
                            error_count += 1
                            if len(errors) < MAX_REPORTED_ISSUES:
                                errors.append(
                                    ExcelFormulaIssue(
                                        sheet=sheet.title,
                                        cell=cell.coordinate,
                                        formula=str(cell.value),
                                        cached_value=str(cached_value),
                                        issue="formula_error",
                                    )
                                )
                            else:
                                issue_truncated = True
                    if truncated:
                        break
                if truncated:
                    break
            return (
                total,
                errors,
                missing,
                error_count,
                missing_count,
                truncated,
                issue_truncated,
            )
        finally:
            cached.close()
    finally:
        formulas.close()


def check_formula_health(request: ExcelFormulaHealthRequest) -> ExcelFormulaHealthResult:
    """Validate the workspace path, scan the workbook, and classify results."""
    workspace = validate_workspace(Path(request.workspace_path))
    source = resolve_within(workspace, Path(request.file_path))
    if not source.is_file():
        raise OfficeFileNotFoundError(source)
    if source.suffix.lower() != ".xlsx":
        raise OfficeParseError("公式健康检查仅支持 .xlsx")
    if source.stat().st_size > MAX_XLSX_BYTES:
        raise OfficeSizeLimitError(
            source.stat().st_size, MAX_XLSX_BYTES, file_path=source
        )

    try:
        (
            total,
            errors,
            missing,
            error_count,
            missing_count,
            truncated,
            issue_truncated,
        ) = scan_formula_health(source, max_cells=request.max_cells)
    except Exception as exc:  # noqa: BLE001 — 扫描失败折算为结果警告
        logger.warning("formula health scan failed: %s", type(exc).__name__)
        return ExcelFormulaHealthResult(
            ok=False,
            source_path=_rel(source, workspace),
            warnings=[
                {
                    "code": "formula_scan_failed",
                    "message": f"公式扫描失败（{type(exc).__name__}）",
                }
            ],
        )

    warnings: List[Dict[str, str]] = []
    if truncated:
        warnings.append(
            {
                "code": "formula_cells_truncated",
                "message": f"公式单元格超过上限 {request.max_cells}，结果已截断",
            }
        )
    if issue_truncated:
        warnings.append(
            {
                "code": "formula_issues_truncated",
                "message": "错误/缺缓存条目超过 200 条，列表已截断（计数仍准确）",
            }
        )
    if missing_count:
        warnings.append(
            {
                "code": "missing_formula_cache",
                "message": f"{missing_count} 个公式缺少缓存值，建议执行公式重算",
            }
        )
    return ExcelFormulaHealthResult(
        ok=not errors,
        source_path=_rel(source, workspace),
        total_formulas=total,
        error_count=error_count,
        missing_cache_count=missing_count,
        errors=errors,
        missing_cache=missing,
        truncated=truncated,
        issue_truncated=issue_truncated,
        warnings=warnings,
    )


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.name
