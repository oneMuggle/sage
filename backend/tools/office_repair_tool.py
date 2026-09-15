# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Word 格式自动修复工具（Round 12）—— ``office_repair_word``。

对照 FormatSpec 自动修复 .docx 的可机械修复违规（样式/页面/编号/题注），
修复后自动复检。与 :mod:`backend.tools.office_lint_tool` 同一安全姿态：

- ``risk = WRITE_LOCAL``（修复会写盘——默认写 ``<stem>-repaired.docx``
  新文件，overwrite=true 时原子替换原文件）；
- ``requires_tool_context = True``（无活动 ToolExecutionContext 时
  registry 隐藏 schema，execute() 顶部 fail-closed）；
- file_path 经 ``_enforce_workspace`` + 绝对路径 + .docx 白名单把守。

Public surface:

    OfficeRepairWordTool(policy=None)   # name="office_repair_word"
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from backend.domain.risk import RiskClass
from backend.tools.base import BaseTool, ToolResult, ToolSchema


class OfficeRepairWordTool(BaseTool):
    """对照 FormatSpec 自动修复 docx（WRITE_LOCAL，修复后自动复检）。"""

    risk: RiskClass = RiskClass.WRITE_LOCAL
    requires_tool_context = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_repair_word",
            description=(
                "对照格式规范（FormatSpec）自动修复 .docx 的可机械修复违规："
                "页边距/纸张/方向、正文字号/行距/缩进、标题样式、页眉文本、"
                "页码域、标题编号与图/表题注的连续编号。修复后自动复检并"
                "返回剩余违规。默认写 <stem>-repaired.docx 新文件"
                "（overwrite=true 才原地替换）；语义类违规（如引用缺失）"
                "不可自动修，保留在复检结果中。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "工作区内待修复 .docx 的路径",
                    },
                    "format_spec": {
                        "type": "object",
                        "description": (
                            "格式规范（与 office_create 的 content.format_spec "
                            "同构）；只填需要修复到位的项"
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
                            "bibliography": {
                                "type": "object",
                                "properties": {"heading_text": {"type": "string"}},
                            },
                        },
                        "required": ["format_spec"],
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": (
                            "true=原地原子替换原文件；false（默认）= 写 "
                            "<stem>-repaired.docx 新文件"
                        ),
                    },
                },
                "required": ["file_path", "format_spec"],
            },
        )

    def execute(
        self,
        file_path: Optional[str] = None,
        format_spec: Optional[Dict[str, Any]] = None,
        overwrite: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        return self._repair(file_path, format_spec, overwrite)

    def _repair(self, file_path: Any, format_spec: Any, overwrite: Any) -> ToolResult:  # noqa: PLR0911
        """参数校验 + 路径围栏 + 修复执行（拆出以控制 execute 分支数）。"""
        if self.requires_tool_context:
            from backend.tools.context import current_tool_context

            if current_tool_context() is None:
                return ToolResult(success=False, error="missing_tool_context")
        if not isinstance(file_path, str) or not file_path.strip():
            return ToolResult(success=False, error="file_path_required")
        if not isinstance(format_spec, dict) or not format_spec:
            return ToolResult(success=False, error="format_spec_required")

        from pydantic import ValidationError

        from backend.office.errors import OfficeError
        from backend.office.models import WordFormatSpec
        from backend.office.word_repair import repair_docx

        try:
            spec = WordFormatSpec(**format_spec)
        except ValidationError as exc:
            return ToolResult(success=False, error=f"format_spec_invalid: {exc}")

        # 与 office_lint_word 同一安全姿态：
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
            result = repair_docx(target, spec, overwrite=bool(overwrite))
        except OfficeError as exc:
            return ToolResult(success=False, error=f"repair_failed: {exc}")
        except Exception as exc:  # noqa: BLE001 — 其余异常折叠为工具错误
            return ToolResult(success=False, error=f"repair_failed: {exc}")
        return ToolResult(success=True, content=result.model_dump())
