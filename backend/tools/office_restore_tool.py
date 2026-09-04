# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Office restore tool for the LLM tool loop (Office CRUD 的「还原」).

``office_restore`` is the inverse of ``office_archive``: it clears
``office_documents.archived_at`` so a previously soft-deleted document
reappears in the default ``office_list`` view. Locate by ``doc_id``
(from ``office_list`` with ``include_archived=True`` or any future
archive-management UI). No file_path mode — restore operates on the
canonical managed row only.

Restore is non-destructive (the on-disk file was never removed by
``office_archive``) and idempotent (re-restoring a live doc is a no-op
success). The WRITE_LOCAL risk class routes the call through the
permission engine's mode gate (逐次审批 in restrictive modes) so
unarchiving a doc still counts as a state change.
"""

from __future__ import annotations

from typing import Any, Optional

from backend.data.database import get_database
from backend.domain.risk import RiskClass
from backend.office.tool_service import OfficeToolService
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.context import current_tool_context


class OfficeRestoreTool(BaseTool):
    """Restore a previously archived Office document (by doc_id)."""

    requires_tool_context = True
    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_restore",
            description=(
                "Restore (un-archive) a previously archived Office "
                "document so it reappears in office_list. Locate by "
                "doc_id (from office_list with include_archived=True, or "
                "from any prior archive operation). The on-disk file is "
                "kept intact -- office_archive only sets a soft-delete "
                "timestamp; restore clears that timestamp. Pairs with "
                "office_archive: archive to hide a doc without losing "
                "the bytes, restore to bring it back. Combine with "
                "office_update to undo an edit via the pre-edit snapshot "
                "(snapshots live under <managed_dir>/.snapshots/)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "description": (
                            "Document id from office_list (include_archived=True) "
                            "or from any prior archive operation. Required."
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
            result = service.restore(conn, ctx.session_id, ctx.binding_generation, doc_id)
        except Exception:
            return ToolResult(success=False, error="restore_failed")
        if not result.get("success"):
            err = result.get("error") or {}
            return ToolResult(success=False, error=str(err.get("code") or "restore_failed"))
        return ToolResult(success=True, content=result.get("content"))


__all__ = ["OfficeRestoreTool"]
