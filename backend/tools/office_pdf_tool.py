# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Office PDF tool wrappers for the LLM tool loop (Office Parity Batch-1).

把 HTTP 端点已验证的 4 个 PDF 能力接入 LLM 工具面（backend/api/office_routes.py
Phase-2 段的镜像）：

- ``office_read_pdf``      ← POST /office/pdf/read       → ``pdf.read_pdf``
- ``office_generate_pdf``  ← POST /office/pdf/generate   → ``pdf.generate_pdf``
- ``office_read_pdf_form`` ← POST /office/pdf/read-form  → ``pdf_forms.read_pdf_form``
- ``office_fill_pdf_form`` ← POST /office/pdf/fill-form  → ``pdf_forms.fill_pdf_form``

安全姿态与 office_tool / office_update_tool 一致：

1. 读工具（read_pdf / read_pdf_form）``requires_tool_context = True``：
   registry 在无活动 ``ToolExecutionContext`` 时隐藏 schema；execute()
   顶部再 fail-closed（防御纵深，stale 调用照样拒绝）。
2. 写工具（generate_pdf / fill_pdf_form）``requires_tool_context = False``
   （同 office_create / office_update 的 file_path 模式），越界写入由
   (1) M1 PermissionEnforcer 的 path boundary（legacy 链升级为审批）和
   (2) ``BaseTool._enforce_workspace``（hex 链硬拒绝）双层把守。
3. doc_id 模式经 session-workspace binding 解析（``get_active_workspace``
   + ``get_document_in_workspace``，与 ``OfficeToolService._resolve_doc``
   同构）；未知 / 归档 / 跨工作区 / 过期 generation 一律折叠为
   ``document_not_found``，输出不区分「拒绝」与「不存在」。
4. LLM 输出永不回显 binding 的绝对 workspace_path（summary.workspace_path
   剥除，同 ``OfficeToolService._serialize_summary``）；doc_id 模式下的
   顶层 file_path 替换为受管文件名。
5. 读输出按 ``policy.max_output_bytes`` 截断（head + truncated 标记），
   同 ``OfficeToolService._truncate_to_byte_cap`` —— 50MB PDF 全文不进
   LLM 上下文。

服务函数（pdf.py / pdf_forms.py）在模块顶部 import pymupdf，属可选重
依赖 —— 与 tool_service 的 reader 模式一致，这里延迟到 execute() 内再
import，坏依赖不拖垮整个工具模块。

Public surface:

    OfficeReadPdfTool(policy=None)       # name="office_read_pdf"
    OfficeGeneratePdfTool(policy=None)   # name="office_generate_pdf"
    OfficeReadPdfFormTool(policy=None)   # name="office_read_pdf_form"
    OfficeFillPdfFormTool(policy=None)   # name="office_fill_pdf_form"
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

#: page_size 参数（LLM 面小写）→ PdfGenerateRequest 服务层取值
_PAGE_SIZE_MAP = {
    "a4": "A4",
    "letter": "Letter",
    "legal": "Legal",
}


# ──────────────────────────────────────────────────────────────────────
# 共享小助手（office_template_tool.py 内有镜像副本，保持模块自包含）
# ──────────────────────────────────────────────────────────────────────


def _resolve_bound_document(
    ctx: ToolExecutionContext,
    doc_id: str,
    expected_doc_type: OfficeDocType,
) -> Optional[Tuple[Path, str, Any]]:
    """binding 内解析 doc_id → (on-disk path, workspace_path, summary)。

    与 ``OfficeToolService._resolve_doc`` 同构：binding 过期 / 撤销、doc
    未知 / 归档 / 跨工作区一律返回 ``None``（调用方折叠为 document_not_found，
    不区分拒绝与不存在）。doc 类型不匹配同样折叠为 ``None``（office_list
    已携带类型信息，试错成本低，且不额外泄漏受管状态）。
    """
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
    """有活动绑定 → 绑定工作区 Path；否则 ``None``（DB 不可用同样吞掉）。"""
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
    """file_path 模式的服务层 workspace 取值。

    优先绑定工作区（覆盖 ``<workspace>/office/...`` 受管文档与工作区任意
    子目录）；无绑定时回退输入文件父目录（ad-hoc 单文件模式，越界由
    ``_enforce_workspace`` + 服务层 ``resolve_within`` 双层把守）。
    """
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
    """剥除 summary.workspace_path（LLM 面永不回显 binding 绝对路径）。"""
    summary = data.get("summary")
    if isinstance(summary, dict):
        summary.pop("workspace_path", None)
    return data


def _office_error_result(exc: Exception, fallback: str) -> ToolResult:
    """Office 异常 → 安全错误码（消息含服务层 generic 文案，不泄漏新路径）。"""
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


def _resolve_pdf_input(  # noqa: PLR0911 — 错误早退路径多，保持线性可读
    tool: BaseTool,
    ctx: Optional[ToolExecutionContext],
    doc_id: Optional[str],
    file_path: Optional[str],
    expected_doc_type: OfficeDocType = OfficeDocType.PDF,
) -> Union[Tuple[Path, str, Any], ToolResult]:
    """解析 doc_id / file_path 双模式输入（4 个 PDF 工具共用）。

    返回 ``(on-disk path, workspace_path, doc|None)``；参数缺失 / 越界 /
    not-found 时返回失败 :class:`ToolResult`。doc 只在 doc_id 命中时非空
    （file_path 模式没有受管 row，类型约束由扩展名检查承担）。
    """
    if isinstance(doc_id, str) and doc_id.strip():
        if ctx is None:
            # doc_id 模式需要 binding；写工具无 ctx 时 fail-closed
            # （读工具在 execute() 顶部已拦截，走不到这里）。
            return ToolResult(success=False, error="missing_tool_context")
        found = _resolve_bound_document(ctx, doc_id.strip(), expected_doc_type)
        if found is None:
            # 未知 / 归档 / 跨工作区 / 过期 generation / 类型不符 → 同一错误码。
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
        expected_ext = ".pdf" if expected_doc_type is OfficeDocType.PDF else ".docx"
        if path.suffix.lower() != expected_ext:
            return ToolResult(
                success=False,
                error=f"unsupported_file_type: 仅支持 {expected_ext}",
            )
        workspace = _workspace_for_input(ctx, path)
        return path, str(workspace), None
    return ToolResult(success=False, error="doc_id_or_file_path_required")


# ──────────────────────────────────────────────────────────────────────
# 读工具
# ──────────────────────────────────────────────────────────────────────


class OfficeReadPdfTool(BaseTool):
    """Read a PDF's text content (page-wise) from the bound workspace."""

    requires_tool_context = True
    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_read_pdf",
            description=(
                "Read a PDF file's text content page by page (plus "
                "metadata). Locate the file either by doc_id (from "
                "office_list, uses the active chat workspace) or by an "
                "absolute file_path inside the workspace. Use before "
                "office_fill_pdf_form to inspect contents, or to extract "
                "text from uploaded/generated PDFs."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "description": "PDF document id from office_list.",
                    },
                    "file_path": {
                        "type": "string",
                        "description": (
                            "ABSOLUTE path to a .pdf inside the active "
                            "chat workspace (when no doc_id)."
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

        resolved = _resolve_pdf_input(self, ctx, doc_id, file_path)
        if isinstance(resolved, ToolResult):
            return resolved
        path, workspace, doc = resolved

        from backend.office.pdf import read_pdf  # 延迟 import（pymupdf 重依赖）

        try:
            result = read_pdf(
                path,
                workspace_path=workspace,
                document_id=doc.id if doc is not None else None,
            )
        except OfficeError as exc:
            return _office_error_result(exc, "read_failed")
        except Exception as exc:  # noqa: BLE001 — 解析器未归类异常按失败处理
            return ToolResult(success=False, error=f"read_failed: {exc}")

        data = _strip_workspace_path(result.model_dump(mode="json"))
        return ToolResult(
            success=True, content=_bounded(data, self._policy.max_output_bytes)
        )


class OfficeReadPdfFormTool(BaseTool):
    """List a PDF's AcroForm fields (names, types, current values)."""

    requires_tool_context = True
    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_read_pdf_form",
            description=(
                "Read a PDF's form fields (AcroForm): field names, types, "
                "current values, options, required/read-only flags. Locate "
                "by doc_id (from office_list) or absolute file_path inside "
                "the workspace. Call before office_fill_pdf_form to learn "
                "the exact field names to fill."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "description": "PDF document id from office_list.",
                    },
                    "file_path": {
                        "type": "string",
                        "description": (
                            "ABSOLUTE path to a .pdf inside the active "
                            "chat workspace (when no doc_id)."
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

        resolved = _resolve_pdf_input(self, ctx, doc_id, file_path)
        if isinstance(resolved, ToolResult):
            return resolved
        path, workspace, doc = resolved

        from backend.office.pdf_forms import read_pdf_form  # 延迟 import

        try:
            result = read_pdf_form(path, workspace_path=workspace)
        except OfficeError as exc:
            return _office_error_result(exc, "read_failed")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=f"read_failed: {exc}")

        data = result.model_dump(mode="json")
        if doc is not None:
            # doc_id 模式不回显受管绝对路径，换成受管文件名。
            data["file_path"] = doc.generated_filename
        return ToolResult(success=True, content=_bounded(data, self._policy.max_output_bytes))


# ──────────────────────────────────────────────────────────────────────
# 写工具
# ──────────────────────────────────────────────────────────────────────


class OfficeGeneratePdfTool(BaseTool):
    """Generate a new PDF from a title + paragraphs (reportlab)."""

    requires_tool_context = False
    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_generate_pdf",
            description=(
                "Generate a new PDF file from a title and paragraphs. "
                "`output_path` is an ABSOLUTE path for the new .pdf (must "
                "not already exist; inside the chat workspace when one is "
                "bound — outside paths need user approval). Use for "
                "read-only-looking reports/letters where a .pdf is "
                "explicitly requested; prefer office_create (docx) when "
                "the format is open."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "output_path": {
                        "type": "string",
                        "description": (
                            "ABSOLUTE target path for the generated .pdf "
                            "(file must not exist yet)."
                        ),
                    },
                    "title": {
                        "type": "string",
                        "description": "Optional first-page title line.",
                    },
                    "paragraphs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Body paragraphs, in order.",
                    },
                    "tables": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "description": (
                            "Optional tables; each table is a list of rows "
                            "of string cells (rendered as text rows)."
                        ),
                    },
                    "page_size": {
                        "type": "string",
                        "enum": ["a4", "letter", "legal"],
                        "description": "Page size (default a4).",
                        "default": "a4",
                    },
                },
                "required": ["output_path", "paragraphs"],
            },
        )

    def execute(  # noqa: PLR0911 — 错误早退路径多，保持线性可读
        self,
        output_path: Optional[str] = None,
        file_path: Optional[str] = None,  # 别名兜底：LLM 偶尔把目标路径叫 file_path
        title: Optional[str] = None,
        paragraphs: Optional[Any] = None,
        tables: Optional[Any] = None,
        page_size: str = "a4",
        **kwargs: Any,
    ) -> ToolResult:
        target = output_path if isinstance(output_path, str) and output_path.strip() else file_path
        if not isinstance(target, str) or not target.strip():
            return ToolResult(success=False, error="output_path_required")
        if (
            not isinstance(paragraphs, list)
            or not paragraphs
            or not all(isinstance(p, str) for p in paragraphs)
        ):
            return ToolResult(success=False, error="paragraphs_required")

        blocked = self._enforce_workspace(target)
        if blocked is not None:
            return blocked
        path = Path(target).expanduser()
        if not path.is_absolute():
            return ToolResult(
                success=False,
                error="output_path_absolute_required: 请传绝对路径",
            )
        if path.suffix.lower() != ".pdf":
            return ToolResult(success=False, error="unsupported_file_type: 仅支持 .pdf")
        if not path.parent.is_dir():
            return ToolResult(success=False, error="output_dir_not_found")
        if path.exists():
            # 服务层对已存在输出只会报 generic 错误；这里给出明确错误码
            # （与 office_create 的 file_exists 语义一致）。
            return ToolResult(
                success=False,
                error=f"file_exists: {path.name} 已存在，请更换 output_path",
            )

        size = _PAGE_SIZE_MAP.get(str(page_size).lower())
        if size is None:
            return ToolResult(
                success=False,
                error=f"unsupported_page_size: {page_size} (可选 a4/letter/legal)",
            )

        from backend.office.models import PdfGenerateRequest
        from backend.office.pdf import generate_pdf  # 延迟 import（reportlab）

        req = PdfGenerateRequest(
            workspace_path=str(path.parent),
            filename=path.name,
            pages=[
                {
                    "title": title,
                    "paragraphs": paragraphs,
                    "tables": tables if isinstance(tables, list) else [],
                }
            ],
            page_size=size,
        )
        try:
            result = generate_pdf(req)
        except OfficeError as exc:
            return _office_error_result(exc, "generate_failed")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=f"generate_failed: {exc}")

        output = Path(result.output_path)
        # 记录 Artifacts（无 tool_context 时静默跳过，不阻断结果）。
        _record_artifact_safely(str(output), result.file_size_bytes)
        return ToolResult(
            success=True,
            content={
                "path": str(output),
                "filename": result.filename,
                "bytes": result.file_size_bytes,
                "page_count": result.page_count,
            },
        )


class OfficeFillPdfFormTool(BaseTool):
    """Fill a PDF's AcroForm fields (in place or to output_path)."""

    requires_tool_context = False
    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_fill_pdf_form",
            description=(
                "Fill a PDF form (AcroForm) with values. Locate the form "
                "by doc_id (from office_list) or absolute file_path. "
                "`data` maps exact field names (from office_read_pdf_form) "
                "to values. By default the file is filled IN PLACE; pass "
                "`output_path` to write a new .pdf instead. flatten=true "
                "makes fields read-only after filling."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "description": "PDF document id from office_list.",
                    },
                    "file_path": {
                        "type": "string",
                        "description": (
                            "ABSOLUTE path to the .pdf with form fields "
                            "(when no doc_id)."
                        ),
                    },
                    "data": {
                        "type": "object",
                        "description": "Map of form field name → value.",
                    },
                    "output_path": {
                        "type": "string",
                        "description": (
                            "Optional ABSOLUTE path for the filled copy; "
                            "omit to fill in place."
                        ),
                    },
                    "flatten": {
                        "type": "boolean",
                        "description": "Set fields read-only after filling (default false).",
                        "default": False,
                    },
                },
                "required": ["data"],
            },
        )

    def execute(  # noqa: PLR0911 — 错误早退路径多，保持线性可读
        self,
        data: Optional[Dict[str, Any]] = None,
        doc_id: Optional[str] = None,
        file_path: Optional[str] = None,
        output_path: Optional[str] = None,
        flatten: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        if not isinstance(data, dict) or not data:
            return ToolResult(success=False, error="data_required")

        ctx = current_tool_context()
        resolved = _resolve_pdf_input(self, ctx, doc_id, file_path)
        if isinstance(resolved, ToolResult):
            return resolved
        input_path, workspace_str, doc = resolved
        workspace = Path(workspace_str)

        # 最终落点：显式 output_path 或原地覆盖输入文件。
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
            if final.suffix.lower() != ".pdf":
                return ToolResult(
                    success=False,
                    error="unsupported_file_type: 仅支持 .pdf",
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

        # 服务层要求 output 不存在且不带路径分隔符 → 先写工作区内临时名，
        # 成功后 os.replace 到最终落点（同一工作区卷内原子改名）。
        tmp_name = f".fill-{uuid.uuid4().hex}.pdf"
        from backend.office.models import PdfFormFillRequest
        from backend.office.pdf_forms import fill_pdf_form  # 延迟 import

        req = PdfFormFillRequest(
            workspace_path=workspace_str,
            template_path=str(input_path),
            output_filename=tmp_name,
            data=data,
            flatten=bool(flatten),
        )
        try:
            result = fill_pdf_form(req)
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
                "in_place": final == input_path.resolve(),
            },
        )


__all__ = [
    "OfficeFillPdfFormTool",
    "OfficeGeneratePdfTool",
    "OfficeReadPdfFormTool",
    "OfficeReadPdfTool",
]
