# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""LaTeX PDF audit tool — ``office_audit_latex_pdf``."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from backend.domain.risk import RiskClass
from backend.tools.base import BaseTool, ToolResult, ToolSchema


def _require_context() -> Optional[ToolResult]:
    from backend.tools.context import current_tool_context

    if current_tool_context() is None:
        return ToolResult(success=False, error="missing_tool_context")
    return None


def _optional_positive_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


class OfficeAuditLatexPdfTool(BaseTool):
    """Audit PDF page size/count, embedded fonts and image DPI (READ)."""

    risk: RiskClass = RiskClass.READ
    requires_tool_context = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_audit_latex_pdf",
            description=(
                "只读审计工作区 PDF：页数/页面尺寸（A4/Letter/Legal）、"
                "字体是否嵌入、图片有效 DPI。返回带页码锚点的问题列表；"
                "不修改 PDF、不执行 TeX。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "工作区内 .pdf 的绝对路径",
                    },
                    "required_min_pages": {
                        "type": "integer",
                        "description": "可选：要求的最小页数",
                    },
                    "required_max_pages": {
                        "type": "integer",
                        "description": "可选：要求的最大页数",
                    },
                    "min_image_dpi": {
                        "type": "number",
                        "description": "图片有效 DPI 阈值（默认 150）",
                    },
                },
                "required": ["file_path"],
            },
        )

    def execute(  # noqa: PLR0911
        self,
        file_path: Optional[str] = None,
        required_min_pages: Any = None,
        required_max_pages: Any = None,
        min_image_dpi: Any = 150.0,
        **kwargs: Any,
    ) -> ToolResult:
        blocked = _require_context()
        if blocked is not None:
            return blocked
        if not isinstance(file_path, str) or not file_path.strip():
            return ToolResult(success=False, error="file_path_required")
        blocked = self._enforce_workspace(file_path)
        if blocked is not None:
            return blocked
        target = Path(file_path).expanduser()
        if not target.is_absolute():
            return ToolResult(success=False, error="file_path_absolute_required")
        if target.suffix.lower() != ".pdf":
            return ToolResult(success=False, error="unsupported_file_type")
        if not target.is_file():
            return ToolResult(success=False, error="file_not_found")

        try:
            dpi = float(min_image_dpi)
        except (TypeError, ValueError):
            dpi = 150.0
        dpi = max(1.0, min(dpi, 2400.0))

        from backend.office.errors import OfficeError
        from backend.office.latex.service import audit_latex_pdf_service

        root = Path(self._policy.workspace_root or str(target.parent))
        try:
            result = audit_latex_pdf_service(
                target,
                workspace=root,
                required_min_pages=_optional_positive_int(required_min_pages),
                required_max_pages=_optional_positive_int(required_max_pages),
                min_image_dpi=dpi,
            )
        except OfficeError as exc:
            return ToolResult(success=False, error=f"latex_pdf_audit_failed: {exc}")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=f"latex_pdf_audit_failed: {exc}")
        return ToolResult(success=True, content=result)


__all__ = ["OfficeAuditLatexPdfTool"]
