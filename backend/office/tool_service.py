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
    .create(conn, session_id, binding_generation, *,
            doc_type, filename, content) -> dict
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.domain.tool_policy import ToolPolicy
from backend.office.errors import OfficeContentShapeError, OfficeError
from backend.office.models import (
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
    OfficeExcelGenerateRequest,
    OfficePptGenerateRequest,
    OfficeWordGenerateRequest,
)
from backend.office.session_workspace import (
    get_active_workspace,
    get_document_in_workspace,
    get_document_in_workspace_any_status,
)
from backend.office.storage import (
    archive_document,
    delete_document,
    document_path,
    list_documents,
    restore_document,
    save_document,
    snapshot_pre_edit,
)

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


def _update_document(
    doc_type: str, path: Path, ops: List[Dict[str, Any]]
) -> tuple:
    """Deferred import of the editor dispatcher (mirrors the reader pattern).

    Importing :mod:`backend.office.edit` pulls in python-docx/openpyxl/
    python-pptx depending on doc_type; deferring keeps a broken optional
    dependency from breaking unrelated code paths at import time.
    """
    from backend.office.edit import update_document

    return update_document(doc_type, path, ops)


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

    # ──────────────────────────────────────────────────────────────
    # create (T7.5 round-trip)
    # ──────────────────────────────────────────────────────────────

    def create(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        binding_generation: int,
        *,
        doc_type: str,
        filename: str,
        content: Any,
    ) -> Dict[str, Any]:
        """Generate + register a new Office document under the bound workspace.

        Steps:
            1. Re-verify the session-workspace binding.
            2. Mint a ``doc_id`` and dispatch to the doc-type generator.
               The generator is told the binding's workspace_path so it
               lands at ``<workspace>/office/<doc_type>/<doc_id>/``
               (managed-document path, scoped to the binding).
            3. Persist a row in ``office_documents`` via :func:`save_document`
               so the new doc is visible to ``list`` / ``read``.
            4. Roll back the generated file if registration fails -- the
               filesystem must not carry orphan files the DB doesn't know
               about.

        Returns ``{success: True, content: {document_id, doc_type, filename}}``
        on success. The result payload deliberately drops the absolute
        ``workspace_path`` -- tool callers only need the handle trio.
        """
        binding = get_active_workspace(
            conn, session_id, expected_generation=binding_generation
        )
        if binding is None:
            return {
                "success": False,
                "error": {"code": "no_workspace_binding", "message": "no binding"},
            }

        # Normalize + validate doc_type. Generators accept OfficeDocType values;
        # the tool wrapper may pass user-supplied case ("Word") which we fold.
        try:
            normalized_doc_type = OfficeDocType(doc_type.lower())
        except ValueError:
            return {
                "success": False,
                "error": {"code": "unsupported_doc_type", "message": str(doc_type)},
            }

        try:
            generated_path = _generate_managed_document(
                doc_type=normalized_doc_type,
                doc_id="unused",  # generator mints its own; we read from path
                filename=filename,
                content=content,
                workspace_path=binding.workspace_path,
            )
        except OfficeContentShapeError as exc:
            return {
                "success": False,
                "error": {"code": "content_shape_invalid", "message": str(exc)},
            }
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return {
                "success": False,
                "error": {"code": "generation_failed", "message": str(exc)},
            }

        # Recover the doc_id the generator minted. Managed layout is
        # ``<workspace>/office/<doc_type>/<doc_id>/`` so the
        # parent directory's basename IS the doc_id.
        doc_id = generated_path.parent.name

        # Register the document. Status is GENERATED (created from scratch,
        # not parsed from an upload). Original filename is None -- the
        # "original" slot is reserved for uploaded files.
        try:
            now_ms = int(time.time() * 1000)
            canonical_workspace = str(Path(binding.workspace_path).resolve())
            summary = OfficeDocumentSummary(
                id=doc_id,
                workspace_path=canonical_workspace,
                doc_type=normalized_doc_type,
                original_filename=None,
                generated_filename=generated_path.name,
                status=OfficeDocStatus.GENERATED,
                created_at=now_ms,
                updated_at=now_ms,
                metadata=OfficeDocumentMetadata(
                    file_size_bytes=generated_path.stat().st_size,
                ),
            )
            save_document(conn, summary)
        except Exception as exc:  # noqa: BLE001 -- rollback must catch all
            # Best-effort rollback: drop the file the generator wrote so the
            # workspace doesn't accumulate orphan files the DB doesn't track.
            with contextlib.suppress(OSError):
                generated_path.unlink(missing_ok=True)
            return {
                "success": False,
                "error": {
                    "code": "registration_failed",
                    "message": str(exc),
                },
            }

        return {
            "success": True,
            "content": {
                "document_id": doc_id,
                "doc_type": normalized_doc_type.value,
                "filename": filename,
            },
        }

    # ──────────────────────────────────────────────────────────────
    # update (改 — 原地编辑)
    # ──────────────────────────────────────────────────────────────

    def update(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        binding_generation: int,
        doc_id: str,
        ops: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Apply in-place edits to a workspace-managed document.

        Steps:
            1. Re-verify the session-workspace binding + resolve the doc
               (stale / revoked / archived all collapse to not-found).
            2. Apply the same ``max_read_bytes`` disk cap as ``read`` —
               editing loads the whole file too.
            3. Dispatch to :mod:`backend.office.edit`; the editor is
               all-or-nothing (a failed op leaves the file untouched).
            4. On success, refresh the DB row: status → EDITED,
               ``updated_at`` → now, ``file_size_bytes`` → new size.

        The absolute workspace path never appears in the returned dict.
        """
        doc = self._resolve_doc(conn, session_id, binding_generation, doc_id)
        if doc is None:
            return _not_found()

        path = document_path(doc)
        try:
            if path.is_file() and path.stat().st_size > self._policy.max_read_bytes:
                return {
                    "success": False,
                    "error": {
                        "code": "file_too_large",
                        "message": "file exceeds edit cap",
                        "max_read_bytes": self._policy.max_read_bytes,
                    },
                }
            # PR-2: pre-edit snapshot — capture the bytes that the editor
            # is about to overwrite. Best-effort: a snapshot failure must
            # never block the user's edit (edit is the primary intent).
            snapshot_pre_edit(doc)
            saved, results = _update_document(doc.doc_type.value, path, ops)
        except OfficeError as exc:
            return {
                "success": False,
                "error": {"code": "update_failed", "message": str(exc)},
            }
        except Exception as exc:  # noqa: BLE001 — 编辑器未归类异常按失败处理
            return {
                "success": False,
                "error": {"code": "update_failed", "message": str(exc)},
            }

        if not saved:
            return {
                "success": False,
                "error": {"code": "operation_failed", "message": "one or more ops failed"},
                "results": results,
            }

        self._mark_edited(conn, doc, path)
        return {
            "success": True,
            "content": {
                "document_id": doc.id,
                "doc_type": doc.doc_type.value,
                "results": results,
            },
        }

    def _mark_edited(
        self,
        conn: sqlite3.Connection,
        doc: OfficeDocumentSummary,
        path: Path,
    ) -> None:
        """Persist the post-edit state: EDITED status + fresh size/mtime."""
        try:
            doc.status = OfficeDocStatus.EDITED
            doc.updated_at = int(time.time() * 1000)
            doc.metadata.file_size_bytes = path.stat().st_size
            save_document(conn, doc)
        except Exception:  # noqa: BLE001 — 文件已改成功，登记失败只记日志
            logger.warning("office edit applied but DB refresh failed: doc=%s", doc.id)

    # ──────────────────────────────────────────────────────────────
    # delete (删 — 整文件删除)
    # ──────────────────────────────────────────────────────────────

    def delete(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        binding_generation: int,
        doc_id: str,
    ) -> Dict[str, Any]:
        """Delete a workspace-managed document (DB row + managed directory).

        Order matters: the managed directory is removed **first**; only
        on success does the DB row go away. A locked file (Word holding
        it open) therefore keeps a consistent row+file state and surfaces
        ``delete_failed`` instead of orphaning files.
        """
        doc = self._resolve_doc(conn, session_id, binding_generation, doc_id)
        if doc is None:
            return _not_found()

        managed_dir = document_path(doc).parent
        if managed_dir.is_dir():
            import shutil

            try:
                shutil.rmtree(managed_dir)
            except OSError as exc:
                return {
                    "success": False,
                    "error": {"code": "delete_failed", "message": str(exc)},
                }

        delete_document(conn, doc.id)
        return {
            "success": True,
            "content": {"document_id": doc.id, "doc_type": doc.doc_type.value},
        }

    # ──────────────────────────────────────────────────────────────
    # archive / restore (PR-2: soft-delete lifecycle)
    # ──────────────────────────────────────────────────────────────

    def archive(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        binding_generation: int,
        doc_id: str,
    ) -> Dict[str, Any]:
        """Soft-delete a workspace-managed document.

        Sets ``office_documents.archived_at`` to the current ms epoch so
        the row hides from the default ``list`` view but stays recoverable
        via ``restore``. Idempotent: re-archiving an already-archived doc
        is a success (the timestamp is preserved — re-archiving a doc
        intentionally does NOT bump the timestamp).

        Returns the canonical ``document_not_found`` for unknown / stale /
        cross-workspace ids, identical to other read/write methods — no
        path leak to the LLM tool output.
        """
        # Archive deliberately uses the any-status lookup: an archived doc
        # must still be reachable so the idempotent re-archive path can
        # return the existing timestamp. Read/write paths still hide
        # archived docs via the standard ``get_document_in_workspace``.
        binding = get_active_workspace(
            conn, session_id, expected_generation=binding_generation
        )
        if binding is None:
            return _not_found()
        doc = get_document_in_workspace_any_status(conn, doc_id, binding.workspace_path)
        if doc is None:
            return _not_found()

        if doc.archived_at is not None:
            # Idempotent: already archived → return the existing timestamp
            # so the caller can display "archived since ..." without a
            # second list round-trip.
            return {
                "success": True,
                "content": {
                    "document_id": doc.id,
                    "was_archived": True,
                    "archived_at": doc.archived_at,
                },
            }

        # Compute the timestamp once and pass it down so the value echoed
        # back to the LLM matches the value persisted to SQLite exactly
        # (avoids sub-millisecond drift between two separate ``time.time()``
        # calls in the same request).
        now_ms = int(time.time() * 1000)
        ok = archive_document(conn, doc.id, now_ms=now_ms)
        if not ok:
            # Row vanished between _resolve_doc and the UPDATE (concurrent
            # delete from another request) → indistinguishable not-found.
            return _not_found()

        return {
            "success": True,
            "content": {
                "document_id": doc.id,
                "was_archived": True,
                "archived_at": now_ms,
            },
        }

    def restore(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        binding_generation: int,
        doc_id: str,
    ) -> Dict[str, Any]:
        """Un-archive a workspace-managed document (live again).

        Clears ``office_documents.archived_at`` so the row reappears in
        the default ``list`` view. Idempotent: restoring a live doc
        returns success without bumping ``updated_at`` (the doc state is
        already what the caller wants).

        Returns the canonical ``document_not_found`` for unknown / stale /
        cross-workspace ids, identical to other methods.
        """
        # Restore uses the any-status lookup too: the whole point is to
        # find a doc whose ``archived_at`` is currently set and clear it.
        binding = get_active_workspace(
            conn, session_id, expected_generation=binding_generation
        )
        if binding is None:
            return _not_found()
        doc = get_document_in_workspace_any_status(conn, doc_id, binding.workspace_path)
        if doc is None:
            return _not_found()

        if doc.archived_at is None:
            # Idempotent: already live → report success without rewriting.
            return {
                "success": True,
                "content": {
                    "document_id": doc.id,
                    "was_archived": False,
                },
            }

        ok = restore_document(conn, doc.id)
        if not ok:
            return _not_found()

        return {
            "success": True,
            "content": {
                "document_id": doc.id,
                "was_archived": False,
            },
        }


def _generate_managed_document(
    *,
    doc_type: OfficeDocType,
    doc_id: str,
    filename: str,
    content: Any,
    workspace_path: str,
) -> Any:  # Path on success
    """Dispatch to the right generator and return the on-disk path.

    Each generator accepts ``output_dir=None`` to mean "use the managed
    per-doc layout under ``workspace_path/office/<doc_type>/<doc_id>/``".
    The workspace path travels on the request object itself so request
    models stay self-contained.
    """
    if doc_type is OfficeDocType.WORD:
        from backend.office.word import generate_docx

        req = _coerce_word_request(doc_id, filename, content, workspace_path)
        return generate_docx(req, output_dir=None)
    if doc_type is OfficeDocType.EXCEL:
        from backend.office.excel import generate_xlsx

        req = _coerce_excel_request(doc_id, filename, content, workspace_path)
        return generate_xlsx(req, output_dir=None)
    if doc_type is OfficeDocType.PPT:
        from backend.office.ppt import generate_ppt

        req = _coerce_ppt_request(doc_id, filename, content, workspace_path)
        return generate_ppt(req, output_dir=None)
    raise ValueError(f"unsupported doc_type: {doc_type}")


def _coerce_word_request(
    doc_id: str, filename: str, content: Any, workspace_path: str
) -> OfficeWordGenerateRequest:
    """Build an OfficeWordGenerateRequest from the LLM-facing ``content``.

    Accepts either:
        * ``str`` — wrap as a single Title-less paragraph (mirrors the
          OfficeCreateTool "writing a sentence" case).
        * ``dict`` — must contain ``title`` (optional) + ``paragraphs`` /
          ``tables`` (optional). Empty dict → single empty paragraph.

    NB: the request model has no ``document_id`` field — the generator
    mints a fresh UUID internally when ``output_dir=None``. The ``doc_id``
    we want to bind to the DB row is recovered from the resulting
    on-disk path (``file_path.parent.name``).
    """
    if isinstance(content, str):
        return OfficeWordGenerateRequest(
            workspace_path=workspace_path,
            filename=filename,
            title=filename,
            paragraphs=[{"text": content}],
        )
    if not isinstance(content, dict):
        raise TypeError("word content must be str or dict")
    title = content.get("title") or filename
    paragraphs = content.get("paragraphs") or [{"text": ""}]
    tables = content.get("tables") or []
    return OfficeWordGenerateRequest(
        workspace_path=workspace_path,
        filename=filename,
        title=title,
        paragraphs=paragraphs,
        tables=tables,
    )


def _coerce_excel_request(
    doc_id: str, filename: str, content: Any, workspace_path: str
) -> OfficeExcelGenerateRequest:
    if not isinstance(content, dict) or not content.get("sheets"):
        raise OfficeContentShapeError(
            "excel content 需要形如 {'sheets': [{'name', 'headers', 'rows'}]} 的对象"
        )
    return OfficeExcelGenerateRequest(
        workspace_path=workspace_path,
        filename=filename,
        sheets=content["sheets"],
    )


def _coerce_ppt_request(
    doc_id: str, filename: str, content: Any, workspace_path: str
) -> OfficePptGenerateRequest:
    if not isinstance(content, dict) or not content.get("slides"):
        raise OfficeContentShapeError(
            "ppt content 需要形如 {'slides': [{'title', 'bullets', 'notes'}]} 的对象"
        )
    # OfficePptGenerateRequest 是 extra="forbid" 且没有 title 字段 —— 传 title 会
    # ValidationError, 这是 PR #405 前每次 ppt 创建都失败的原因。
    return OfficePptGenerateRequest(
        workspace_path=workspace_path,
        filename=filename,
        slides=content["slides"],
    )


def _not_found() -> Dict[str, Any]:
    """Canonical 'not found' response -- identical for unknown, archived,
    stale-generation, and cross-workspace lookups.
    """
    return {
        "success": False,
        "error": {"code": "document_not_found", "message": "document not found"},
    }


__all__ = ["OfficeToolService"]
