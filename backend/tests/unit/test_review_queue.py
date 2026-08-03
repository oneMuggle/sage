"""Tests for ReviewQueue with async worker and SQLite persistence."""
import os
import sqlite3
import tempfile
import threading
import time

import pytest

from backend.skills.review_queue import ReviewQueue


@pytest.fixture()
def db_path():
    """Create a temporary database file for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    if os.path.exists(path):
        os.unlink(path)


class TestEnqueueDequeue:
    """Tests for enqueue/dequeue roundtrip."""

    def test_enqueue_dequeue_roundtrip(self, db_path):
        """Enqueue an event, dequeue it, verify fields and status transition."""
        queue = ReviewQueue(db_path)

        queue.enqueue(
            trigger_type="complex_turn",
            session_id="session_1",
            context={"tool_calls": [{"tool": "read", "args": {"path": "/a"}}]},
        )

        event = queue._dequeue_next()

        assert event is not None
        assert event.trigger_type == "complex_turn"
        assert event.session_id == "session_1"
        assert event.status == "processing"
        assert event.context == {"tool_calls": [{"tool": "read", "args": {"path": "/a"}}]}

    def test_dequeue_empty_returns_none(self, db_path):
        """Dequeue from empty queue returns None."""
        queue = ReviewQueue(db_path)
        event = queue._dequeue_next()
        assert event is None

    def test_dequeue_fifo_order(self, db_path):
        """Events are dequeued in FIFO order (oldest first)."""
        queue = ReviewQueue(db_path)

        queue.enqueue(trigger_type="first", session_id="s1", context={})
        # Small sleep to ensure different timestamps
        time.sleep(0.01)
        queue.enqueue(trigger_type="second", session_id="s2", context={})

        event1 = queue._dequeue_next()
        event2 = queue._dequeue_next()
        event3 = queue._dequeue_next()

        assert event1 is not None
        assert event1.trigger_type == "first"
        assert event2 is not None
        assert event2.trigger_type == "second"
        assert event3 is None

    def test_dequeue_fifo_tie_breaker_by_id(self, db_path):
        """Events with identical created_at timestamps are ordered by id ASC."""
        queue = ReviewQueue(db_path)

        # Insert events with the same timestamp directly (bypassing time.time)
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """INSERT INTO review_events
                   (trigger_type, session_id, context, status, created_at)
                   VALUES (?, ?, ?, 'pending', ?)""",
                ("first", "s1", "{}", 1000000),
            )
            conn.execute(
                """INSERT INTO review_events
                   (trigger_type, session_id, context, status, created_at)
                   VALUES (?, ?, ?, 'pending', ?)""",
                ("second", "s2", "{}", 1000000),  # same timestamp
            )
            conn.execute(
                """INSERT INTO review_events
                   (trigger_type, session_id, context, status, created_at)
                   VALUES (?, ?, ?, 'pending', ?)""",
                ("third", "s3", "{}", 1000000),  # same timestamp
            )

        # All three have identical created_at; id ASC must break the tie
        event1 = queue._dequeue_next()
        event2 = queue._dequeue_next()
        event3 = queue._dequeue_next()

        assert event1.trigger_type == "first"
        assert event2.trigger_type == "second"
        assert event3.trigger_type == "third"
        # Verify ids are strictly ascending
        assert event1.id < event2.id < event3.id

    def test_dequeue_skips_processing_events(self, db_path):
        """Dequeue only returns pending events, not already-processing ones."""
        queue = ReviewQueue(db_path)

        queue.enqueue(trigger_type="first", session_id="s1", context={})
        queue.enqueue(trigger_type="second", session_id="s2", context={})

        # Dequeue first → becomes 'processing'
        event1 = queue._dequeue_next()
        assert event1.trigger_type == "first"

        # Next dequeue should return second, not first again
        event2 = queue._dequeue_next()
        assert event2 is not None
        assert event2.trigger_type == "second"


class TestMarkDoneFailed:
    """Tests for marking events as done or failed."""

    def test_mark_done(self, db_path):
        """Mark an event as done updates status and processed_at."""
        queue = ReviewQueue(db_path)
        queue.enqueue(trigger_type="test", session_id="s1", context={})
        event = queue._dequeue_next()

        queue._mark_done(event.id)

        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT status, processed_at FROM review_events WHERE id = ?",
                (event.id,),
            ).fetchone()
        assert row[0] == "done"
        assert row[1] is not None

    def test_mark_failed(self, db_path):
        """Mark an event as failed updates status, processed_at, and error_message."""
        queue = ReviewQueue(db_path)
        queue.enqueue(trigger_type="test", session_id="s1", context={})
        event = queue._dequeue_next()

        queue._mark_failed(event.id, "something broke")

        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT status, processed_at, error_message FROM review_events WHERE id = ?",
                (event.id,),
            ).fetchone()
        assert row[0] == "failed"
        assert row[1] is not None
        assert row[2] == "something broke"


class TestWorkerLifecycle:
    """Tests for worker thread start/stop."""

    def test_worker_lifecycle_start_stop(self, db_path):
        """Start creates a living thread, stop kills it."""
        queue = ReviewQueue(db_path)

        queue.start()
        assert queue.worker_thread is not None
        assert queue.worker_thread.is_alive()

        queue.stop()
        # Give thread a moment to exit
        time.sleep(0.1)
        assert not queue.worker_thread.is_alive()

    def test_start_idempotent(self, db_path):
        """Calling start twice doesn't create a second thread."""
        queue = ReviewQueue(db_path)

        queue.start()
        thread1 = queue.worker_thread
        queue.start()
        thread2 = queue.worker_thread

        assert thread1 is thread2
        queue.stop()

    def test_worker_processes_enqueued_event(self, db_path):
        """Worker picks up and processes an enqueued event."""
        queue = ReviewQueue(db_path)
        queue.start()

        try:
            queue.enqueue(trigger_type="auto_test", session_id="s1", context={})
            # Wait for worker to process
            time.sleep(0.5)

            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT status FROM review_events WHERE trigger_type = 'auto_test'"
                ).fetchone()
            assert row[0] == "done"
        finally:
            queue.stop()

    def test_worker_marks_failed_on_exception(self, db_path):
        """Worker marks event as failed if _process_event raises."""
        queue = ReviewQueue(db_path)

        # Override _process_event to raise
        def bad_process(event):
            raise RuntimeError("intentional test error")

        queue._process_event = bad_process
        queue.start()

        try:
            queue.enqueue(trigger_type="will_fail", session_id="s1", context={})
            time.sleep(0.5)

            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT status, error_message FROM review_events WHERE trigger_type = 'will_fail'"
                ).fetchone()
            assert row[0] == "failed"
            assert "intentional test error" in row[1]
        finally:
            queue.stop()


class TestDrain:
    """Tests for drain-on-stop behavior."""

    def test_stop_with_drain(self, db_path):
        """stop(drain=True) processes all pending events before stopping."""
        queue = ReviewQueue(db_path)
        # Enqueue events (no worker running yet since start hasn't been called)
        queue.enqueue(trigger_type="evt1", session_id="s1", context={})
        queue.enqueue(trigger_type="evt2", session_id="s2", context={})

        queue.start()
        queue.stop(drain=True)

        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT status FROM review_events ORDER BY id"
            ).fetchall()
        # Both should be done (processed by drain loop or worker)
        statuses = [r[0] for r in rows]
        assert all(s == "done" for s in statuses)

    def test_drain_without_worker(self, db_path):
        """stop(drain=True) without start() processes events via drain loop only.

        This exercises the drain code path directly — no worker thread exists,
        so all events must be processed by the drain loop in stop().
        """
        queue = ReviewQueue(db_path)
        # Enqueue events but NEVER call start() — no worker thread
        queue.enqueue(trigger_type="drain1", session_id="s1", context={})
        queue.enqueue(trigger_type="drain2", session_id="s2", context={})
        queue.enqueue(trigger_type="drain3", session_id="s3", context={})

        # worker_thread is None, so join() is skipped, drain=True enters loop
        queue.stop(drain=True)

        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT status FROM review_events ORDER BY id"
            ).fetchall()

        statuses = [r[0] for r in rows]
        assert len(statuses) == 3
        # All events processed by the drain loop
        assert all(s == "done" for s in statuses)


class TestThreadSafety:
    """Tests for thread-safe enqueue."""

    def test_concurrent_enqueue(self, db_path):
        """Multiple threads enqueuing simultaneously doesn't corrupt the queue."""
        queue = ReviewQueue(db_path)
        errors = []

        def enqueue_batch(prefix, count):
            try:
                for i in range(count):
                    queue.enqueue(
                        trigger_type=f"{prefix}_{i}",
                        session_id="s1",
                        context={"i": i},
                    )
            except Exception as e:
                errors.append(e)

        threads = []
        for t_id in range(5):
            t = threading.Thread(target=enqueue_batch, args=(f"t{t_id}", 20))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert errors == []

        # Verify all 100 events are in the DB
        with sqlite3.connect(db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM review_events").fetchone()[0]
        assert count == 100
