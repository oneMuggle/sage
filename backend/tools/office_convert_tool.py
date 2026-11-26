# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Word 格式转换 Agent 工具（P0）：office_convert_word。

把 `.doc` 转为 `.docx`（或反向）。转换器走本机 LibreOffice / Word COM，
服务层契约“永不抛异常”，失败以 ToolResult(success=False, error=...) 返回。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from backend.domain.risk import RiskClass
from backend.office.word_convert import convert_word
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.context import current_tool_context
from backend.tools.file_tool import _record_artifact_safely
from backend.tools.office_template_tool import _workspace_for_input


class OfficeConvertWordTool(BaseTool):
    """Convert Word binary formats (.doc ↔ .docx) with a local converter."""

    requires_tool_context = False
    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_convert_word",
            description=(
                "Convert a Word file between binary .doc and .docx formats "
                "using a locally installed converter (LibreOffice headless, "
                "or MS Word COM on Windows). The output is written next to "
                "the source as <stem>.docx / <stem>.doc. Useful for legacy "
                "templates that office_analyze_word_template cannot open."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "ABSOLUTE path to a .doc or .docx file.",
                    },
                    "target_format": {
                        "type": "string",
                        "enum": ["docx", "doc"],
                        "description": "Desired output format (default docx).",
                    },
                    "output_filename": {
                        "type": "string",
                        "description": (
                            "Optional output file name (no path separators); "
                            "must end with the target extension."
                        ),
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "Allow replacing an existing output file.",
                    },
                },
                "required": ["file_path"],
            },
        )

    def execute(  # noqa: PLR0911 — 错误早退路径多，保持线性可读
        self,
        file_path: Optional[str] = None,
        target_format: str = "docx",
        output_filename: Optional[str] = None,
        overwrite: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        if not isinstance(file_path, str) or not file_path.strip():
            return ToolResult(success=False, error="file_path_required")
        path = Path(file_path).expanduser()
        if not path.is_absolute():
            return ToolResult(
                success=False, error="file_path_absolute_required: 请传绝对路径"
            )
        if path.suffix.lower() not in (".doc", ".docx"):
            return ToolResult(
                success=False, error="unsupported_file_type: 仅支持 .doc / .docx"
            )
        if target_format not in ("docx", "doc"):
            return ToolResult(
                success=False, error=f"target_format_invalid: {target_format!r}"
            )
        if not path.is_file():
            return ToolResult(success=False, error="file_not_found")

        # 写沙箱：受限子代理下源目录即写入边界（产物落在源文件同目录），
        # 与 _BOUNDARY_SPECS 的 file_path 登记一致。
        blocked = self._enforce_workspace(str(path))
        if blocked is not None:
            return blocked

        ctx = current_tool_context()
        workspace = _workspace_for_input(ctx, path)
        result = convert_word(
            path,
            workspace,
            target_format=target_format,
            output_filename=output_filename,
            overwrite=bool(overwrite),
        )
        if not result.ok or not result.output_path:
            return ToolResult(success=False, error=result.error or "convert_failed")

        final = Path(result.output_path)
        _record_artifact_safely(str(final), final.stat().st_size)
        return ToolResult(
            success=True,
            content={
                "path": str(final),
                "filename": final.name,
                "bytes": final.stat().st_size,
                "method": result.method,
                "target_format": result.target_format,
            },
        )


__all__ = ["OfficeConvertWordTool"]
