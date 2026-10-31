# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""LaTeX template tools: analyze slots/style and fill a new .tex."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from backend.domain.risk import RiskClass
from backend.tools.base import BaseTool, ToolResult, ToolSchema


def _require_context() -> Optional[ToolResult]:
    from backend.tools.context import current_tool_context

    if current_tool_context() is None:
        return ToolResult(success=False, error="missing_tool_context")
    return None


class OfficeAnalyzeLatexTemplateTool(BaseTool):
    """Analyze a .tex template and return slots/style/macros (READ)."""

    risk: RiskClass = RiskClass.READ
    requires_tool_context = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_analyze_latex_template",
            description=(
                "分析工作区内的 LaTeX .tex 模板（可结合同目录 .cls/.sty），返回"
                "文档类、宏包、宏、版式参数（geometry/linespread 等）以及"
                "可填槽位（title/author/abstract/关键词/占位符/注释）。不编译 TeX。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "工作区内 .tex 模板的绝对路径",
                    }
                },
                "required": ["file_path"],
            },
        )

    def execute(self, file_path: Optional[str] = None, **kwargs: Any) -> ToolResult:  # noqa: PLR0911
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
        if target.suffix.lower() not in (".tex", ".ltx"):
            return ToolResult(success=False, error="unsupported_file_type")
        if not target.is_file():
            return ToolResult(success=False, error="file_not_found")

        from backend.office.errors import OfficeError
        from backend.office.latex.service import analyze_latex_template_file

        root = Path(self._policy.workspace_root or str(target.parent))
        try:
            result = analyze_latex_template_file(target, workspace=root)
        except OfficeError as exc:
            return ToolResult(success=False, error=f"latex_template_failed: {exc}")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=f"latex_template_failed: {exc}")
        return ToolResult(success=True, content=result)


class OfficeFillLatexTemplateTool(BaseTool):
    """Fill a .tex template's slots into a new .tex (WRITE_LOCAL)."""

    risk: RiskClass = RiskClass.WRITE_LOCAL
    requires_tool_context = False

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_fill_latex_template",
            description=(
                "按槽位名称填充工作区内的 LaTeX .tex 模板，输出新的 .tex 文件"
                "（绝不覆盖模板）。data 为槽位名 → 文本/数组；数组用于作者/单位/"
                "关键词。填充后只做源码校验（括号/环境配对），不编译 TeX。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "template_path": {
                        "type": "string",
                        "description": "工作区内 .tex 模板的绝对路径",
                    },
                    "output_filename": {
                        "type": "string",
                        "description": "输出文件名（不能含路径分隔符，不能覆盖已有文件）",
                    },
                    "data": {
                        "type": "object",
                        "description": "槽位名 → 值；数组用于作者/单位/关键词等列表槽位",
                        "additionalProperties": True,
                    },
                },
                "required": ["template_path", "output_filename", "data"],
            },
        )

    def execute(  # noqa: PLR0911
        self,
        template_path: Optional[str] = None,
        output_filename: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ToolResult:
        if not isinstance(template_path, str) or not template_path.strip():
            return ToolResult(success=False, error="template_path_required")
        if not isinstance(output_filename, str) or not output_filename.strip():
            return ToolResult(success=False, error="output_filename_required")
        if not isinstance(data, dict):
            return ToolResult(success=False, error="data_required")
        blocked = self._enforce_workspace(template_path)
        if blocked is not None:
            return blocked
        target = Path(template_path).expanduser()
        if not target.is_absolute():
            return ToolResult(success=False, error="template_path_absolute_required")
        if target.suffix.lower() not in (".tex", ".ltx"):
            return ToolResult(success=False, error="unsupported_file_type")
        if not target.is_file():
            return ToolResult(success=False, error="file_not_found")

        from backend.office.errors import OfficeError
        from backend.office.latex.service import fill_latex_template_file

        root = Path(self._policy.workspace_root or str(target.parent))
        try:
            result = fill_latex_template_file(
                target,
                data,
                output_filename,
                workspace=root,
            )
        except OfficeError as exc:
            return ToolResult(
                success=False, error=f"latex_template_fill_failed: {exc}"
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False, error=f"latex_template_fill_failed: {exc}"
            )
        return ToolResult(success=True, content=result)


__all__ = ["OfficeAnalyzeLatexTemplateTool", "OfficeFillLatexTemplateTool"]
