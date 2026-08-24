"""SessionSummary — 会话级压缩摘要持久化（批次三 step 3-4）。

This module owns one table (``session_summaries``) and one store
(:class:`SessionSummaryStore`). It exists separately from
:mod:`backend.memory.episodic` on purpose: a session summary is *not*
an ordinary fact, it's a derived artifact generated from the working
context. Mixing the two would let callers mistake a summary for a fact,
which is exactly what spec §4.3 step 4 forbids ("不伪装为普通事实").

Contract (spec 2026-08-23-win7-parity-platform-fixes-design.md §4.3):

    SessionSummary {
      id: string
      session_id: string
      source_turn_id: string | null
      content: string
      created_at_ms: integer
      updated_at_ms: integer
      status: "pending" | "ready" | "failed"
    }

Plus ``error_message: string | null`` (spec step 4: failed summaries
MUST retain their diagnostic so callers can surface a structured
failure instead of pretending the LLM produced a real fact).

Design rules baked into the API:

* ``status`` is CHECK-constrained at the SQL level and revalidated at
  the Python boundary so an in-memory store can't drift from the
  schema.
* All timestamps are epoch milliseconds, UTC, with the ``_ms`` suffix
  per spec §4.4 (no naive datetimes leak into persistence).
* Different sessions cannot cross-inject summaries — every read path
  takes ``session_id`` as a required filter.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from backend.data.database import Database

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Public constants (spec §4.3 step 3 status enum)
# ──────────────────────────────────────────────────────────────────────

PENDING = "pending"
READY = "ready"
FAILED = "failed"

_VALID_STATUSES = frozenset({PENDING, READY, FAILED})


class SummaryStatusError(ValueError):
    """Raised when a status value is not in {pending, ready, failed}."""


def _now_ms() -> int:
    """Epoch milliseconds — UTC instant per spec §4.4 step 1."""
    return int(time.time() * 1000)


def _validate_status(status: str) -> str:
    if status not in _VALID_STATUSES:
        raise SummaryStatusError(
            f"invalid session_summary status: {status!r} "
            f"(expected one of {sorted(_VALID_STATUSES)})"
        )
    return status


# ──────────────────────────────────────────────────────────────────────
# Dataclass
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SessionSummary:
    """Typed row representation for the ``session_summaries`` table."""

    id: str
    session_id: str
    source_turn_id: Optional[str]
    content: str
    created_at_ms: int
    updated_at_ms: int
    status: str
    error_message: Optional[str]


def _row_to_summary(row: sqlite3.Row) -> SessionSummary:
    return SessionSummary(
        id=row["id"],
        session_id=row["session_id"],
        source_turn_id=row["source_turn_id"],
        content=row["content"] or "",
        created_at_ms=int(row["created_at_ms"]),
        updated_at_ms=int(row["updated_at_ms"]),
        status=row["status"],
        error_message=row["error_message"],
    )


# ──────────────────────────────────────────────────────────────────────
# Store
# ──────────────────────────────────────────────────────────────────────


class SessionSummaryStore:
    """CRUD wrapper for the ``session_summaries`` table.

    Keep all SQL in one place so the rest of the codebase can treat
    summaries as plain dataclasses and so the session-isolation
    invariant (step 5: different sessions don't cross-inject) is easy
    to audit.
    """

    def __init__(self, db: Database):
        self.db = db

    # ── create ─────────────────────────────────────────────────────────

    def create(
        self,
        session_id: str,
        content: str,
        status: str = PENDING,
        source_turn_id: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> SessionSummary:
        """Insert a new summary row. The caller picks ``status`` — use
        :data:`PENDING` when the row is a placeholder waiting on the
        LLM, :data:`READY` when content is final, :data:`FAILED` when
        generation crashed (and supply ``error_message`` so the
        diagnostic survives).
        """
        if not session_id:
            raise ValueError("session_id is required")
        status = _validate_status(status)
        # A READY row without actual content would be a silent lie.
        if status == READY and not content:
            raise ValueError("READY summary requires non-empty content")
        # A FAILED row without a diagnostic would be useless to callers.
        if status == FAILED and not error_message:
            raise ValueError("FAILED summary requires error_message")

        now = _now_ms()
        summary_id = uuid.uuid4().hex

        cursor = self.db.get_connection().cursor()
        cursor.execute(
            """
            INSERT INTO session_summaries (
                id, session_id, source_turn_id, content,
                created_at_ms, updated_at_ms, status, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                summary_id,
                session_id,
                source_turn_id,
                content,
                now,
                now,
                status,
                error_message,
            ),
        )
        self.db.get_connection().commit()

        logger.debug(
            "session_summary created: id=%s session=%s status=%s",
            summary_id, session_id, status,
        )

        return SessionSummary(
            id=summary_id,
            session_id=session_id,
            source_turn_id=source_turn_id,
            content=content,
            created_at_ms=now,
            updated_at_ms=now,
            status=status,
            error_message=error_message,
        )

    # ── read ───────────────────────────────────────────────────────────

    def get_by_id(self, summary_id: str) -> Optional[SessionSummary]:
        cursor = self.db.get_connection().cursor()
        row = cursor.execute(
            "SELECT * FROM session_summaries WHERE id = ?", (summary_id,)
        ).fetchone()
        return _row_to_summary(row) if row is not None else None

    def get_latest_ready(self, session_id: str) -> Optional[SessionSummary]:
        """Most recent READY summary for ``session_id``, or ``None``.

        Used by the retrieval-priority layer (step 5) to inject the
        bound session's summary without leaking summaries from other
        sessions. FAILED / PENDING rows are deliberately excluded so a
        failed generation never masquerades as a successful one.
        """
        cursor = self.db.get_connection().cursor()
        row = cursor.execute(
            """
            SELECT * FROM session_summaries
            WHERE session_id = ? AND status = ?
            ORDER BY created_at_ms DESC
            LIMIT 1
            """,
            (session_id, READY),
        ).fetchone()
        return _row_to_summary(row) if row is not None else None

    # ── update ─────────────────────────────────────────────────────────

    def update(
        self,
        pending_id: str,
        content: str,
        status: str,
        error_message: Optional[str] = None,
    ) -> Optional[SessionSummary]:
        """Promote a PENDING row to READY / FAILED after the LLM call.

        只允许更新 ``status='pending'`` 的行:这是 spec §4.3 step 4
        "不重写已落定的诊断" 的实现约束。READY / FAILED 行一旦写入,
        其 ``error_message`` / ``content`` 即视为终态,后续重试不能
        偷偷改写(否则多个并发生成会互相覆盖)。

        Returns the refreshed row, or ``None`` when ``pending_id`` was
        never created or already left PENDING (caller can log + ignore;
        no exception is raised because the generation pipeline expects
        "missing/already-settled → just skip").
        """
        status = _validate_status(status)
        if status == READY and not content:
            raise ValueError("READY summary requires non-empty content")
        if status == FAILED and not error_message:
            raise ValueError("FAILED summary requires error_message")

        now = _now_ms()
        cursor = self.db.get_connection().cursor()
        cursor.execute(
            """
            UPDATE session_summaries
            SET content = ?, status = ?, error_message = ?, updated_at_ms = ?
            WHERE id = ? AND status = ?
            """,
            (content, status, error_message, now, pending_id, PENDING),
        )
        self.db.get_connection().commit()

        if cursor.rowcount == 0:
            return None

        refreshed = self.get_by_id(pending_id)
        logger.debug(
            "session_summary updated: id=%s status=%s", pending_id, status
        )
        return refreshed


# ──────────────────────────────────────────────────────────────────────
# Module-level query helpers (used by retrieval + Memory UI)
# ──────────────────────────────────────────────────────────────────────


def list_summaries_for_session(
    db: Database,
    session_id: str,
    limit: int = 20,
) -> List[SessionSummary]:
    """Return summaries for ``session_id``, newest first.

    Always filter by ``session_id`` — different sessions MUST NOT
    cross-inject summaries (spec §4.3 step 5).
    """
    cursor = db.get_connection().cursor()
    rows = cursor.execute(
        """
        SELECT * FROM session_summaries
        WHERE session_id = ?
        ORDER BY created_at_ms DESC
        LIMIT ?
        """,
        (session_id, max(1, int(limit))),
    ).fetchall()
    return [_row_to_summary(r) for r in rows]


# ──────────────────────────────────────────────────────────────────────
# Generation hook (spec §4.3 step 4)
# ──────────────────────────────────────────────────────────────────────


def generate_summary(
    messages: List[Dict[str, Any]],
    llm_call: Any,
) -> str:
    """Synchronous hook that turns working-context messages into a single
    summary string. Wraps ``llm_call`` so the caller doesn't have to
    know the LLM client shape; exceptions propagate so the caller can
    route them to the failed-status branch (rather than
    catch-and-retry-into-episodic, which is exactly what spec §4.3 step 4
    forbids).
    """
    payload = [
        {"role": m["role"], "content": m["content"]}
        for m in messages
    ]
    return llm_call(payload, 0.0)


def persist_summary(
    store: SessionSummaryStore,
    session_id: str,
    source_turn_id: Optional[str],
    content: str,
    status: str = READY,
    error_message: Optional[str] = None,
) -> SessionSummary:
    """Persist a single summary row through :class:`SessionSummaryStore`.

    Happy path: ``status=READY`` with non-empty content.
    Failure path: ``status=FAILED`` with a diagnostic ``error_message``
    so callers can distinguish "LLM genuinely returned nothing" from
    "summary generation crashed".
    """
    return store.create(
        session_id=session_id,
        content=content,
        status=status,
        source_turn_id=source_turn_id,
        error_message=error_message,
    )


def _redact_error_message(raw: str) -> str:
    """脱敏错误消息:截断 URL / 长 key / 绝对路径,避免把生产环境
    凭证或路径写入持久化的 ``session_summaries`` 行（spec §4.4 step 5
    "不向生产环境数据写入日志/诊断"）。

    仅保留 ``{ExceptionClass}: <safe>`` 这种结构化前缀,长度上限 200 字符。
    """
    if not raw:
        return ""
    text = str(raw)
    # 去掉 http(s) URL
    text = re.sub(r"https?://[^\s)\]]+", "<url>", text)
    # 去掉绝对路径（包含 / 或 \ 或 ~ 的长串）
    text = re.sub(r"(/|\\|~)[A-Za-z0-9_./\\-]{8,}", "<path>", text)
    # 去掉疑似长 key / token（连续 24+ 位 [A-Za-z0-9_-]）
    text = re.sub(r"[A-Za-z0-9_\-]{24,}", "<redacted>", text)
    # 截断总长度
    return text[:200]


def generate_and_persist_summary(
    store: SessionSummaryStore,
    session_id: str,
    messages: List[Dict[str, Any]],
    llm_call: Any,
    source_turn_id: Optional[str] = None,
) -> SessionSummary:
    """End-to-end hook: generate via the LLM and persist a row.

    Spec §4.3 step 4 enforces two invariants:

    1. A failed summary MUST preserve its diagnostic so callers can
       distinguish "LLM genuinely returned nothing" from "summary
       generation crashed" — never pretend failure is success.
    2. The summary MUST NEVER be silently re-saved as a generic
       episodic fact. A summary is a derived artifact; mixing it with
       ordinary facts would let downstream code surface it as a real
       memory, which is the exact spec §4.3 step 4 violation we are
       guarding against.

    Outcomes:

    * LLM returns non-empty content → READY row.
    * LLM returns empty / garbage → FAILED row with
      "LLM returned empty summary".
    * LLM raises any exception → FAILED row carrying
      ``"{ExceptionClass}: {message}"``.
    """
    try:
        content = generate_summary(messages, llm_call)
    except Exception as exc:
        return persist_summary(
            store=store,
            session_id=session_id,
            source_turn_id=source_turn_id,
            content="",
            status=FAILED,
            error_message=_redact_error_message(
                f"{type(exc).__name__}: {exc}"
            ),
        )

    if not content or not content.strip():
        return persist_summary(
            store=store,
            session_id=session_id,
            source_turn_id=source_turn_id,
            content="",
            status=FAILED,
            error_message=_redact_error_message(
                "LLM returned empty summary"
            ),
        )

    return persist_summary(
        store=store,
        session_id=session_id,
        source_turn_id=source_turn_id,
        content=content,
        status=READY,
    )


__all__ = [
    "FAILED",
    "PENDING",
    "READY",
    "SessionSummary",
    "SessionSummaryStore",
    "SummaryStatusError",
    "generate_and_persist_summary",
    "generate_summary",
    "list_summaries_for_session",
    "persist_summary",
]
