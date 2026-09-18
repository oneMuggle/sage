# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Office PPT template tool wrappers for the LLM tool loop.

把 HTTP 端点已验证的 2 个 PPT 模板能力接入 LLM 工具面
（backend/api/office_routes.py 的 /office/ppt/analyze-template 与
/office/ppt/fill-template 段的镜像）：

- ``office_analyze_ppt_template`` → ``ppt_template.analyze_ppt_template``
  （枚举模板母版版式与占位符，layout 名供 office_create 的 slides[].layout 引用）
- ``office_fill_ppt_template``   → ``ppt_template.fill_ppt_template``
  （按 {1 起页号, 占位符 idx, 文本} 填充模板副本，另存新文件，原件不动）

安全姿态与 :mod:`backend.tools.office_template_tool` 一致（读工具
``requires_tool_context = True`` fail-closed；写工具走 ``_enforce_workspace`` +
服务层 ``resolve_within`` 双层边界；doc_id 模式经 binding 解析、失败折叠为
document_not_found；输出按 ``policy.max_output_bytes`` 截断）。共享助手直接
从 office_template_tool 导入（同为 .docx→.pptx 的双模式解析形状）。

与 Word 模板的关键语义差异：pptx 填充**永远另存新文件**（output_filename
必填、与模板同目录、已存在即拒绝），没有原地填充通路。

Public surface:

    OfficeAnalyzePptTemplateTool(policy=None)  # name="office_analyze_ppt_template"
    OfficeFillPptTemplateTool(policy=None)     # name="office_fill_ppt_template"
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from backend.domain.risk import RiskClass
from backend.office.errors import OfficeError
from backend.office.models import OfficeDocType
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.context import ToolExecutionContext, current_tool_context
from backend.tools.file_tool import _record_artifact_safely
from backend.tools.office_template_tool import (
    _bounded,
    _office_error_result,
    _resolve_bound_document,
    _strip_workspace_path,
    _workspace_for_input,
)


def _resolve_ppt_template_input(  # noqa: PLR0911 — 错误早退路径多，保持线性可读
    tool: BaseTool,
    ctx: Optional[ToolExecutionContext],
    doc_id: Optional[str],
    file_path: Optional[str],
) -> Union[Tuple[Path, str, Any], ToolResult]:
    """解析 doc_id / file_path 双模式输入（PPT 类型，.pptx）。"""
    if isinstance(doc_id, str) and doc_id.strip():
        if ctx is None:
            return ToolResult(success=False, error="missing_tool_context")
        found = _resolve_bound_document(ctx, doc_id.strip(), OfficeDocType.PPT)
        if found is None:
            return ToolResult(success=False, error="document_not_found")
        return found
    if isinstance(file_path, str) and file_path.strip():
        blocked = tool._enforce_workspace(file_path)
        if blocked is not None:
            return blocked
        path = Path(file_path).expanduser()
        if not path.is_absolute():
            return ToolResult(
                success=False,
                error="file_path_absolute_required: 请传绝对路径",
            )
        if path.suffix.lower() != ".pptx":
            return ToolResult(
                success=False,
                error="unsupported_file_type: 仅支持 .pptx",
            )
        workspace = _workspace_for_input(ctx, path)
        return path, str(workspace), None
    return ToolResult(success=False, error="doc_id_or_file_path_required")


# ──────────────────────────────────────────────────────────────────────
# 读工具
# ──────────────────────────────────────────────────────────────────────


class OfficeAnalyzePptTemplateTool(BaseTool):
    """Enumerate the layouts & placeholders of a PPT (.pptx) template."""

    requires_tool_context = True
    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_analyze_ppt_template",
            description=(
                "Analyze a PPT template (.pptx): enumerate its master layout "
                "names and each layout's placeholders (idx / type / is_title). "
                "Use the layout names as `slides[].layout` when creating a "
                "deck with office_create, and call this before "
                "office_fill_ppt_template to learn slide placeholder indexes. "
                "Locate by doc_id (from office_list) or absolute file_path."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "description": "PPT document id from office_list.",
                    },
                    "file_path": {
                        "type": "string",
                        "description": (
                            "ABSOLUTE path to a .pptx template inside the "
                            "active chat workspace (when no doc_id)."
                        ),
                    },
                },
                "required": [],
            },
        )

    def execute(
        self,
        doc_id: Optional[str] = None,
        file_path: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        ctx = current_tool_context()
        if ctx is None:
            return ToolResult(success=False, error="missing_tool_context")

        resolved = _resolve_ppt_template_input(self, ctx, doc_id, file_path)
        if isinstance(resolved, ToolResult):
            return resolved
        path, workspace, doc = resolved

        from backend.office.ppt_template import (
            PptTemplateAnalyzeRequest,
            analyze_ppt_template,
        )

        try:
            result = analyze_ppt_template(
                PptTemplateAnalyzeRequest(workspace_path=workspace, file_path=str(path))
            )
        except OfficeError as exc:
            return _office_error_result(exc, "analyze_failed")
        except Exception as exc:  # noqa: BLE001 — 解析器未归类异常按失败处理
            return ToolResult(success=False, error=f"analyze_failed: {exc}")

        if not result.ok:
            return ToolResult(success=False, error=f"analyze_failed: {result.error}")

        data = _strip_workspace_path(result.model_dump(mode="json"))
        if doc is not None:
            data["file_path"] = doc.generated_filename
        return ToolResult(
            success=True, content=_bounded(data, self._policy.max_output_bytes)
        )


# ──────────────────────────────────────────────────────────────────────
# 写工具
# ──────────────────────────────────────────────────────────────────────


class OfficeFillPptTemplateTool(BaseTool):
    """Fill placeholder text in a copy of a PPT template (saves a new .pptx)."""

    requires_tool_context = False
    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_fill_ppt_template",
            description=(
                "Fill a PPT template (.pptx) with text: each fill item is "
                "{slide_number (1-based), placeholder_idx (from "
                "office_analyze_ppt_template), text}. Works on a COPY of the "
                "template and always saves a NEW .pptx next to it "
                "(output_filename, .pptx appended automatically; existing "
                "files are rejected) — the template is never modified. "
                "Locate the template by doc_id or absolute file_path. "
                "Any invalid slide_number/placeholder_idx aborts the whole "
                "operation (all-or-nothing)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "description": "PPT document id from office_list.",
                    },
                    "file_path": {
                        "type": "string",
                        "description": (
                            "ABSOLUTE path to the .pptx template (when no "
                            "doc_id)."
                        ),
                    },
                    "fills": {
                        "type": "array",
                        "description": (
                            "List of {slide_number, placeholder_idx, text} "
                            "items (1-200)."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "slide_number": {"type": "integer"},
                                "placeholder_idx": {"type": "integer"},
                                "text": {"type": "string"},
                            },
                            "required": ["slide_number", "placeholder_idx", "text"],
                        },
                    },
                    "output_filename": {
                        "type": "string",
                        "description": (
                            "Output file name (kept in the template's own "
                            "directory; .pptx auto-appended)."
                        ),
                    },
                },
                "required": ["fills", "output_filename"],
            },
        )

    def execute(  # noqa: PLR0911 — 错误早退路径多，保持线性可读
        self,
        fills: Optional[List[Dict[str, Any]]] = None,
        output_filename: Optional[str] = None,
        doc_id: Optional[str] = None,
        file_path: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        if not isinstance(fills, list) or not fills:
            return ToolResult(
                success=False,
                error="fills_required: 至少一条 {slide_number, placeholder_idx, text}",
            )
        if not isinstance(output_filename, str) or not output_filename.strip():
            return ToolResult(
                success=False,
                error="output_filename_required: 填充永远另存新文件，必须给输出文件名",
            )

        ctx = current_tool_context()
        resolved = _resolve_ppt_template_input(self, ctx, doc_id, file_path)
        if isinstance(resolved, ToolResult):
            return resolved
        path, workspace, doc = resolved

        from pydantic import ValidationError

        from backend.office.ppt_template import (
            PptTemplateFillRequest,
            fill_ppt_template,
        )

        try:
            req = PptTemplateFillRequest(
                workspace_path=workspace,
                file_path=str(path),
                output_filename=output_filename,
                fills=fills,
            )
        except ValidationError as exc:
            return ToolResult(success=False, error=f"fills_invalid: {exc.errors()}")

        result = fill_ppt_template(req)
        if not result.ok:
            return ToolResult(success=False, error=f"fill_failed: {result.error}")

        out = Path(str(result.output_path))
        try:
            size = out.stat().st_size
        except OSError:
            size = 0
        _record_artifact_safely(str(out), size)
        return ToolResult(
            success=True,
            content={
                "path": str(out),
                "filename": result.filename,
                "bytes": size,
                "filled_count": result.filled_count,
            },
        )


__all__ = [
    "OfficeAnalyzePptTemplateTool",
    "OfficeFillPptTemplateTool",
]
