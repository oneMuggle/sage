# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Office delete tool for the LLM tool loop (Office CRUD 的「删」).

``office_delete`` removes an existing Word / Excel / PPT document. Two
locating modes:

1. **doc_id mode** — ``doc_id`` (from ``office_list``) resolves through
   the active session-workspace binding via ``OfficeToolService.delete``:
   the managed directory (``<workspace>/office/<type>/<id>/``) and the
   ``office_documents`` row are removed together, files-first so a
   locked file keeps a consistent row+file state.
2. **file_path mode** — an absolute path to a single office file.
   Restricted to ``.docx/.xlsx/.pptx`` so the tool can never delete an
   arbitrary file the way ``bash rm`` could; outside-workspace targets
   are gated by the same approval chain as ``office_create``
   (``make_office_path_boundary``) and the hex-chain
   ``_enforce_workspace``.

Deletion is destructive; the WRITE_LOCAL risk class routes both modes
through the permission engine's mode gate (逐次审批 in restrictive
modes).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from backend.data.database import get_database
from backend.domain.risk import RiskClass
from backend.office.tool_service import OfficeToolService
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.context import current_tool_context

#: file_path 模式允许删除的扩展名（与 office_update 的可编辑范围一致）
_DELETABLE_EXTENSIONS = frozenset({".docx", ".xlsx", ".pptx"})


class OfficeDeleteTool(BaseTool):
    """Delete an existing Office document (by doc_id or absolute path)."""

    requires_tool_context = False
    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_delete",
            description=(
                "Delete an existing Office document (.docx/.xlsx/.pptx). "
                "This is DESTRUCTIVE and cannot be undone. Locate the file "
                "either by doc_id (from office_list, uses the active chat "
                "workspace and removes the managed copy + its registration) "
                "or by absolute file_path (deletes that single file; only "
                "office extensions are allowed). Confirm with the user "
                "before deleting a file they did not explicitly ask to "
                "remove."
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
                            "file to delete (when no doc_id)."
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
        if isinstance(doc_id, str) and doc_id.strip():
            return self._execute_bound(doc_id.strip())
        if isinstance(file_path, str) and file_path.strip():
            return self._execute_by_path(file_path.strip())
        return ToolResult(success=False, error="doc_id_or_file_path_required")

    # ── doc_id 模式：走 service（授权 + DB 行与文件一并删除） ────────

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
            result = service.delete(conn, ctx.session_id, ctx.binding_generation, doc_id)
        except Exception:
            return ToolResult(success=False, error="delete_failed")
        if not result.get("success"):
            err = result.get("error") or {}
            return ToolResult(success=False, error=str(err.get("code") or "delete_failed"))
        return ToolResult(success=True, content=result.get("content"))

    # ── file_path 模式：删除单个 office 文件 ─────────────────────────

    def _execute_by_path(self, file_path: str) -> ToolResult:
        blocked = self._enforce_workspace(file_path)
        if blocked is not None:
            return blocked
        path = Path(file_path).expanduser()
        if not path.is_absolute():
            return ToolResult(
                success=False,
                error="file_path_absolute_required: 请传绝对路径",
            )
        if path.suffix.lower() not in _DELETABLE_EXTENSIONS:
            return ToolResult(
                success=False,
                error="unsupported_file_type: 仅允许删除 .docx/.xlsx/.pptx",
            )
        if not path.is_file():
            return ToolResult(success=False, error="file_not_found")
        try:
            path.unlink()
        except OSError as exc:
            return ToolResult(success=False, error=f"delete_failed: {exc}")
        return ToolResult(
            success=True,
            content={"path": str(path.resolve()), "deleted": True},
        )


__all__ = ["OfficeDeleteTool"]
