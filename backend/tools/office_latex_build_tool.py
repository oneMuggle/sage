# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""LaTeX build tools: optional PDF compile and latexdiff."""

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


def _clamp_timeout(value: Any, default: int = 60) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(number, 600))


class OfficeCompileLatexTool(BaseTool):
    """Compile a .tex project with a detected external engine (WRITE_LOCAL)."""

    risk: RiskClass = RiskClass.WRITE_LOCAL
    requires_tool_context = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_compile_latex",
            description=(
                "使用本机已安装的 TeX 引擎（latexmk/xelatex/lualatex/pdflatex）"
                "编译工作区 .tex 项目为 PDF。编译前强制运行源码审校，发现危险命令/"
                "include 越界等 error 会拒绝编译。不捆绑 TeX；无引擎时返回 no_engine。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "工作区内 .tex 主文件的绝对路径",
                    },
                    "output_filename": {
                        "type": "string",
                        "description": "输出 PDF 文件名（默认 <stem>.pdf，不能覆盖已有文件）",
                    },
                    "engine": {
                        "type": "string",
                        "description": "可选：latexmk/xelatex/lualatex/pdflatex；缺省自动探测",
                    },
                    "timeout_s": {
                        "type": "integer",
                        "description": "编译超时秒数（1–600，默认 60）",
                    },
                },
                "required": ["file_path"],
            },
        )

    def execute(  # noqa: PLR0911
        self,
        file_path: Optional[str] = None,
        output_filename: Optional[str] = None,
        engine: Optional[str] = None,
        timeout_s: Any = None,
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
        if target.suffix.lower() not in (".tex", ".ltx"):
            return ToolResult(success=False, error="unsupported_file_type")
        if not target.is_file():
            return ToolResult(success=False, error="file_not_found")

        from backend.office.errors import OfficeError
        from backend.office.latex.service import compile_latex_file

        root = Path(self._policy.workspace_root or str(target.parent))
        try:
            result = compile_latex_file(
                target,
                workspace=root,
                output_filename=output_filename,
                engine=engine,
                timeout_s=_clamp_timeout(timeout_s),
            )
        except OfficeError as exc:
            return ToolResult(success=False, error=f"latex_compile_failed: {exc}")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=f"latex_compile_failed: {exc}")
        return ToolResult(success=True, content=result)


class OfficeLatexdiffTool(BaseTool):
    """Generate a latexdiff .tex (optionally compile it) (WRITE_LOCAL)."""

    risk: RiskClass = RiskClass.WRITE_LOCAL
    requires_tool_context = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_latexdiff",
            description=(
                "使用本机 latexdiff 对比两份 .tex，输出 diff.tex（可选编译红字版 PDF）。"
                "适合论文修改说明/审稿回复；不安装/不下载 latexdiff，缺失时返回 no_latexdiff。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "original_path": {
                        "type": "string",
                        "description": "原始 .tex 的绝对路径",
                    },
                    "revised_path": {
                        "type": "string",
                        "description": "修订后 .tex 的绝对路径",
                    },
                    "output_filename": {
                        "type": "string",
                        "description": "输出 diff.tex 文件名（默认 <stem>-diff.tex）",
                    },
                    "compile_pdf": {
                        "type": "boolean",
                        "description": "是否编译 diff.pdf（需要 TeX 引擎）",
                    },
                    "engine": {
                        "type": "string",
                        "description": "可选 TeX 引擎；仅 compile_pdf=true 时使用",
                    },
                },
                "required": ["original_path", "revised_path"],
            },
        )

    def execute(  # noqa: PLR0911
        self,
        original_path: Optional[str] = None,
        revised_path: Optional[str] = None,
        output_filename: str = "",
        compile_pdf: bool = False,
        engine: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        blocked = _require_context()
        if blocked is not None:
            return blocked
        if not isinstance(original_path, str) or not original_path.strip():
            return ToolResult(success=False, error="original_path_required")
        if not isinstance(revised_path, str) or not revised_path.strip():
            return ToolResult(success=False, error="revised_path_required")
        for value, label in (
            (original_path, "original_path"),
            (revised_path, "revised_path"),
        ):
            blocked = self._enforce_workspace(value)
            if blocked is not None:
                return blocked
            target = Path(value).expanduser()
            if not target.is_absolute():
                return ToolResult(success=False, error=f"{label}_absolute_required")
            if target.suffix.lower() not in (".tex", ".ltx"):
                return ToolResult(success=False, error="unsupported_file_type")
            if not target.is_file():
                return ToolResult(success=False, error="file_not_found")

        from backend.office.errors import OfficeError
        from backend.office.latex.service import latexdiff_files_service

        root = Path(
            self._policy.workspace_root or str(Path(original_path).expanduser().parent)
        )
        try:
            result = latexdiff_files_service(
                Path(original_path).expanduser(),
                Path(revised_path).expanduser(),
                workspace=root,
                output_filename=output_filename,
                compile_pdf=bool(compile_pdf),
                engine=engine,
            )
        except OfficeError as exc:
            return ToolResult(success=False, error=f"latexdiff_failed: {exc}")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=f"latexdiff_failed: {exc}")
        return ToolResult(success=True, content=result)


__all__ = ["OfficeCompileLatexTool", "OfficeLatexdiffTool"]
