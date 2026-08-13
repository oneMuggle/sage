"""Scoped Office document service for LLM tool calls (Task 9).

``OfficeToolService`` is the authorization + policy layer that sits between
the tool wrappers (``OfficeListTool`` / ``OfficeReadTool``) and the underlying
storage + reader modules. Every method:

1. Re-checks the session-workspace binding via
   :func:`backend.office.session_workspace.get_active_workspace` with
   ``expected_generation=`` so a revoked / rebound / mismatched binding
   produces the same empty / not-found result as a genuinely empty
   workspace (indistinguishable failure -> no path leak).
2. Applies :class:`backend.domain.tool_policy.ToolPolicy` caps
   (``max_result_items``, ``max_output_bytes``).
3. Strips the binding's absolute ``workspace_path`` from any returned dict
   so the LLM-facing payload never echoes filesystem layout.

Public surface:

    OfficeToolService(policy=None)
    .list(conn, session_id, binding_generation, query=None,
          doc_type=None, limit=50) -> List[dict]
    .read(conn, session_id, binding_generation, doc_id,
          section="summary") -> dict
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional

from backend.domain.tool_policy import ToolPolicy
from backend.office.models import OfficeDocType, OfficeDocumentSummary
from backend.office.session_workspace import (
    get_active_workspace,
    get_document_in_workspace,
)
from backend.office.storage import document_path, list_documents

import logging

logger = logging.getLogger(__name__)

# Reader imports are deferred per doc_type so a broken optional dependency
# (python-pptx / python-docx / openpyxl) does not crash the whole module
# at import time. Each reader function is imported only on the code path
# that needs it.


def _serialize_summary(summary: OfficeDocumentSummary) -> Dict[str, Any]:
    """Convert a Pydantic summary to a JSON-safe dict, dropping workspace_path.

    ``workspace_path`` is the binding's canonical absolute directory. It must
    never reach the LLM tool output; callers only need the doc id / type /
    filename to decide whether to read the document.
    """
    data = summary.model_dump(mode="json")
    data.pop("workspace_path", None)
    return data


def _read_doc(doc: OfficeDocumentSummary) -> Dict[str, Any]:
    """Dispatch to the appropriate reader and return a JSON-safe dict.

    Raises:
        OSError: the on-disk file is missing or unreadable. The tool
            wrapper converts this to a safe ``read_failed`` error code.
    """
    path = document_path(doc)
    if not path.is_file():
        raise OSError(f"office file missing on disk: {doc.id}")
    doc_type = doc.doc_type
    if doc_type is OfficeDocType.PPT:
        from backend.office.ppt import read_ppt

        result = read_ppt(
            path,
            document_id=doc.id,
            workspace_path=doc.workspace_path,
            generated_filename=doc.generated_filename,
            original_filename=doc.original_filename,
        )
        return result.model_dump(mode="json")
    if doc_type is OfficeDocType.WORD:
        from backend.office.word import read_docx

        result = read_docx(
            path,
            document_id=doc.id,
            workspace_path=doc.workspace_path,
            generated_filename=doc.generated_filename,
            original_filename=doc.original_filename,
        )
        return result.model_dump(mode="json")
    if doc_type is OfficeDocType.EXCEL:
        from backend.office.excel import read_xlsx

        result = read_xlsx(
            path,
            document_id=doc.id,
            workspace_path=doc.workspace_path,
            generated_filename=doc.generated_filename,
            original_filename=doc.original_filename,
        )
        return result.model_dump(mode="json")
    raise ValueError(f"unsupported doc_type: {doc_type}")


def _strip_workspace_path_from_read_result(data: Dict[str, Any]) -> Dict[str, Any]:
    """Walk the read-result dict and remove any nested ``workspace_path`` keys.

    The reader returns a top-level ``summary`` that carries the binding's
    canonical workspace path; we must redact it before handing the result
    back to the LLM tool wrapper.
    """
    summary = data.get("summary")
    if isinstance(summary, dict):
        summary.pop("workspace_path", None)
    return data


def _truncate_to_byte_cap(data: Dict[str, Any], max_bytes: int) -> Dict[str, Any]:
    """Serialize ``data`` to JSON and truncate to ``max_bytes`` UTF-8 bytes.

    Returns a dict with:
        ``truncated``: True (the caller knows the output was bounded)
        ``head``: the truncated JSON string (valid UTF-8 prefix)
        ``max_output_bytes``: echo of the cap for auditability
    """
    serialized = json.dumps(data, ensure_ascii=False, default=str)
    raw = serialized.encode("utf-8")
    if len(raw) <= max_bytes:
        return {**data, "truncated": False}
    # Truncate bytes, then decode with ``errors="ignore"`` so we never
    # emit a partial multi-byte UTF-8 character.
    head_bytes = raw[:max_bytes]
    head = head_bytes.decode("utf-8", errors="ignore")
    return {
        "truncated": True,
        "max_output_bytes": max_bytes,
        "head": head,
    }


class OfficeToolService:
    """Scoped read/list over the active session-workspace binding.

    Construct once per process (or per request); the service is stateless
    apart from the injected :class:`ToolPolicy`. Connection + session ids
    are passed per call so the same instance can serve multiple requests.
    """

    def __init__(self, policy: Optional[ToolPolicy] = None) -> None:
        self._policy = policy or ToolPolicy()

    # ──────────────────────────────────────────────────────────────
    # list
    # ──────────────────────────────────────────────────────────────

    def list(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        binding_generation: int,
        query: Optional[str] = None,
        doc_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Return a bounded, workspace-scoped list of live Office documents.

        Returns an empty list (not an error) for revoked / mismatched
        bindings so the tool output does not leak filesystem state.
        """
        binding = get_active_workspace(
            conn, session_id, expected_generation=binding_generation
        )
        if binding is None:
            return []

        docs = list_documents(conn, binding.workspace_path, include_archived=False)

        # Apply caller-supplied filters. ``query`` matches case-insensitively
        # against both the user-visible original filename and the on-disk
        # generated filename so partial recollections ("meeting" for
        # "MeetingNotes.docx") still land.
        if query:
            needle = query.strip().casefold()
            if needle:
                docs = [
                    d
                    for d in docs
                    if needle in (d.original_filename or "").casefold()
                    or needle in (d.generated_filename or "").casefold()
                ]
        if doc_type:
            docs = [d for d in docs if d.doc_type.value == doc_type]

        # Apply the stricter of caller limit and policy cap.
        effective_limit = min(limit, self._policy.max_result_items)
        docs = docs[:effective_limit]

        return [_serialize_summary(d) for d in docs]

    # ──────────────────────────────────────────────────────────────
    # read
    # ──────────────────────────────────────────────────────────────

    def _read_content(self, doc: OfficeDocumentSummary) -> Dict[str, Any]:
        """Read the document body, applying ``max_read_bytes`` cap.

        Returns either:
            ``{"ok": True, "data": <parsed dict>}`` on success, or
            ``{"ok": False, "error": {...}}`` on failure (file too large,
            missing on disk, parser error).
        """
        # Disk-read cap. Applied before invoking the parser so absurdly
        # large Office files (a 50MB .pptx might yield only 100KB of text,
        # but the parse itself is expensive) are rejected early.
        try:
            on_disk_path = document_path(doc)
            if on_disk_path.is_file():
                file_size = on_disk_path.stat().st_size
                if file_size > self._policy.max_read_bytes:
                    return {
                        "ok": False,
                        "error": {
                            "code": "file_too_large",
                            "message": "file exceeds read cap",
                            "max_read_bytes": self._policy.max_read_bytes,
                        },
                    }
        except OSError:
            pass  # Fall through to _read_doc which handles missing files.

        try:
            full = _read_doc(doc)
        except (OSError, Exception):
            return {
                "ok": False,
                "error": {"code": "read_failed", "message": "file unreadable"},
            }

        _strip_workspace_path_from_read_result(full)
        return {"ok": True, "data": full}

    def _resolve_doc(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        binding_generation: int,
        doc_id: str,
    ) -> Optional[OfficeDocumentSummary]:
        """Re-verify the binding and look up the document.

        Returns ``None`` when the binding is stale, revoked, or the
        document is missing / archived / cross-workspace -- callers treat
        this uniformly as ``document_not_found``.
        """
        binding = get_active_workspace(
            conn, session_id, expected_generation=binding_generation
        )
        if binding is None:
            return None
        return get_document_in_workspace(conn, doc_id, binding.workspace_path)

    def read(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        binding_generation: int,
        doc_id: str,
        section: str = "summary",
    ) -> Dict[str, Any]:
        """Read a single Office document with bounded output.

        ``section`` is one of:
            ``"summary"`` -- return only the summary dict (no content body).
            ``"head"``    -- return summary + the first ``max_output_bytes``
                            of the serialized content.
            ``"all"``     -- return summary + full content; if it exceeds
                            ``max_output_bytes``, degrade to bounded head
                            with ``truncated=True``.

        Failures (unknown doc, archived, stale generation, missing file)
        all collapse to the same ``document_not_found`` / ``read_failed``
        error shape so the tool output never distinguishes "denied" from
        "absent".
        """
        doc = self._resolve_doc(conn, session_id, binding_generation, doc_id)
        if doc is None:
            return _not_found()

        if section == "summary":
            return {
                "success": True,
                "content": {"summary": _serialize_summary(doc)},
            }

        content = self._read_content(doc)
        if not content["ok"]:
            return {"success": False, "error": content["error"]}

        full = content["data"]
        if section == "head":
            bounded = _truncate_to_byte_cap(full, self._policy.max_output_bytes)
            return {"success": True, "content": bounded}

        # section == "all" (or any unknown value falls through to "all")
        serialized_size = len(
            json.dumps(full, ensure_ascii=False, default=str).encode("utf-8")
        )
        if serialized_size <= self._policy.max_output_bytes:
            return {"success": True, "content": full}
        # Degrade to bounded head so the tool output stays within budget.
        bounded = _truncate_to_byte_cap(full, self._policy.max_output_bytes)
        return {"success": True, "content": bounded}


def _not_found() -> Dict[str, Any]:
    """Canonical 'not found' response -- identical for unknown, archived,
    stale-generation, and cross-workspace lookups.
    """
    return {
        "success": False,
        "error": {"code": "document_not_found", "message": "document not found"},
    }


__all__ = ["OfficeToolService"]
