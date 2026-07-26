"""Office list + read tool wrappers for the LLM tool loop (Task 9).

These are thin adapters that:

1. Set ``requires_tool_context = True`` so the registry hides them from
   the LLM schema list when there is no active ``ToolExecutionContext``.
2. Check ``current_tool_context()`` at the top of ``execute()`` and fail
   closed with ``missing_tool_context`` when the producer did not set
   one (defence in depth -- the registry already hides the schema, but a
   stale tool call could still reach ``execute()``).
3. Pull the session id + binding generation from the context and delegate
   to :class:`backend.office.tool_service.OfficeToolService` for the
   actual scoped read.

The schemas intentionally expose NO ``path`` / ``workspace_path`` /
``file_path`` parameter -- the LLM only sees ``doc_id``, ``section``,
``query``, ``doc_type`` and ``limit``. The binding's workspace path is
derived from the context (captured at authorization time in the producer)
and never re-supplied by the model.

Public surface:

    OfficeListTool(policy=None)   # name="office_list"
    OfficeReadTool(policy=None)   # name="office_read"
"""

from __future__ import annotations

from typing import Any, Optional

from backend.data.database import get_database
from backend.office.tool_service import OfficeToolService
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.context import current_tool_context


class OfficeListTool(BaseTool):
    """List Office documents visible to the current chat session.

    The LLM sees a bounded, workspace-scoped list; absolute workspace
    paths are stripped by :class:`OfficeToolService` before the result
    is returned.
    """

    requires_tool_context = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_list",
            description=(
                "List Office documents (ppt/word/excel) in the active "
                "chat workspace. Results are scoped to the current "
                "session's binding; documents from other workspaces or "
                "archived documents are not visible."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Optional case-insensitive substring filter "
                            "matched against document filenames."
                        ),
                    },
                    "doc_type": {
                        "type": "string",
                        "enum": ["ppt", "word", "excel"],
                        "description": "Optional document type filter.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": (
                            "Maximum number of results to return " "(default 50, capped by policy)."
                        ),
                        "default": 50,
                    },
                },
                "required": [],
            },
        )

    def execute(
        self,
        query: Optional[str] = None,
        doc_type: Optional[str] = None,
        limit: int = 50,
        **kwargs: Any,
    ) -> ToolResult:
        ctx = current_tool_context()
        if ctx is None:
            return ToolResult(success=False, error="missing_tool_context")

        service = OfficeToolService(policy=self._policy)
        try:
            conn = get_database().get_connection()
            items = service.list(
                conn,
                ctx.session_id,
                ctx.binding_generation,
                query=query,
                doc_type=doc_type,
                limit=limit,
            )
        except Exception:
            # Authorization / DB failures collapse to an empty list so
            # the tool output never distinguishes denied from absent.
            items = []

        return ToolResult(success=True, content={"items": items})


class OfficeReadTool(BaseTool):
    """Read a single Office document visible to the current chat session.

    ``section`` controls the output breadth:

    - ``"summary"`` -- metadata only (no content body).
    - ``"head"``    -- summary + the first ``max_output_bytes`` of content.
    - ``"all"``     -- summary + full content; degraded to bounded head
      with ``truncated=True`` when the serialized payload exceeds
      ``max_output_bytes``.
    """

    requires_tool_context = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_read",
            description=(
                "Read the contents of a single Office document in the "
                "active chat workspace. The document is identified by "
                "its id (from office_list); the workspace path is "
                "derived from the session binding and never supplied "
                "by the caller."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "description": "Document id returned by office_list.",
                    },
                    "section": {
                        "type": "string",
                        "enum": ["summary", "head", "all"],
                        "description": (
                            "'summary' = metadata only; 'head' = "
                            "metadata + bounded content prefix; "
                            "'all' = full content (may be truncated)."
                        ),
                        "default": "summary",
                    },
                },
                "required": ["doc_id"],
            },
        )

    def execute(
        self,
        doc_id: str,
        section: str = "summary",
        **kwargs: Any,
    ) -> ToolResult:
        ctx = current_tool_context()
        if ctx is None:
            return ToolResult(success=False, error="missing_tool_context")

        service = OfficeToolService(policy=self._policy)
        try:
            conn = get_database().get_connection()
            result = service.read(
                conn,
                ctx.session_id,
                ctx.binding_generation,
                doc_id,
                section=section,
            )
        except Exception:
            # Unexpected backend error: return a safe, non-leaking error.
            return ToolResult(
                success=False,
                error="read_failed",
            )

        if not result.get("success"):
            error = result.get("error", {})
            code = error.get("code", "read_failed")
            return ToolResult(success=False, error=code)

        return ToolResult(success=True, content=result.get("content"))


__all__ = ["OfficeListTool", "OfficeReadTool"]
