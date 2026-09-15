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

Plan 3.4 self-check readback: on success the result carries
``content["self_check"]`` — a compact read-back of the edited file
(counts per doc_type) so the model can immediately verify the edit
landed. Best-effort: read-back failure never fails the tool result.

Round-2 R4 ``dry_run``: with ``dry_run=true`` the tool resolves the
target file exactly like a real update, then runs the read-only
:func:`backend.office.diff_preview.preview_update` (ops applied to a
temp copy, source untouched) and returns
``{"dry_run": True, "changes": [...], "truncated": bool}`` instead of
writing anything. Preview failure (invalid ops / unreadable file)
collapses to the standard ``success=False`` error shape.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.data.database import get_database
from backend.domain.risk import RiskClass
from backend.office.diff_preview import preview_update
from backend.office.edit import update_document
from backend.office.models import OfficeDocType
from backend.office.path_safety import validate_supported_filename
from backend.office.selfcheck_history import record
from backend.office.session_workspace import (
    get_active_workspace,
    get_document_in_workspace,
)
from backend.office.storage import document_path
from backend.office.tool_service import OfficeToolService
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.context import ToolExecutionContext, current_tool_context
from backend.tools.office_create_tool import build_self_check, managed_self_check

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
        "{table_index,row,col,text}（row 0 为表头行）; delete_paragraph{find,all?}; "
        "add_image{path|base64,width_inches?,height_inches?}（≤10MB）; "
        "set_paragraph_style{index|match,font_size?,bold?,italic?,color?,align?}"
        "（样式作用于该段全部 runs）; add_comment{find,comment,author?,date?}"
        "（批注锚定首个包含 find 的段落）; delete_comment{comment_id}"
    ),
    "excel": (
        "excel ops: set_cells{sheet,cells:[{addr,value}]}（A1 记法，数字串按 Excel "
        "录入语义转数值）; append_rows{sheet,rows}; add_sheet{name,headers?,rows?}; "
        "rename_sheet{from,to}; delete_sheet{name}; add_chart{sheet,type:"
        "'line'|'bar'|'pie',anchor,data_ref:{min_col,min_row,max_col,max_row},"
        "titles_from_data?,from_rows?,categories_ref?,title?}（原生图表）; "
        "set_column_width{sheet,column,width}; set_number_format{sheet,cells,format}; "
        "set_fill{sheet,cells,color（6 位 hex）}; freeze_panes{sheet,cell}"
    ),
    "ppt": (
        "ppt ops（slide index 从 0 起）: replace_text{find,replace}; set_slide_title"
        "{index,title}; set_slide_bullets{index,bullets}; set_slide_notes{index,notes}; "
        "append_slide{title,bullets?,notes?}; delete_slide{index}; "
        "add_picture{index,path|base64,width_inches?,height_inches?}（≤10MB）"
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
                    "dry_run": {
                        "type": "boolean",
                        "description": (
                            "true 时仅预览变更不落盘（返回 diff 变更清单），默认 false"
                        ),
                    },
                },
                "required": ["ops"],
            },
        )

    def execute(  # noqa: PLR0911 — dry_run/正式路径守卫链，逐条早退
        self,
        doc_id: Optional[str] = None,
        file_path: Optional[str] = None,
        ops: Optional[List[Dict[str, Any]]] = None,
        dry_run: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        normalized = _normalize_ops(ops)
        if normalized is None:
            return ToolResult(success=False, error="ops_required")
        if dry_run:
            if isinstance(doc_id, str) and doc_id.strip():
                return self._dry_run_bound(doc_id.strip(), normalized)
            if isinstance(file_path, str) and file_path.strip():
                return self._dry_run_by_path(file_path.strip(), normalized)
            return ToolResult(success=False, error="doc_id_or_file_path_required")
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
        # plan 3.4 自校验回读：编辑成功后回读受管文档摘要（解析失败→不加键，
        # 保持原 {document_id, doc_type, results} 形状不变；self_check 只含
        # 计数事实，不回显受管绝对路径）。
        content = dict(result.get("content") or {})
        edited_id = content.get("document_id")
        doc_type_value = content.get("doc_type")
        if isinstance(edited_id, str) and isinstance(doc_type_value, str):
            self_check = self._managed_self_check(ctx, edited_id, doc_type_value)
            if self_check is not None:
                content["self_check"] = self_check
                # N4 (round-3) 自检历史：受管 update 落一行（best-effort，
                # 失败由 helper 自吞，绝不影响主结果）。
                record(
                    edited_id,
                    "update",
                    bool(self_check.get("ok")),
                    self_check.get("summary"),
                    conn=conn,
                )
        return ToolResult(success=True, content=content)

    def _managed_self_check(
        self,
        ctx: ToolExecutionContext,
        doc_id: str,
        doc_type: str,
    ) -> Optional[Dict[str, Any]]:
        """doc_id 模式的 self_check：binding 内解析受管文档后回读。

        binding 过期 / doc 消失 / DB 异常 → ``None``（不附加 self_check
        键，主结果不变——best-effort 语义）。
        """
        try:
            conn = get_database().get_connection()
            binding = get_active_workspace(
                conn, ctx.session_id, expected_generation=ctx.binding_generation
            )
        except Exception:  # noqa: BLE001 — DB 层异常按「无法回读」折叠
            return None
        if binding is None:
            return None
        return managed_self_check(conn, binding.workspace_path, doc_id, doc_type)

    # ── dry_run 模式：只读预览（diff_preview 在临时副本上试跑） ──────

    def _dry_run_bound(self, doc_id: str, ops: List[Dict[str, Any]]) -> ToolResult:
        """dry_run + doc_id：与正式路径同构地解析受管文档，但不写盘。

        解析语义与 ``OfficeToolService._resolve_doc`` 一致（binding 有效 +
        ``get_document_in_workspace``，归档/跨工作区/未知 id 折叠为
        ``document_not_found``），解析不到目标文件时绝不退化为预览。
        """
        ctx = current_tool_context()
        if ctx is None or not ctx.session_id:
            return ToolResult(success=False, error="missing_tool_context")
        try:
            conn = get_database().get_connection()
            binding = get_active_workspace(
                conn, ctx.session_id, expected_generation=ctx.binding_generation
            )
        except Exception:  # noqa: BLE001 — DB 层异常按「文档不存在」折叠
            return ToolResult(success=False, error="document_not_found")
        doc = (
            get_document_in_workspace(conn, doc_id, binding.workspace_path)
            if binding is not None
            else None
        )
        if doc is None:
            return ToolResult(success=False, error="document_not_found")
        return self._dry_run_result(document_path(doc), ops)

    def _dry_run_by_path(self, file_path: str, ops: List[Dict[str, Any]]) -> ToolResult:
        """dry_run + file_path：复用正式路径的全部定位守卫，但不写盘。"""
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
            validate_supported_filename(path.name, _DOC_TYPE_ENUM[doc_type])
        except Exception:
            return ToolResult(success=False, error="invalid_filename")
        if not path.is_file():
            return ToolResult(success=False, error="file_not_found")
        return self._dry_run_result(path, ops)

    def _dry_run_result(self, path: Path, ops: List[Dict[str, Any]]) -> ToolResult:
        """跑只读预览并折算成 ToolResult（源文件零写入）。

        预览失败（非法 op / 不可读文件）→ 标准 ``success=False`` 错误形状，
        error 里带上 preview 的人类可读原因。
        """
        try:
            preview = preview_update(path, ops)
        except Exception as exc:  # noqa: BLE001 — preview 异常折算为失败
            return ToolResult(success=False, error=f"preview_failed: {exc}")
        if not preview.ok:
            return ToolResult(
                success=False,
                error=f"preview_failed: {preview.error or 'one or more ops failed'}",
            )
        return ToolResult(
            success=True,
            content={
                "dry_run": True,
                "changes": [change.model_dump() for change in preview.changes],
                "truncated": preview.truncated,
            },
        )

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
        # plan 3.4 自校验回读：编辑成功后回读摘要（best-effort，失败也得
        # 到 {ok: False} 占位，主结果保持 success）。
        self_check = build_self_check(doc_type, path, requested=ops)
        # N4 (round-3) 自检历史：file_path 模式无受管 doc row，行记在 ""
        # （纯审计；dry_run 预览路径不落历史）。
        record(
            "",
            "update",
            bool(self_check.get("ok")),
            self_check.get("summary"),
        )
        return ToolResult(
            success=True,
            content={
                "path": str(path.resolve()),
                "filename": path.name,
                "bytes": path.stat().st_size,
                "results": results,
                "self_check": self_check,
            },
        )


__all__ = ["OfficeUpdateTool"]
