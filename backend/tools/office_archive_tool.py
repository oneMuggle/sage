# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Office archive tool for the LLM tool loop (Office CRUD 的「软删」).

``office_archive`` is the soft-delete companion to ``office_delete``: it
sets ``office_documents.archived_at`` to the current ms epoch so the row
hides from the default ``office_list`` view but stays recoverable via
``office_restore``. Locate by ``doc_id`` (from ``office_list``) only —
``file_path`` mode is reserved for the destructive ``office_delete``
because soft-delete + a single path lookup doesn't compose well
(managed rows own their on-disk bytes via session binding; ad-hoc
paths are not first-class documents).

Archive is non-destructive (the on-disk file is kept intact) and
idempotent (re-archiving an already-archived doc returns the existing
``archived_at`` timestamp without bumping it). The WRITE_LOCAL risk
class routes the call through the permission engine's mode gate
(逐次审批 in restrictive modes) so soft-deleting still counts as a
state change.

Round-2 R7 self-check readback: on success the result carries
``content["self_check"]`` — workspace-level archive counts (from
``storage.list_documents`` for the bound workspace) plus the touched
document's filename/doc_type. Best-effort: a failed readback degrades
to ``{ok: False, error}`` and never fails the tool result.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional

from backend.data.database import get_database
from backend.domain.risk import RiskClass
from backend.office.session_workspace import (
    get_active_workspace,
    get_document_in_workspace_any_status,
)
from backend.office.storage import list_documents
from backend.office.tool_service import OfficeToolService
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.context import ToolExecutionContext, current_tool_context


def workspace_count_self_check(
    conn: sqlite3.Connection,
    ctx: ToolExecutionContext,
    doc_id: str,
    count_key: str,
) -> Dict[str, Any]:
    """R7 archive/restore 共用的回读：绑定工作区计数 + 触达文档指纹。

    ``count_key``: ``"archived_count"``（office_archive 用）或
    ``"live_count"``（office_restore 用）。计数来自
    ``storage.list_documents``（绑定 workspace_path；archived = 全量 − 未归档）。
    document 只回 ``filename``（original_filename）/``doc_type``，不回绝对路径。
    尽力而为：任何异常/解析失败折算为 ``{ok: False, error}``，绝不抛出、
    绝不令主结果失败；返回值恒 < 1KB。
    """
    try:
        binding = get_active_workspace(
            conn, ctx.session_id, expected_generation=ctx.binding_generation
        )
        if binding is None:
            return {"ok": False, "error": "binding_unavailable"}
        doc = get_document_in_workspace_any_status(conn, doc_id, binding.workspace_path)
        if doc is None:
            return {"ok": False, "error": "document_unavailable"}
        total = len(list_documents(conn, binding.workspace_path, include_archived=True))
        live = len(list_documents(conn, binding.workspace_path, include_archived=False))
        counts = {"archived_count": total - live, "live_count": live}
        return {
            "ok": True,
            "summary": {
                count_key: counts.get(count_key, 0),
                "document": {
                    "filename": doc.original_filename,
                    "doc_type": doc.doc_type.value,
                },
            },
        }
    except Exception as exc:  # noqa: BLE001 — best-effort 回读，失败不阻断主结果
        return {"ok": False, "error": f"self_check_failed: {type(exc).__name__}"}


class OfficeArchiveTool(BaseTool):
    """Archive (soft-delete) an Office document (by doc_id)."""

    requires_tool_context = True
    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_archive",
            description=(
                "Archive (soft-delete) an Office document so it disappears "
                "from the default office_list view. Locate by doc_id "
                "(from office_list). The on-disk file is kept intact -- "
                "archive only sets a soft-delete timestamp. Pair with "
                "office_restore to bring the doc back; pair with "
                "office_delete for irreversible removal. Use this when "
                "you want to hide a doc temporarily without losing the "
                "bytes or breaking downstream references."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "description": (
                            "Document id from office_list. Required. "
                            "Takes precedence over any other mode."
                        ),
                    },
                },
                "required": ["doc_id"],
            },
        )

    def execute(
        self,
        doc_id: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        if not isinstance(doc_id, str) or not doc_id.strip():
            return ToolResult(success=False, error="doc_id_required")
        return self._execute_bound(doc_id.strip())

    def _execute_bound(self, doc_id: str) -> ToolResult:
        ctx = current_tool_context()
        if ctx is None or not ctx.session_id:
            return ToolResult(success=False, error="missing_tool_context")
        try:
            conn = get_database().get_connection()
        except Exception:
            return ToolResult(success=False, error="document_not_found")
        service = OfficeToolService(policy=self._policy)
        try:
            result = service.archive(conn, ctx.session_id, ctx.binding_generation, doc_id)
        except Exception:
            return ToolResult(success=False, error="archive_failed")
        if not result.get("success"):
            err = result.get("error") or {}
            return ToolResult(success=False, error=str(err.get("code") or "archive_failed"))
        # R7 自校验回读：工作区归档计数 + 触达文档指纹（best-effort，
        # 回读失败得到 {ok: False, error} 占位，主结果保持 success）。
        content = dict(result.get("content") or {})
        content["self_check"] = workspace_count_self_check(
            conn, ctx, doc_id, "archived_count"
        )
        return ToolResult(success=True, content=content)


__all__ = ["OfficeArchiveTool"]
