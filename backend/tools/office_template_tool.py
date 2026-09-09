# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Office Word template tool wrappers for the LLM tool loop (Parity Batch-1).

把 HTTP 端点已验证的 2 个 Word 模板能力接入 LLM 工具面
（backend/api/office_routes.py Phase-2 段的镜像）：

- ``office_analyze_word_template`` ← POST /office/word/analyze-template
  → ``word_template.analyze_word_template``（列出 {{占位符}}）
- ``office_fill_word_template``   ← POST /office/word/fill-template
  → ``word_template.fill_word_template``（按 data 填充，支持图片占位符）

安全姿态与 :mod:`backend.tools.office_pdf_tool` 一致（读工具
``requires_tool_context = True`` fail-closed；写工具走
``_enforce_workspace`` + 服务层 ``resolve_within`` 双层边界；doc_id 模式
经 binding 解析、失败折叠为 document_not_found；输出剥除
summary.workspace_path；读输出按 ``policy.max_output_bytes`` 截断）。

填充落点：服务层永远写「新文件且不存在」，这里统一先落工作区内临时名，
成功后 ``os.replace`` 到最终目标 —— 默认原地覆盖模板（或显式
``output_path`` 另存），同一工作区卷内原子改名。docxtpl 属可选重依赖，
延迟到 execute() 内 import（同 tool_service 的 reader 模式）。

Public surface:

    OfficeAnalyzeWordTemplateTool(policy=None)  # name="office_analyze_word_template"
    OfficeFillWordTemplateTool(policy=None)     # name="office_fill_word_template"
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

from backend.data.database import get_database
from backend.domain.risk import RiskClass
from backend.office.errors import (
    OfficeError,
    OfficeFileNotFoundError,
    OfficePathError,
    OfficeSizeLimitError,
)
from backend.office.models import OfficeDocType
from backend.office.session_workspace import (
    get_active_workspace,
    get_document_in_workspace,
)
from backend.office.storage import document_path
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.context import ToolExecutionContext, current_tool_context
from backend.tools.file_tool import _record_artifact_safely

# ──────────────────────────────────────────────────────────────────────
# 共享小助手（office_pdf_tool.py 内有镜像副本，保持模块自包含）
# ──────────────────────────────────────────────────────────────────────


def _resolve_bound_document(
    ctx: ToolExecutionContext,
    doc_id: str,
    expected_doc_type: OfficeDocType,
) -> Optional[Tuple[Path, str, Any]]:
    """binding 内解析 doc_id → (on-disk path, workspace_path, summary)。"""
    try:
        conn = get_database().get_connection()
    except Exception:
        return None
    binding = get_active_workspace(
        conn, ctx.session_id, expected_generation=ctx.binding_generation
    )
    if binding is None:
        return None
    doc = get_document_in_workspace(conn, doc_id, binding.workspace_path)
    if doc is None or doc.doc_type is not expected_doc_type:
        return None
    return document_path(doc), binding.workspace_path, doc


def _resolve_active_workspace(ctx: Optional[ToolExecutionContext]) -> Optional[Path]:
    """有活动绑定 → 绑定工作区 Path；否则 ``None``。"""
    if ctx is None or not ctx.session_id:
        return None
    try:
        conn = get_database().get_connection()
        binding = get_active_workspace(
            conn, ctx.session_id, expected_generation=ctx.binding_generation
        )
    except Exception:
        return None
    if binding is None:
        return None
    return Path(binding.workspace_path)


def _workspace_for_input(
    ctx: Optional[ToolExecutionContext], input_path: Path
) -> Path:
    """file_path 模式的服务层 workspace：优先绑定工作区，回退输入父目录。"""
    binding_ws = _resolve_active_workspace(ctx)
    if binding_ws is not None:
        return binding_ws
    return input_path.parent


def _bounded(data: Dict[str, Any], max_bytes: int) -> Dict[str, Any]:
    """超 ``max_bytes`` 时退化为 bounded head，语义同 tool_service。"""
    serialized = json.dumps(data, ensure_ascii=False, default=str)
    raw = serialized.encode("utf-8")
    if len(raw) <= max_bytes:
        return data
    head = raw[:max_bytes].decode("utf-8", errors="ignore")
    return {"truncated": True, "max_output_bytes": max_bytes, "head": head}


def _strip_workspace_path(data: Dict[str, Any]) -> Dict[str, Any]:
    """剥除 summary.workspace_path。"""
    summary = data.get("summary")
    if isinstance(summary, dict):
        summary.pop("workspace_path", None)
    return data


def _office_error_result(exc: Exception, fallback: str) -> ToolResult:
    """Office 异常 → 安全错误码。"""
    if isinstance(exc, OfficeFileNotFoundError):
        code = "file_not_found"
    elif isinstance(exc, OfficeSizeLimitError):
        code = "file_too_large"
    elif isinstance(exc, OfficePathError):
        code = "path_invalid"
    else:
        code = fallback
    message = str(exc)
    return ToolResult(success=False, error=f"{code}: {message}" if message else code)


def _resolve_template_input(  # noqa: PLR0911 — 错误早退路径多，保持线性可读
    tool: BaseTool,
    ctx: Optional[ToolExecutionContext],
    doc_id: Optional[str],
    file_path: Optional[str],
) -> Union[Tuple[Path, str, Any], ToolResult]:
    """解析 doc_id / file_path 双模式输入（两个模板工具共用，WORD 类型）。"""
    if isinstance(doc_id, str) and doc_id.strip():
        if ctx is None:
            # doc_id 模式需要 binding；写工具无 ctx 时 fail-closed
            # （读工具在 execute() 顶部已拦截，走不到这里）。
            return ToolResult(success=False, error="missing_tool_context")
        found = _resolve_bound_document(ctx, doc_id.strip(), OfficeDocType.WORD)
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
        if path.suffix.lower() != ".docx":
            return ToolResult(
                success=False,
                error="unsupported_file_type: 仅支持 .docx",
            )
        workspace = _workspace_for_input(ctx, path)
        return path, str(workspace), None
    return ToolResult(success=False, error="doc_id_or_file_path_required")


# ──────────────────────────────────────────────────────────────────────
# 读工具
# ──────────────────────────────────────────────────────────────────────


class OfficeAnalyzeWordTemplateTool(BaseTool):
    """List the {{placeholders}} inside a Word (docxtpl) template."""

    requires_tool_context = True
    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_analyze_word_template",
            description=(
                "Analyze a Word template (.docx) and list its {{placeholder}} "
                "tags — name, inferred type (text/image/date), location "
                "(body/table/header/footer), and whether Jinja2 control "
                "blocks are present. Locate by doc_id (from office_list) or "
                "absolute file_path. Call before office_fill_word_template "
                "to learn the exact placeholder names and which ones need "
                "images."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "description": "Word document id from office_list.",
                    },
                    "file_path": {
                        "type": "string",
                        "description": (
                            "ABSOLUTE path to a .docx template inside the "
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

        resolved = _resolve_template_input(self, ctx, doc_id, file_path)
        if isinstance(resolved, ToolResult):
            return resolved
        path, workspace, doc = resolved

        # 延迟 import：word_template 顶部拉 docxtpl（可选重依赖）。
        from backend.office.word_template import analyze_word_template

        try:
            result = analyze_word_template(
                path,
                workspace_path=workspace,
                document_id=doc.id if doc is not None else None,
            )
        except OfficeError as exc:
            return _office_error_result(exc, "analyze_failed")
        except Exception as exc:  # noqa: BLE001 — 解析器未归类异常按失败处理
            return ToolResult(success=False, error=f"analyze_failed: {exc}")

        data = _strip_workspace_path(result.model_dump(mode="json"))
        if doc is not None:
            # doc_id 模式不回显受管绝对路径，换成受管文件名。
            data["file_path"] = doc.generated_filename
        return ToolResult(
            success=True, content=_bounded(data, self._policy.max_output_bytes)
        )


# ──────────────────────────────────────────────────────────────────────
# 写工具
# ──────────────────────────────────────────────────────────────────────


class OfficeFillWordTemplateTool(BaseTool):
    """Fill a Word template's {{placeholders}} (in place or to output_path)."""

    requires_tool_context = False
    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_fill_word_template",
            description=(
                "Fill a Word template (.docx) by replacing {{placeholder}} "
                "tags with values. Locate the template by doc_id (from "
                "office_list) or absolute file_path. `data` maps exact "
                "placeholder names (from office_analyze_word_template) to "
                "strings; `images` maps image placeholders to a workspace "
                "image path or a data:image/... base64 URI (≤10MB). By "
                "default the template is filled IN PLACE; pass "
                "`output_path` to write a new .docx instead."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "description": "Word document id from office_list.",
                    },
                    "file_path": {
                        "type": "string",
                        "description": (
                            "ABSOLUTE path to the .docx template (when no "
                            "doc_id)."
                        ),
                    },
                    "data": {
                        "type": "object",
                        "description": "Map of placeholder name → text value.",
                    },
                    "images": {
                        "type": "object",
                        "description": (
                            "Optional map of image placeholder name → "
                            "workspace image path OR data:image/<fmt>;base64,... "
                            "URI (max 10MB decoded)."
                        ),
                    },
                    "output_path": {
                        "type": "string",
                        "description": (
                            "Optional ABSOLUTE path for the filled copy; "
                            "omit to fill in place."
                        ),
                    },
                },
                "required": ["data"],
            },
        )

    def execute(  # noqa: PLR0911 — 错误早退路径多，保持线性可读
        self,
        data: Optional[Dict[str, Any]] = None,
        images: Optional[Dict[str, str]] = None,
        doc_id: Optional[str] = None,
        file_path: Optional[str] = None,
        output_path: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        if not isinstance(data, dict) or not data:
            return ToolResult(success=False, error="data_required")
        if images is not None and not isinstance(images, dict):
            return ToolResult(success=False, error="images_invalid")

        ctx = current_tool_context()
        resolved = _resolve_template_input(self, ctx, doc_id, file_path)
        if isinstance(resolved, ToolResult):
            return resolved
        input_path, workspace_str, doc = resolved
        workspace = Path(workspace_str)

        # 最终落点：显式 output_path 或原地覆盖模板。
        if output_path is not None:
            if not isinstance(output_path, str) or not output_path.strip():
                return ToolResult(success=False, error="output_path_invalid")
            blocked = self._enforce_workspace(output_path)
            if blocked is not None:
                return blocked
            final = Path(output_path).expanduser()
            if not final.is_absolute():
                return ToolResult(
                    success=False,
                    error="output_path_absolute_required: 请传绝对路径",
                )
            if final.suffix.lower() != ".docx":
                return ToolResult(
                    success=False,
                    error="unsupported_file_type: 仅支持 .docx",
                )
            from backend.office.path_safety import resolve_within

            try:
                final = resolve_within(workspace, final)
            except OfficePathError as exc:
                return _office_error_result(exc, "output_path_invalid")
            if final.exists() and final != input_path.resolve():
                return ToolResult(
                    success=False,
                    error=f"file_exists: {final.name} 已存在，请更换 output_path",
                )
        else:
            final = input_path.resolve()

        # 服务层要求 output 不存在、不带分隔符、且写在模板同目录 →
        # 先落临时名再 os.replace 到最终落点。
        tmp_name = f".fill-{uuid.uuid4().hex}.docx"
        from backend.office.models import WordTemplateFillRequest
        from backend.office.word_template import fill_word_template  # 延迟 import

        req = WordTemplateFillRequest(
            workspace_path=workspace_str,
            template_path=str(input_path),
            output_filename=tmp_name,
            data=data,
            images=images,
        )
        try:
            result = fill_word_template(req)
        except OfficeError as exc:
            return _office_error_result(exc, "fill_failed")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=f"fill_failed: {exc}")

        tmp_path = Path(result.output_path)
        try:
            tmp_path.replace(final)
        except OSError as exc:
            tmp_path.unlink(missing_ok=True)
            return ToolResult(success=False, error=f"fill_failed: {exc}")

        _record_artifact_safely(str(final), final.stat().st_size)
        return ToolResult(
            success=True,
            content={
                "path": str(final),
                "filename": final.name,
                "bytes": final.stat().st_size,
                "filled_count": result.filled_count,
                "unfilled_placeholders": result.unfilled_placeholders,
                "in_place": final == input_path.resolve(),
            },
        )


__all__ = [
    "OfficeAnalyzeWordTemplateTool",
    "OfficeFillWordTemplateTool",
]
