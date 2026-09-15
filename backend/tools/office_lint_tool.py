# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Word 格式 Linter 工具（Round 10）—— ``office_lint_word``。

对照 FormatSpec 校验工作区内的 .docx（纯回读，零写入），输出带
rule_id / severity / fix_hint 的违规清单。与 office_read_pdf 同一安全
姿态：``requires_tool_context = True``（无活动 ToolExecutionContext 时
registry 隐藏 schema，execute() 顶部 fail-closed）；file_path 经
``_enforce_workspace`` 工作区围栏把守。

Public surface:

    OfficeLintWordTool(policy=None)   # name="office_lint_word"
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from backend.domain.risk import RiskClass
from backend.tools.base import BaseTool, ToolResult, ToolSchema


class OfficeLintWordTool(BaseTool):
    """对照 FormatSpec 校验 docx（READ，纯回读）。"""

    risk: RiskClass = RiskClass.READ
    requires_tool_context = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_lint_word",
            description=(
                "对照格式规范（FormatSpec）校验工作区内的 .docx，返回违规清单"
                "（rule_id/严重级/实测 vs 期望/中文修复建议）。适合生成文档后"
                "自检、或校验用户提供的旧文档是否符合格式要求。spec 未提供的"
                "项不产生规则；结果 ok=false 表示存在 error 级违规。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "工作区内待校验 .docx 的路径",
                    },
                    "format_spec": {
                        "type": "object",
                        "description": (
                            "格式规范（与 office_create 的 content.format_spec "
                            "同构：page/body/headings/title/header/footer/"
                            "numbering）；只填需要检查的项"
                        ),
                        "properties": {
                            "page": {
                                "type": "object",
                                "properties": {
                                    "size": {"type": "string", "enum": ["A4", "letter"]},
                                    "orientation": {
                                        "type": "string",
                                        "enum": ["portrait", "landscape"],
                                    },
                                    "margins_cm": {
                                        "type": "object",
                                        "properties": {
                                            "top": {"type": "number"},
                                            "bottom": {"type": "number"},
                                            "left": {"type": "number"},
                                            "right": {"type": "number"},
                                        },
                                    },
                                },
                            },
                            "body": {
                                "type": "object",
                                "properties": {
                                    "font_size_pt": {"type": "number"},
                                    "line_spacing": {"type": "number"},
                                    "first_line_indent_cm": {"type": "number"},
                                },
                            },
                            "headings": {
                                "type": "object",
                                "description": "键为 h1/h2/h3，值为字号/加粗/颜色",
                                "properties": {
                                    "h1": {"type": "object"},
                                    "h2": {"type": "object"},
                                    "h3": {"type": "object"},
                                },
                            },
                            "title": {"type": "object"},
                            "header": {
                                "type": "object",
                                "properties": {"text": {"type": "string"}},
                            },
                            "footer": {
                                "type": "object",
                                "properties": {"page_number": {"type": "boolean"}},
                            },
                            "numbering": {"type": "boolean"},
                        },
                        "required": ["format_spec"],
                    },
                },
                "required": ["file_path", "format_spec"],
            },
        )

    def execute(
        self,
        file_path: Optional[str] = None,
        format_spec: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ToolResult:
        if self.requires_tool_context:
            from backend.tools.context import current_tool_context

            if current_tool_context() is None:
                return ToolResult(success=False, error="missing_tool_context")
        return self._lint(file_path, format_spec)

    def _lint(self, file_path: Any, format_spec: Any) -> ToolResult:  # noqa: PLR0911
        """参数校验 + 路径围栏 + 校验执行（拆出以控制 execute 分支数）。"""
        if not isinstance(file_path, str) or not file_path.strip():
            return ToolResult(success=False, error="file_path_required")
        if not isinstance(format_spec, dict) or not format_spec:
            return ToolResult(success=False, error="format_spec_required")

        from pydantic import ValidationError

        from backend.office.errors import OfficeError
        from backend.office.models import WordFormatSpec
        from backend.office.word_lint import lint_docx

        try:
            spec = WordFormatSpec(**format_spec)
        except ValidationError as exc:
            return ToolResult(success=False, error=f"format_spec_invalid: {exc}")

        # 与 office_read_pdf / office_generate_pdf 同一安全姿态：
        # _enforce_workspace（绑定工作区硬拒绝）+ 绝对路径 + 后缀白名单。
        blocked = self._enforce_workspace(file_path)
        if blocked is not None:
            return blocked
        target = Path(file_path).expanduser()
        if not target.is_absolute():
            return ToolResult(
                success=False,
                error="file_path_absolute_required: 请传绝对路径",
            )
        if target.suffix.lower() != ".docx":
            return ToolResult(success=False, error="unsupported_file_type: 仅支持 .docx")
        if not target.is_file():
            return ToolResult(success=False, error="file_not_found")

        try:
            result = lint_docx(target, spec)
        except OfficeError as exc:
            return ToolResult(success=False, error=f"lint_failed: {exc}")
        except Exception as exc:  # noqa: BLE001 — 其余异常折叠为工具错误
            return ToolResult(success=False, error=f"lint_failed: {exc}")
        return ToolResult(success=True, content=result.model_dump())
