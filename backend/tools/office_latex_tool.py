# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""LaTeX reader tool — ``office_read_latex``.

Parses a workspace ``.tex`` file/project into structured preview blocks
(headings / paragraphs / equations / figures / tables / citations) and
warnings. This is read-only and never executes TeX.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from backend.domain.risk import RiskClass
from backend.tools.base import BaseTool, ToolResult, ToolSchema


class OfficeReadLatexTool(BaseTool):
    """Read a .tex file and return a semantic preview (READ)."""

    risk: RiskClass = RiskClass.READ
    requires_tool_context = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_read_latex",
            description=(
                "读取工作区内的 LaTeX .tex 文件/项目，返回结构化预览：元数据、"
                "章节、段落、公式、图、表、引用、参考文献与解析警告。不会编译 "
                "TeX，也不会执行宏；未知命令会降级为文本并附带 warning。适合"
                "查看期刊 LaTeX 模板或 .tex 论文。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "工作区内 .tex 文件的绝对路径",
                    }
                },
                "required": ["file_path"],
            },
        )

    def execute(self, file_path: Optional[str] = None, **kwargs: Any) -> ToolResult:
        if self.requires_tool_context:
            from backend.tools.context import current_tool_context

            if current_tool_context() is None:
                return ToolResult(success=False, error="missing_tool_context")
        return self._read(file_path)

    def _read(self, file_path: Any) -> ToolResult:  # noqa: PLR0911
        if not isinstance(file_path, str) or not file_path.strip():
            return ToolResult(success=False, error="file_path_required")
        blocked = self._enforce_workspace(file_path)
        if blocked is not None:
            return blocked
        target = Path(file_path).expanduser()
        if not target.is_absolute():
            return ToolResult(
                success=False,
                error="file_path_absolute_required: 请传绝对路径",
            )
        if target.suffix.lower() not in (".tex", ".ltx"):
            return ToolResult(
                success=False, error="unsupported_file_type: 仅支持 .tex/.ltx"
            )
        if not target.is_file():
            return ToolResult(success=False, error="file_not_found")

        from backend.office.errors import OfficeError
        from backend.office.latex.service import read_latex_file

        root = self._policy.workspace_root or str(target.parent)
        try:
            result = read_latex_file(target, workspace=Path(root))
        except OfficeError as exc:
            return ToolResult(success=False, error=f"latex_read_failed: {exc}")
        except Exception as exc:  # noqa: BLE001 — 其余异常折叠为工具错误
            return ToolResult(success=False, error=f"latex_read_failed: {exc}")
        return ToolResult(success=True, content=result)


__all__ = ["OfficeReadLatexTool"]
