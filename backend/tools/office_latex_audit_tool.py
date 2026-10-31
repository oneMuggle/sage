# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""LaTeX source audit tool — ``office_audit_latex``."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional

from backend.domain.risk import RiskClass
from backend.tools.base import BaseTool, ToolResult, ToolSchema


class OfficeAuditLatexTool(BaseTool):
    """Run deterministic source-level checks on a .tex project (READ)."""

    risk: RiskClass = RiskClass.READ
    requires_tool_context = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_audit_latex",
            description=(
                "对工作区内的 LaTeX .tex 项目做源码级确定性审校：documentclass/"
                "title/author/abstract、必需章节、未定义 cite/ref、图表 caption/label、"
                "重复 label、TODO/占位符、危险命令/越界 include。返回带 file/line "
                "锚点与 fix_hint 的问题清单；不编译 TeX。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "工作区内 .tex 主文件的绝对路径",
                    },
                    "required_sections": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选：必须存在的章节标题（子串匹配，大小写不敏感）",
                    },
                },
                "required": ["file_path"],
            },
        )

    def execute(  # noqa: PLR0911
        self,
        file_path: Optional[str] = None,
        required_sections: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> ToolResult:
        if self.requires_tool_context:
            from backend.tools.context import current_tool_context

            if current_tool_context() is None:
                return ToolResult(success=False, error="missing_tool_context")
        if not isinstance(file_path, str) or not file_path.strip():
            return ToolResult(success=False, error="file_path_required")
        if required_sections is not None and not isinstance(required_sections, list):
            return ToolResult(success=False, error="required_sections_invalid")
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
        from backend.office.latex.service import audit_latex_file_service

        root = Path(self._policy.workspace_root or str(target.parent))
        try:
            result = audit_latex_file_service(
                target,
                workspace=root,
                required_sections=[str(item) for item in (required_sections or [])],
            )
        except OfficeError as exc:
            return ToolResult(success=False, error=f"latex_audit_failed: {exc}")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=f"latex_audit_failed: {exc}")
        return ToolResult(success=True, content=result)


__all__ = ["OfficeAuditLatexTool"]
