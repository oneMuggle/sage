"""Office create tool for the LLM tool loop.

``office_create`` lets the LLM generate a Word / Excel / PPT document to an
arbitrary (trusted) target directory -- e.g. the user's Desktop. Unlike the
existing ``office_list`` / ``office_read`` (which need an @-mention to bind a
``ToolExecutionContext``), ``requires_tool_context = False`` so the tool is
always visible and a plain question ("create a word doc on my desktop") can
trigger it directly.

Writing outside the session workspace is gated by two complementary layers:
(1) ``path_boundary_validator`` in the M1 ``PermissionEnforcer`` (see
permissions.py) upgrades a cross-workspace write to approval in the legacy
agent chain; (2) ``BaseTool._enforce_workspace`` in ``execute()`` rejects the
write outright when ``policy.workspace_root`` is bound (the hex chain).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from backend.data.database import get_database
from backend.domain.risk import RiskClass
from backend.office.excel import generate_xlsx
from backend.office.models import (
    OfficeDocType,
    OfficeExcelGenerateRequest,
    OfficePptGenerateRequest,
    OfficeWordGenerateRequest,
)
from backend.office.path_safety import OfficePathError, validate_supported_filename
from backend.office.ppt import generate_ppt
from backend.office.session_workspace import get_active_workspace
from backend.office.tool_service import OfficeToolService
from backend.office.word import generate_docx
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.context import current_tool_context
from backend.tools.file_tool import _record_artifact_safely

#: doc_type 参数合法取值（与 models.OfficeDocType 对齐）
_VALID_DOC_TYPES = tuple(t.value for t in OfficeDocType)


def _check_content(content: Any) -> Optional[ToolResult]:
    """校验 content：非空 dict 或非空字符串（字符串由 ``_normalize_content``
    包装为 word 段落）。拆开 isinstance 避免 UP038（union 语法 3.10+）。"""
    if content is None:
        return ToolResult(success=False, error="content_required")
    if isinstance(content, str):
        if not content.strip():
            return ToolResult(success=False, error="content_required")
        return None
    if not isinstance(content, dict) or not content:
        return ToolResult(success=False, error="content_required")
    return None


class OfficeCreateTool(BaseTool):
    """Generate an Office document (word/excel/ppt) to a target directory."""

    requires_tool_context = False
    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_create",
            description=(
                "Create a new Office document (Word/Excel/PPT) and write it to "
                "a target directory. Use when the user asks to create / generate "
                "a .docx/.xlsx/.pptx file (e.g. on their Desktop). `content` is "
                "an object whose shape depends on `doc_type`: word → "
                "{title, paragraphs:[{text, heading?}], tables:[{headers, rows[]}]}, "
                "excel → {sheets:[{name, headers[], rows[]}]}, ppt → "
                "{slides:[{title, bullets[], notes?}]}."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "doc_type": {
                        "type": "string",
                        "enum": list(_VALID_DOC_TYPES),
                        "description": (
                            "Document type (case-insensitive: word/Word/WORD "
                            "are all accepted)."
                        ),
                    },
                    "output_dir": {
                        "type": "string",
                        "description": (
                            "Target directory — ABSOLUTE path or ~-prefixed "
                            "(e.g. /home/user/Desktop or ~/Desktop). Do NOT use "
                            "a bare relative name like '桌面'. Created if missing."
                        ),
                    },
                    "filename": {
                        "type": "string",
                        "description": (
                            "Output filename. Extension is appended if missing "
                            "(.docx/.xlsx/.pptx); a wrong extension is rejected."
                        ),
                    },
                    "content": {
                        "type": "object",
                        "description": (
                            "Structured content as a JSON object, keyed by "
                            "doc_type: word → {title, paragraphs:[{text, "
                            "heading?}], tables:[{headers, rows[]}]}; excel → "
                            "{sheets:[{name, headers[], rows[]}]}; ppt → "
                            "{slides:[{title, bullets[], notes?}]}. A plain "
                            "string is also accepted for word (treated as body "
                            "text)."
                        ),
                        "properties": {
                            "title": {
                                "type": "string",
                                "description": "word 文档标题。",
                            },
                            "paragraphs": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "text": {"type": "string"},
                                        "heading": {
                                            "type": ["string", "null"],
                                            "description": "'h1'/'h2'/'h3' 或 null",
                                        },
                                    },
                                    "required": ["text"],
                                },
                                "description": "word 段落列表。",
                            },
                            "tables": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "headers": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "rows": {
                                            "type": "array",
                                            "items": {
                                                "type": "array",
                                                "items": {"type": "string"},
                                            },
                                        },
                                    },
                                },
                                "description": "word 表格列表。",
                            },
                            "sheets": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "headers": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "rows": {
                                            "type": "array",
                                            "items": {
                                                "type": "array",
                                                "items": {"type": "string"},
                                            },
                                        },
                                    },
                                },
                                "description": "excel 工作表列表。",
                            },
                            "slides": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "title": {"type": "string"},
                                        "bullets": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "notes": {"type": "string"},
                                    },
                                },
                                "description": "ppt 幻灯片列表。",
                            },
                        },
                    },
                },
                "required": ["doc_type", "output_dir", "filename", "content"],
            },
        )

    def execute(
        self,
        doc_type: Optional[str] = None,
        output_dir: Optional[str] = None,
        filename: Optional[str] = None,
        content: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ToolResult:
        # doc_type 大小写容错（T6 实测模型传 "Word"）：归一化后再校验。
        if isinstance(doc_type, str):
            doc_type = doc_type.lower()
        error = self._check_params(doc_type, output_dir, filename, content)
        if error is not None:
            return error

        # ---- T7.5: binding-aware delegation -----------------------------
        # When the agent loop is running under a session-workspace binding
        # (``@workspace foo`` in the chat) we MUST route through
        # ``OfficeToolService.create`` so the doc is registered in
        # ``office_documents`` -- otherwise list/read can't see it (the
        # round-trip bug T7.5 fixes).
        delegated = self._try_delegate_to_bound_service(
            doc_type=doc_type, filename=filename, content=content
        )
        if delegated is not None:
            return delegated

        doc_type_enum = OfficeDocType(doc_type)
        target_dir = Path(output_dir).expanduser().resolve()
        error = self._check_path(output_dir, filename, doc_type_enum, target_dir)
        if error is not None:
            return error
        content = self._normalize_content(doc_type_enum, filename, content)
        if content is None:
            return ToolResult(success=False, error="content_required")
        return self._generate_document(doc_type_enum, filename, content, target_dir)

    @staticmethod
    def _try_delegate_to_bound_service(
        *,
        doc_type: str,
        filename: str,
        content: Any,
    ) -> Optional[ToolResult]:
        """Route to OfficeToolService.create when an active binding exists.

        Returns:
            * ``None`` when there is no live binding (caller falls through
              to the legacy ``output_dir`` flow).
            * A :class:`ToolResult` carrying the service's ``{document_id,
              doc_type, filename}`` payload when delegation succeeds.
            * A failure :class:`ToolResult` if the service returns an
              error (e.g. stale generation, generation failure).
        """
        ctx = current_tool_context()
        if ctx is None or not ctx.session_id:
            return None
        try:
            db = get_database()
            conn = db.get_connection()
        except Exception:
            # No DB configured (e.g. legacy caller) -> fall through to
            # legacy ``output_dir`` path so plain "create on Desktop"
            # requests still work.
            return None
        binding = get_active_workspace(
            conn, ctx.session_id, expected_generation=ctx.binding_generation
        )
        if binding is None:
            return None

        service = OfficeToolService()
        result = service.create(
            conn,
            ctx.session_id,
            ctx.binding_generation,
            doc_type=doc_type,
            filename=filename,
            content=content,
        )
        if not result.get("success"):
            err = result.get("error") or {}
            return ToolResult(
                success=False,
                error=str(err.get("code") or "create_failed"),
            )
        return ToolResult(success=True, content=result["content"])

    @staticmethod
    def _normalize_content(
        doc_type_enum: OfficeDocType,
        filename: str,
        content: Any,
    ) -> Optional[Dict[str, Any]]:
        """把 LLM 常见的简化 content 归一化为结构化 dict。

        - 纯字符串 content（"今天天气很好"）→ word 正文段落（标题取文件名主名）。
        - 其它类型保持原样（pydantic 校验兜底）。

        Returns:
            归一化的 dict；excel/ppt 收到纯字符串时返回 None（保持严格）。
        """
        if isinstance(content, str) and content.strip():
            if doc_type_enum is OfficeDocType.WORD:
                title = Path(filename).stem or "文档"
                return {"title": title, "paragraphs": [{"text": content.strip()}]}
            return None
        return content

    @staticmethod
    def _check_params(
        doc_type: Optional[str],
        output_dir: Optional[str],
        filename: Optional[str],
        content: Optional[Dict[str, Any]],
    ) -> Optional[ToolResult]:
        """fail-fast 参数校验；返回错误 ToolResult 或 None（通过）。"""
        if doc_type not in _VALID_DOC_TYPES:
            return ToolResult(success=False, error=f"unsupported_doc_type: {doc_type}")
        if not isinstance(output_dir, str) or not output_dir.strip():
            return ToolResult(success=False, error="output_dir_required")
        # 相对路径（非绝对、非 ~ 开头）拒绝——避免静默 resolve 到 cwd 而非
        # 用户真实目录（T6 实测 LLM 传 "Desktop" 落到 <cwd>/Desktop）。
        if not Path(output_dir).is_absolute() and not output_dir.startswith("~"):
            return ToolResult(
                success=False,
                error=(
                    "output_dir_relative: 请用绝对路径或以 ~ 开头"
                    f"（如 ~/Desktop），而非 {output_dir!r}"
                ),
            )
        if not isinstance(filename, str) or not filename.strip():
            return ToolResult(success=False, error="filename_required")
        return _check_content(content)

    def _check_path(
        self,
        output_dir: str,
        filename: str,
        doc_type_enum: OfficeDocType,
        target_dir: Path,
    ) -> Optional[ToolResult]:
        """工作区边界 + 路径守卫；返回错误 ToolResult 或 None（通过）。

        - 工作区边界：``policy.workspace_root`` 绑定（hex 链）时拒绝越界写入；
          未绑定（legacy 链）时 ``_enforce_workspace`` 返回 None，零行为变化。
        - 目录必须是目录；目标文件已存在则拒绝（不覆盖）。
        """
        blocked = self._enforce_workspace(output_dir)
        if blocked is not None:
            return blocked
        if target_dir.exists() and not target_dir.is_dir():
            return ToolResult(success=False, error="output_dir_not_directory")
        try:
            safe_name = validate_supported_filename(filename, doc_type_enum)
        except OfficePathError as exc:
            return ToolResult(success=False, error=str(exc))
        target_file = target_dir / safe_name
        if target_file.exists():
            return ToolResult(
                success=False,
                error=f"file_exists: {target_file} 已存在，请更换文件名",
            )
        return None

    def _generate_document(
        self,
        doc_type_enum: OfficeDocType,
        filename: str,
        content: Dict[str, Any],
        target_dir: Path,
    ) -> ToolResult:
        """构造生成请求并执行（复用生成器 + Pydantic 校验），返回结果。"""
        payload: Dict[str, Any] = dict(content)
        payload["workspace_path"] = ""
        payload["filename"] = filename
        try:
            if doc_type_enum is OfficeDocType.WORD:
                req = OfficeWordGenerateRequest(**payload)
                output = generate_docx(req, output_dir=str(target_dir))
            elif doc_type_enum is OfficeDocType.EXCEL:
                req = OfficeExcelGenerateRequest(**payload)
                output = generate_xlsx(req, output_dir=str(target_dir))
            else:
                req = OfficePptGenerateRequest(**payload)
                output = generate_ppt(req, output_dir=str(target_dir))
        except Exception as exc:
            return ToolResult(success=False, error=f"generate_failed: {exc}")

        stat = output.stat()

        # --- 记录 Artifacts（无 tool_context 时静默跳过，不阻断结果） ------
        # ``_record_artifact_safely`` 内部已吞掉一切异常，无需再包一层。
        _record_artifact_safely(str(output), stat.st_size)

        return ToolResult(
            success=True,
            content={
                "path": str(output),
                "filename": output.name,
                "bytes": stat.st_size,
            },
        )


__all__ = ["OfficeCreateTool"]
