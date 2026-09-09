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
"""

from __future__ import annotations

from typing import Any, Optional

from backend.data.database import get_database
from backend.domain.risk import RiskClass
from backend.office.tool_service import OfficeToolService
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.context import current_tool_context


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
        return ToolResult(success=True, content=result.get("content"))


__all__ = ["OfficeArchiveTool"]
