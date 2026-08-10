"""ReviewQueue: SQLite-backed async review event queue with background worker."""
import asyncio
import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ReviewEvent:
    """A single review event pulled from the queue."""

    id: int
    trigger_type: str
    session_id: str
    context: dict
    status: str
    created_at: int


class ReviewQueue:
    """SQLite-backed queue with a single background worker thread.

    Enqueue is thread-safe. The worker dequeues pending events one at a time,
    calls _process_event(), then marks the event done or failed.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.worker_thread: Optional[threading.Thread] = None
        self.running: bool = False
        self._wake: threading.Event = threading.Event()
        # Optional collaborators — injected by the bootstrap layer
        # (see Task 7 brief). When either is None, _process_event
        # degrades to a no-op with an error log.
        self.review_service: object = None  # ReviewService (late import)
        self.draft_store: object = None  # SkillDraftStore (late import)
        self._initialize_db()

    # ------------------------------------------------------------------ #
    # Database initialization
    # ------------------------------------------------------------------ #

    def _initialize_db(self) -> None:
        """Create the review_events table if it doesn't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS review_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trigger_type TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    context TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at INTEGER NOT NULL,
                    processed_at INTEGER,
                    error_message TEXT
                )
                """
            )

    # ------------------------------------------------------------------ #
    # Enqueue / Dequeue
    # ------------------------------------------------------------------ #

    def enqueue(self, trigger_type: str, session_id: str, context: dict) -> None:
        """Thread-safe enqueue of a new review event.

        Degrades gracefully on DB errors — logs and returns without
        blocking the caller (review is best-effort).
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """INSERT INTO review_events
                       (trigger_type, session_id, context, status, created_at)
                       VALUES (?, ?, ?, 'pending', ?)""",
                    (
                        trigger_type,
                        session_id,
                        json.dumps(context),
                        int(time.time() * 1000),
                    ),
                )
            logger.info("Enqueued review event: %s", trigger_type)
            self._wake.set()  # Wake the worker
        except sqlite3.Error as e:
            logger.error("Failed to enqueue review event: %s", e)

    def _dequeue_next(self) -> Optional[ReviewEvent]:
        """Pop the oldest pending event and mark it 'processing'.

        Returns None if the queue is empty.

        NOTE: This uses a separate SELECT + UPDATE (not SELECT ... FOR UPDATE)
        which is a TOCTOU race in multi-worker scenarios. This is safe because
        ReviewQueue is designed for a single background worker thread — only
        one consumer ever calls _dequeue_next(). If multi-worker support is
        added in the future, this must be replaced with an atomic
        SELECT-and-UPDATE pattern (e.g. UPDATE ... RETURNING or a transaction
        with row-level locking).
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """SELECT id, trigger_type, session_id, context, status, created_at
                   FROM review_events
                   WHERE status = 'pending'
                   ORDER BY created_at ASC, id ASC
                   LIMIT 1"""
            )
            row = cursor.fetchone()
            if not row:
                return None

            event_id, trigger_type, session_id, context_json, status, created_at = row
            conn.execute(
                "UPDATE review_events SET status = 'processing' WHERE id = ?",
                (event_id,),
            )
            return ReviewEvent(
                id=event_id,
                trigger_type=trigger_type,
                session_id=session_id,
                context=json.loads(context_json),
                status="processing",
                created_at=created_at,
            )

    # ------------------------------------------------------------------ #
    # Event status transitions
    # ------------------------------------------------------------------ #

    def _mark_done(self, event_id: int) -> None:
        """Mark an event as successfully processed."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE review_events
                   SET status = 'done', processed_at = ?
                   WHERE id = ?""",
                (int(time.time() * 1000), event_id),
            )

    def _mark_failed(self, event_id: int, error_message: str) -> None:
        """Mark an event as failed with an error message."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE review_events
                   SET status = 'failed', processed_at = ?, error_message = ?
                   WHERE id = ?""",
                (int(time.time() * 1000), error_message, event_id),
            )

    # ------------------------------------------------------------------ #
    # Worker lifecycle
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Start the background worker thread. Idempotent."""
        if self.worker_thread and self.worker_thread.is_alive():
            return
        self.running = True
        self._wake = threading.Event()
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()
        logger.info("ReviewQueue worker started")

    def stop(self, drain: bool = False) -> None:
        """Stop the background worker thread.

        Args:
            drain: If True, process all remaining pending events after the
                   worker has exited. Runs single-threaded to avoid concurrent
                   DB access with the worker.
        """
        self.running = False
        self._wake.set()  # Wake the worker so it can exit
        if self.worker_thread:
            self.worker_thread.join(timeout=5)
            if self.worker_thread.is_alive():
                logger.warning(
                    "ReviewQueue worker did not exit within 5s; "
                    "skipping drain to avoid concurrent DB access"
                )
                drain = False
        if drain:
            # Worker is confirmed dead — safe to access DB without concurrency
            while True:
                event = self._dequeue_next()
                if event is None:
                    break
                try:
                    self._process_event(event)
                    self._mark_done(event.id)
                except Exception as e:
                    logger.error("Drain: review processing failed: %s", e)
                    self._mark_failed(event.id, str(e))
        logger.info("ReviewQueue worker stopped")

    def _worker_loop(self) -> None:
        """Background worker loop: dequeue → process → mark done/failed."""
        while self.running:
            event = self._dequeue_next()
            if event is not None:
                try:
                    self._process_event(event)
                    self._mark_done(event.id)
                except Exception as e:
                    logger.error("Review processing failed: %s", e)
                    self._mark_failed(event.id, str(e))
            else:
                self._wake.clear()
                self._wake.wait(timeout=1.0)

    def _process_event(self, event: ReviewEvent) -> None:
        """Process a review event by calling ReviewService and storing the draft.

        Calls ``ReviewService.generate_draft()`` (async) to produce a
        ``SkillDraft``, then persists it via ``SkillDraftStore.insert()``.

        Raises:
            Any exception raised by the LLM provider or the draft store
            propagates unchanged — the caller (_worker_loop) is
            responsible for marking the event as failed.
        """
        if not self.review_service or not self.draft_store:
            logger.error(
                "ReviewService or SkillDraftStore not configured; "
                "skipping event %s",
                event.trigger_type,
            )
            return

        logger.info("Processing review event: %s", event.trigger_type)

        # Merge event-level session_id into the context dict so that
        # ReviewService.generate_draft() can populate
        # SkillDraft.source_session_id correctly.
        enriched_context = dict(event.context)
        enriched_context.setdefault("session_id", event.session_id)

        # fix/security-perf-quickwins (2026-08-09, §1.3a d): for explicit_learn
        # triggers the route only enqueues an empty messages=[] placeholder
        # (route-side keeps the API surface small; we don't want to ship N
        # message rows in the request body). Load the conversation history
        # here from MessageRepository so the LLM prompt template actually
        # has something to summarize. Other trigger types (e.g. complex_turn)
        # only need tool-call metadata, so we don't load messages for them.
        if (
            event.trigger_type == "explicit_learn"
            and not enriched_context.get("messages")
        ):
            try:
                from backend.data.session_repo import MessageRepository

                message_repo = MessageRepository()
                db_messages = message_repo.get_by_session(event.session_id)
                # Serialize to {role, content} dicts — ReviewService dumps the
                # whole context as JSON into the prompt template, so anything
                # we put here is visible to the LLM.
                enriched_context["messages"] = [
                    {"role": m.role, "content": m.content} for m in db_messages
                ]
                logger.info(
                    "Loaded %d message(s) for session %s (explicit_learn)",
                    len(db_messages),
                    event.session_id,
                )
            except Exception as exc:  # noqa: BLE001 - best-effort, do not break the worker
                # Fall through with whatever messages were enqueued (empty list
                # in current callers). The LLM will get low-quality context but
                # the worker must stay alive and keep draining the queue.
                logger.warning(
                    "Failed to load messages for session %s: %s",
                    event.session_id,
                    exc,
                )

        # generate_draft is async; run it in a one-shot event loop
        # from the sync worker thread.
        draft = asyncio.run(
            self.review_service.generate_draft(
                trigger_type=event.trigger_type,
                context=enriched_context,
            )
        )

        self.draft_store.insert(draft)
        logger.info("Created skill draft: %s (id=%s)", draft.name, draft.id)


# ------------------------------------------------------------------ #
# Global singleton (same pattern as get_usage_store)
# ------------------------------------------------------------------ #

_review_queue: Optional[ReviewQueue] = None


def get_review_queue(db_path: Optional[str] = None) -> ReviewQueue:
    """Return the global ReviewQueue singleton.

    Args:
        db_path: Database path for the queue.  Only used on first call
            when creating the singleton.  Subsequent calls ignore this
            parameter and return the existing instance.
    """
    global _review_queue
    if _review_queue is None:
        if db_path is None:
            # Default: colocate with the main application database
            import os

            from backend.data.database import get_database

            db = get_database()
            db_path = getattr(db, "db_path", None) or os.path.join(
                os.path.dirname(__file__), "..", "data", "sage.db"
            )
        _review_queue = ReviewQueue(db_path)
    return _review_queue


def reset_review_queue() -> None:
    """Reset the global ReviewQueue singleton (test only)."""
    global _review_queue
    if _review_queue is not None:
        _review_queue.stop()
    _review_queue = None
