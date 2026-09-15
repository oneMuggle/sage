# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Office self-check history (round-3 Office parity, item N4).

Every Office write path that already builds a self-check readback
(``build_self_check`` / ``managed_self_check`` / ``workspace_count_self_check``)
appends one audit row to the ``office_self_checks`` table, so the document
detail view can replay the verification timeline: created → edited → applied
→ archived → restored, each with the counts the model/user saw at the time.

Design rules (contract, fixed for the routes/frontend consumers):

* :func:`record` is **best-effort** — the whole body runs inside its own
  try/except and NEVER propagates. A missing table (legacy DB that has not
  been re-initialized), a locked/closed connection, an unserializable
  summary — all degrade to a debug log line; the caller's write always wins.
* :func:`list_for_document` is the read side (used by
  ``GET /office/doc/{id}/self-checks``): newest first, ``summary`` returned
  as the deserialized dict.
* Schema lives in ``backend.data.database.init_db`` (additive, idempotent —
  same ``CREATE TABLE IF NOT EXISTS`` pattern as ``office_documents``):

    office_self_checks(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        doc_id TEXT NOT NULL,
        action TEXT NOT NULL,
        ok INTEGER NOT NULL,
        summary TEXT,
        created_at INTEGER NOT NULL
    )  + index (doc_id, created_at)

* Layering: this module lives in the connection-agnostic office layer, so
  ``backend.data.database`` is imported lazily inside :func:`record` (only
  when the caller did not pass a connection) — office → tools must never
  happen at module load, and office → data is kept call-time-only too.
* Unmanaged writes (``office_create``/``office_update`` with ``output_dir``/
  ``file_path``) have no managed doc row; their rows are recorded under
  ``""`` as a pure audit trail that managed-document history queries never
  match.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = ["VALID_ACTIONS", "list_for_document", "record"]

#: action 域（记录用；不做硬校验——审计写入永远不能因新增 action 而失败）。
VALID_ACTIONS = frozenset(
    {"create", "update", "apply", "archive", "restore", "snapshot_restore"}
)


def record(
    doc_id: str,
    action: str,
    ok: bool,
    summary: Optional[dict],
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    """Best-effort append of one self-check history row.

    Args:
        doc_id: Managed document id. Unmanaged writes (legacy output_dir /
            file_path paths) pass ``""`` — the row is pure audit trail.
        action: One of :data:`VALID_ACTIONS` (not enforced).
        ok: Whether the self-check readback reported success.
        summary: The ``self_check["summary"]`` dict; JSON-serialized here
            (``ensure_ascii=False``). ``None`` is stored as SQL NULL.
        conn: Caller's connection (the office layer is connection-agnostic).
            ``None`` → resolve the global ``get_database()`` connection at
            call time.

    Never raises: any failure (missing table, DB closed, unserializable
    summary, ...) is swallowed and logged at debug level — history must
    never break the write that produced it.
    """
    try:
        if conn is None:
            from backend.data.database import get_database

            conn = get_database().get_connection()
        summary_json: Optional[str] = None
        if summary is not None:
            summary_json = json.dumps(summary, ensure_ascii=False)
        conn.execute(
            "INSERT INTO office_self_checks "
            "(doc_id, action, ok, summary, created_at) VALUES (?, ?, ?, ?, ?)",
            (doc_id, action, 1 if ok else 0, summary_json, int(time.time() * 1000)),
        )
        conn.commit()
    except Exception as exc:  # noqa: BLE001 — best-effort 历史，绝不打断调用方
        logger.debug(
            "office_self_checks: record(doc_id=%s, action=%s) skipped: %s",
            doc_id,
            action,
            type(exc).__name__,
        )


def list_for_document(
    conn: sqlite3.Connection,
    doc_id: str,
    limit: int = 50,
) -> List[dict]:
    """Self-check history rows for ``doc_id``, newest first.

    Returns:
        List of ``{id, doc_id, action, ok, summary, created_at}`` dicts;
        ``ok`` is a real bool, ``summary`` is the deserialized dict (or
        ``None`` when absent/unparseable), ``created_at`` is the ms epoch.
        Column access is positional so both raw ``sqlite3.Connection`` and
        the row-factory-backed Database proxy work.
    """
    rows = conn.execute(
        "SELECT id, doc_id, action, ok, summary, created_at "
        "FROM office_self_checks WHERE doc_id = ? "
        "ORDER BY created_at DESC, id DESC LIMIT ?",
        (doc_id, limit),
    ).fetchall()
    items: List[Dict[str, Any]] = []
    for row in rows:
        raw_summary = row[4]
        summary: Any = None
        if raw_summary is not None:
            try:
                summary = json.loads(raw_summary)
            except (TypeError, ValueError):
                summary = None
        items.append(
            {
                "id": row[0],
                "doc_id": row[1],
                "action": row[2],
                "ok": bool(row[3]),
                "summary": summary,
                "created_at": row[5],
            }
        )
    return items
