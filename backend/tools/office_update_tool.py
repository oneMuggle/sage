# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Office update tool for the LLM tool loop (Office CRUD 的「改」).

``office_update`` applies structured in-place edits to an existing
Word / Excel / PPT document. Two locating modes:

1. **doc_id mode** — ``doc_id`` (from ``office_list``) resolves through
   the active session-workspace binding via ``OfficeToolService.update``:
   authorization, DB status refresh (EDITED) and path redaction all come
   from the service. Unknown / archived / cross-workspace ids collapse
   to the same indistinguishable ``document_not_found``.
2. **file_path mode** — an absolute path to a trusted file (same trust
   model as ``office_create``'s ``output_dir``). Writing outside the
   session workspace is gated by (1) ``make_office_path_boundary`` in
   the M1 PermissionEnforcer (upgrades to user approval in the legacy
   agent chain) and (2) ``BaseTool._enforce_workspace`` (hard reject in
   the hex chain).

Editing is all-or-nothing per call: ``backend.office.edit`` applies ops
to the in-memory document and only atomically replaces the file when
every op succeeds, so a malformed op never corrupts the user's file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.data.database import get_database
from backend.domain.risk import RiskClass
from backend.office.edit import update_document
from backend.office.models import OfficeDocType
from backend.office.path_safety import validate_supported_filename
from backend.office.tool_service import OfficeToolService
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.context import current_tool_context

#: file_path 模式允许的扩展名 → doc_type（防误把非 Office 文件喂给编辑器）
_EXT_TO_DOC_TYPE = {".docx": "word", ".xlsx": "excel", ".pptx": "ppt"}

_DOC_TYPE_ENUM = {
    "word": OfficeDocType.WORD,
    "excel": OfficeDocType.EXCEL,
    "ppt": OfficeDocType.PPT,
}

_OP_DESCRIPTIONS = {
    "word": (
        "word ops: replace_text{find,replace}; append_paragraphs{paragraphs:"
        "[{text,heading?}]}; append_table{headers,rows}; set_table_cell"
        "{table_index,row,col,text}（row 0 为表头行）; delete_paragraph{find,all?}"
    ),
    "excel": (
        "excel ops: set_cells{sheet,cells:[{addr,value}]}（A1 记法，数字串按 Excel "
        "录入语义转数值）; append_rows{sheet,rows}; add_sheet{name,headers?,rows?}; "
        "rename_sheet{from,to}; delete_sheet{name}"
    ),
    "ppt": (
        "ppt ops（slide index 从 0 起）: replace_text{find,replace}; set_slide_title"
        "{index,title}; set_slide_bullets{index,bullets}; set_slide_notes{index,notes}; "
        "append_slide{title,bullets?,notes?}; delete_slide{index}"
    ),
}


def _infer_doc_type(file_path: Path) -> Optional[str]:
    return _EXT_TO_DOC_TYPE.get(file_path.suffix.lower())


def _normalize_ops(ops: Any) -> Optional[List[Dict[str, Any]]]:
    """ops 必须是非空 dict 数组；返回 None 表示非法。"""
    if not isinstance(ops, list) or not ops:
        return None
    for op in ops:
        if not isinstance(op, dict) or not isinstance(op.get("op"), str):
            return None
    return ops


class OfficeUpdateTool(BaseTool):
    """Edit an existing Office document in place (word/excel/ppt)."""

    requires_tool_context = False
    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_update",
            description=(
                "Edit an existing Office document (Word/Excel/PPT) IN PLACE. "
                "Locate the file either by doc_id (from office_list, uses the "
                "active chat workspace) or by absolute file_path. `ops` is a "
                "list of operation objects applied all-or-nothing. "
                + _OP_DESCRIPTIONS["word"]
                + "; "
                + _OP_DESCRIPTIONS["excel"]
                + "; "
                + _OP_DESCRIPTIONS["ppt"]
                + "."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "description": (
                            "Document id from office_list. Takes precedence " "over file_path."
                        ),
                    },
                    "file_path": {
                        "type": "string",
                        "description": (
                            "ABSOLUTE path to an existing .docx/.xlsx/.pptx "
                            "file (when no doc_id). doc_type is inferred from "
                            "the extension."
                        ),
                    },
                    "ops": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": (
                            "Operation list; each op is {'op': <name>, ...}. "
                            + _OP_DESCRIPTIONS["word"]
                            + "; "
                            + _OP_DESCRIPTIONS["excel"]
                            + "; "
                            + _OP_DESCRIPTIONS["ppt"]
                        ),
                    },
                },
                "required": ["ops"],
            },
        )

    def execute(
        self,
        doc_id: Optional[str] = None,
        file_path: Optional[str] = None,
        ops: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> ToolResult:
        normalized = _normalize_ops(ops)
        if normalized is None:
            return ToolResult(success=False, error="ops_required")
        if isinstance(doc_id, str) and doc_id.strip():
            return self._execute_bound(doc_id.strip(), normalized)
        if isinstance(file_path, str) and file_path.strip():
            return self._execute_by_path(file_path.strip(), normalized)
        return ToolResult(success=False, error="doc_id_or_file_path_required")

    # ── doc_id 模式：走 service（授权 + DB 登记） ────────────────────

    def _execute_bound(self, doc_id: str, ops: List[Dict[str, Any]]) -> ToolResult:
        ctx = current_tool_context()
        if ctx is None or not ctx.session_id:
            return ToolResult(success=False, error="missing_tool_context")
        try:
            conn = get_database().get_connection()
        except Exception:
            return ToolResult(success=False, error="document_not_found")
        service = OfficeToolService(policy=self._policy)
        try:
            result = service.update(conn, ctx.session_id, ctx.binding_generation, doc_id, ops)
        except Exception:
            return ToolResult(success=False, error="update_failed")
        if not result.get("success"):
            err = result.get("error") or {}
            code = str(err.get("code") or "update_failed")
            return ToolResult(
                success=False,
                error=code,
                content={"results": result.get("results")} if result.get("results") else None,
            )
        return ToolResult(success=True, content=result.get("content"))

    # ── file_path 模式：直接编辑（越界由权限层守卫） ─────────────────

    def _execute_by_path(  # noqa: PLR0911 — fail-fast 守卫链，逐条早退
        self, file_path: str, ops: List[Dict[str, Any]]
    ) -> ToolResult:
        blocked = self._enforce_workspace(file_path)
        if blocked is not None:
            return blocked
        path = Path(file_path).expanduser()
        if not path.is_absolute():
            return ToolResult(
                success=False,
                error="file_path_absolute_required: 请传绝对路径",
            )
        doc_type = _infer_doc_type(path)
        if doc_type is None:
            return ToolResult(
                success=False,
                error="unsupported_file_type: 仅支持 .docx/.xlsx/.pptx",
            )
        try:
            # 扩展名与文件名合法性共用 path_safety 校验（防路径怪字符）。
            validate_supported_filename(path.name, _DOC_TYPE_ENUM[doc_type])
        except Exception:
            return ToolResult(success=False, error="invalid_filename")
        if not path.is_file():
            return ToolResult(success=False, error="file_not_found")

        try:
            saved, results = update_document(doc_type, path, ops)
        except Exception as exc:
            return ToolResult(success=False, error=f"update_failed: {exc}")
        if not saved:
            return ToolResult(
                success=False,
                error="operation_failed",
                content={"results": results},
            )
        return ToolResult(
            success=True,
            content={
                "path": str(path.resolve()),
                "filename": path.name,
                "bytes": path.stat().st_size,
                "results": results,
            },
        )


__all__ = ["OfficeUpdateTool"]
