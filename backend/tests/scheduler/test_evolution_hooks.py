"""Tests for evolution task hook emission (Task 4 step 14).

Each evolution task must emit an ``evolution_completed`` hook after a
successful ``run_async()`` carrying:
- task_name
- items_processed
- duration_ms
- timestamp (ISO 8601)

If the task raises, no hook is emitted. If the hook registry is missing,
the task still completes (no-op).
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from backend.memory.hooks import HookRegistry
from backend.scheduler.evolution import DailySummaryTask, MemoryPruningTask

pytestmark = pytest.mark.unit


@pytest.fixture()
def hooks():
    return HookRegistry()


@pytest.mark.asyncio()
async def test_daily_summary_emits_evolution_completed(tmp_db_path, hooks):
    """DailySummaryTask.run_async() emits ``evolution_completed`` with the
    expected payload shape after successful completion."""
    from backend.data.database import Database

    db = Database(db_path=tmp_db_path)
    db.init_db()

    events: list[dict] = []

    def listener(payload):
        events.append(payload)

    hooks.on("evolution_completed", listener)

    task = DailySummaryTask(db=db)
    # Inject the hook registry (Task 4 step 14: add hooks param).
    task._hooks = hooks  # type: ignore[attr-defined]

    # No sessions today → processed=0 but should still emit completion.
    await task.run_async()

    assert len(events) == 1
    ev = events[0]
    assert ev["task_name"] == "DailySummaryTask"
    assert ev["items_processed"] == 0
    assert "duration_ms" in ev and ev["duration_ms"] >= 0
    # ISO 8601 timestamp parses cleanly
    assert datetime.fromisoformat(ev["timestamp"])


@pytest.mark.asyncio()
async def test_memory_pruning_emits_evolution_completed(tmp_db_path, hooks):
    """MemoryPruningTask also emits ``evolution_completed``."""
    from backend.data.database import Database

    db = Database(db_path=tmp_db_path)
    db.init_db()

    events: list[dict] = []
    hooks.on("evolution_completed", lambda p: events.append(p))

    task = MemoryPruningTask(db=db)
    task._hooks = hooks  # type: ignore[attr-defined]

    await task.run_async()

    assert len(events) == 1
    assert events[0]["task_name"] == "MemoryPruningTask"


@pytest.mark.asyncio()
async def test_no_hook_emitted_on_failure(tmp_db_path):
    """If the task raises, no ``evolution_completed`` is fired."""
    from backend.data.database import Database

    db = Database(db_path=tmp_db_path)
    db.init_db()

    hooks = HookRegistry()
    events: list[dict] = []
    hooks.on("evolution_completed", lambda p: events.append(p))

    task = MemoryPruningTask(db=db)
    task._hooks = hooks  # type: ignore[attr-defined]

    # Force a failure by swapping the cursor with one that raises.
    bad_cursor = MagicMock()
    bad_cursor.execute.side_effect = RuntimeError("simulated db failure")
    db._connection = MagicMock()
    db._connection.cursor.return_value = bad_cursor

    with pytest.raises(RuntimeError):
        await task.run_async()

    assert events == []


@pytest.mark.asyncio()
async def test_task_runs_without_hooks_attr(tmp_db_path):
    """Backward compat: a task without ``_hooks`` still completes (no-op)."""
    from backend.data.database import Database

    db = Database(db_path=tmp_db_path)
    db.init_db()

    task = MemoryPruningTask(db=db)
    # _hooks deliberately not set
    await task.run_async()  # must not raise