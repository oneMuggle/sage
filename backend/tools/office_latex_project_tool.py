# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""LaTeX project zip import tool — ``office_extract_latex_project``."""

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


class OfficeExtractLatexProjectTool(BaseTool):
    """Safely extract a LaTeX/Overleaf project zip into the workspace (WRITE_LOCAL)."""

    risk: RiskClass = RiskClass.WRITE_LOCAL
    requires_tool_context = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_extract_latex_project",
            description=(
                "安全解压工作区内的 LaTeX/Overleaf 项目 zip 到新目录，识别主 .tex "
                "（含 \\documentclass）。拒绝路径穿越/符号链接/加密 zip/zip bomb；"
                "只解压文档与资源白名单后缀。不执行/不编译解压内容。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "zip_path": {
                        "type": "string",
                        "description": "工作区内 .zip 项目包的绝对路径",
                    },
                    "output_dir_name": {
                        "type": "string",
                        "description": "可选输出目录名（默认 latex-<zip stem>；不能覆盖已有目录）",
                    },
                },
                "required": ["zip_path"],
            },
        )

    def execute(  # noqa: PLR0911
        self,
        zip_path: Optional[str] = None,
        output_dir_name: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        blocked = _require_context()
        if blocked is not None:
            return blocked
        if not isinstance(zip_path, str) or not zip_path.strip():
            return ToolResult(success=False, error="zip_path_required")
        blocked = self._enforce_workspace(zip_path)
        if blocked is not None:
            return blocked
        target = Path(zip_path).expanduser()
        if not target.is_absolute():
            return ToolResult(success=False, error="zip_path_absolute_required")
        if target.suffix.lower() != ".zip":
            return ToolResult(success=False, error="unsupported_file_type")
        if not target.is_file():
            return ToolResult(success=False, error="file_not_found")

        from backend.office.errors import OfficeError
        from backend.office.latex.service import extract_latex_project_service

        root = Path(self._policy.workspace_root or str(target.parent))
        try:
            result = extract_latex_project_service(
                target,
                workspace=root,
                output_dir_name=output_dir_name,
            )
        except OfficeError as exc:
            return ToolResult(
                success=False,
                error=f"latex_project_extract_failed: {exc}",
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False,
                error=f"latex_project_extract_failed: {exc}",
            )
        return ToolResult(success=True, content=result)


__all__ = ["OfficeExtractLatexProjectTool"]
