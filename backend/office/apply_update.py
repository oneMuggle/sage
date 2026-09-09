# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Apply update ops to a managed office document (Office parity round 2 — R1).

The batch-2 edit-preview dialog (:http:post:`/office/update/preview`) can
only show what WOULD change; this module backs the 「应用」 step:

    POST /office/doc/{doc_id}/update   body: {"ops": [...]}

Semantics (mirrors the office_update tool path in
``OfficeToolService.update`` + ``office_update_tool``):

1. Resolve the doc row (route does 404 via ``_require_document``) and its
   managed file via :func:`backend.office.storage.document_path`; the file
   must exist on disk.
2. Take the pre-edit snapshot FIRST — same best-effort
   :func:`backend.office.storage.snapshot_pre_edit` call the tool path
   uses, so the edit can be reverted even if it later fails halfway.
3. Apply ops via :func:`backend.office.edit.update_document` (dispatches
   docx/xlsx/pptx by ``doc_type``). The editor is all-or-nothing: a failed
   op leaves the on-disk file untouched.
4. Rejected ops raise :class:`OfficeOpRejectedError` with per-op failure
   info in the message. It subclasses BOTH ``OfficeContentShapeError``
   (→ 422 via the existing ``office_error_to_http_status`` branch, checked
   before the write-failure branch) and ``OfficeEditError`` (rejected ops
   are edit failures from the caller's point of view), so no errors.py
   change was needed to get the 422 mapping.
5. On success persist the row refresh — status → EDITED, ``updated_at``
   → now, ``metadata.file_size_bytes`` → fresh size — by mutating the
   fetched summary in place and ``save_document``-ing it, exactly like
   ``OfficeToolService._mark_edited`` (archived_at / derived_from /
   original_filename ride along because the summary came from
   ``get_document``; DB refresh failure is logged, not raised — the edit
   itself already succeeded).
6. Attach the self-check readback (``build_self_check`` from the tools
   layer, imported lazily: tools imports office, never the reverse at
   module load). Best-effort — a readback failure degrades to
   ``{"ok": False, ...}`` without failing the request.

Request/response models live here (not models.py) because models.py is
owned by another agent this round — same pattern as diff_preview.py in
batch 2.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field

from .edit import update_document
from .errors import OfficeContentShapeError, OfficeEditError, OfficeFileNotFoundError
from .models import OfficeDocStatus, OfficeDocumentSummary
from .selfcheck_history import record
from .storage import document_path, save_document, snapshot_pre_edit

logger = logging.getLogger(__name__)

__all__ = [
    "OfficeDocUpdateRequest",
    "OfficeDocUpdateResult",
    "OfficeOpRejectedError",
    "apply_doc_update",
]


class OfficeOpRejectedError(OfficeContentShapeError, OfficeEditError):
    """One or more update ops were rejected by the editor.

    Deliberate double inheritance:

    * ``OfficeContentShapeError`` first in the MRO so
      :func:`backend.office.errors.office_error_to_http_status` hits its
      422 branch before the ``OfficeEditError`` → 500 write-failure branch
      — rejected ops are a client-input problem (the preview dialog
      already showed them as invalid), not a server write failure.
    * ``OfficeEditError`` keeps the "edit went wrong" lineage so callers
      (and tests) can catch the edit-layer base class.

    File-level save failures still raise plain ``OfficeEditError`` → 500.
    """


class OfficeDocUpdateRequest(BaseModel):
    """POST /office/doc/{doc_id}/update request body."""

    model_config = ConfigDict(extra="forbid")

    ops: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Same op dicts the office_update tool accepts (word/excel/ppt)",
    )


class OfficeDocUpdateResult(BaseModel):
    """POST /office/doc/{doc_id}/update response."""

    model_config = ConfigDict(extra="forbid")

    ok: bool = Field(description="True when every op applied and the file was saved")
    summary: OfficeDocumentSummary = Field(
        description="Refreshed document row (status=edited, fresh updated_at/size)"
    )
    self_check: Dict[str, Any] = Field(
        description=(
            "Post-edit readback: {ok, summary:{paragraph_count, ...}} per doc "
            "type; {ok: False, error} when the readback failed (best-effort)"
        )
    )
    results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Per-op outcomes from backend.office.edit ({op, ok, ...})",
    )


def _rejection_message(per_op_results: List[Dict[str, Any]]) -> str:
    """Human-readable message for the first rejected op (+ not-applied count)."""
    failed = [r for r in per_op_results if isinstance(r, dict) and not r.get("ok", True)]
    if not failed:
        return "one or more ops failed"
    first = failed[0]
    message = f"op {first.get('op')} rejected: {first.get('error')}"
    not_applied = sum(
        1 for r in failed if str(r.get("error", "")).startswith("not_applied")
    )
    if not_applied:
        message += f"; {not_applied} op(s) not applied"
    return message


def _self_check(doc_type: str, path: Path, ops: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Best-effort post-edit readback (mirrors office_update_tool's attachment).

    The import is deferred: the tools layer imports the office layer at
    module level, so office → tools must only ever happen at call time.
    """
    try:
        from backend.tools.office_create_tool import build_self_check

        return build_self_check(doc_type, path, requested=ops)
    except Exception as exc:  # noqa: BLE001 — 回读失败不令主结果失败
        logger.warning("self-check readback failed: %s", type(exc).__name__)
        return {"ok": False, "error": f"readback_failed: {type(exc).__name__}"}


def apply_doc_update(
    conn: sqlite3.Connection,
    doc: OfficeDocumentSummary,
    ops: List[Dict[str, Any]],
) -> OfficeDocUpdateResult:
    """Apply ``ops`` to ``doc``'s managed file and persist the edited state.

    Raises:
        OfficeFileNotFoundError: the managed file is missing on disk.
        OfficeEditError: file-level save failure (file left untouched).
        OfficeOpRejectedError: at least one op was rejected (422-mapped,
            per-op failure info in the message; file left untouched).
    """
    file_path = document_path(doc)
    if not file_path.is_file():
        raise OfficeFileNotFoundError(file_path)

    # Pre-edit snapshot FIRST — same call the office_update tool path makes,
    # best-effort: a failed snapshot must never block the user's edit.
    snapshot_pre_edit(doc)

    saved, per_op_results = update_document(doc.doc_type.value, file_path, ops)
    if not saved:
        raise OfficeOpRejectedError(
            _rejection_message(per_op_results), file_path=file_path
        )

    # Mirror OfficeToolService._mark_edited: mutate the fetched summary in
    # place (archived_at / derived_from / original_filename ride along) and
    # INSERT OR REPLACE it. DB refresh failure is logged, not raised — the
    # edit itself already succeeded.
    try:
        doc.status = OfficeDocStatus.EDITED
        doc.updated_at = int(time.time() * 1000)
        doc.metadata.file_size_bytes = file_path.stat().st_size
        save_document(conn, doc)
    except Exception:  # noqa: BLE001 — 文件已改成功，登记失败只记日志
        logger.warning("office edit applied but DB refresh failed: doc=%s", doc.id)

    self_check = _self_check(doc.doc_type.value, file_path, ops)
    # N4 (round-3) 自检历史：apply 落一行（best-effort，失败由 helper
    # 自吞——编辑本身已成功，历史绝不令请求失败）。
    record(doc.id, "apply", bool(self_check.get("ok")), self_check.get("summary"), conn=conn)
    return OfficeDocUpdateResult(
        ok=True,
        summary=doc,
        self_check=self_check,
        results=per_op_results,
    )
