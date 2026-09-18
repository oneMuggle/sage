"""Audit regressions shared by main and Python 3.8 Win7 (isolated stores)."""
import sqlite3
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.mcp.config import validate_server_config
from backend.mcp.pool import McpServerPool, ServerState
from backend.memory.working import WorkingMemory
from backend.services.scheduler import SchedulerService


def test_snapshot_failure_keeps_old_snapshot_and_outer_transaction():
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE working_memory_snapshot(session_id TEXT, role TEXT, content TEXT CHECK(content != 'bad'), tokens INT, timestamp REAL, created_at INT)")
        conn.execute("CREATE TABLE unrelated(value TEXT)")
        conn.execute("INSERT INTO working_memory_snapshot VALUES ('s', 'user', 'old', 1, 0, 0)")
        conn.commit()
        conn.execute("INSERT INTO unrelated VALUES ('keep pending')")
        fake = SimpleNamespace(
            _db=SimpleNamespace(get_connection=lambda: conn),
            _resolve=lambda sid: sid,
            _session_messages=lambda sid: [
                {"role": "user", "content": "partial"},
                {"role": "user", "content": "bad"},
            ],
        )
        WorkingMemory._save_snapshot(fake, "s")
        assert conn.in_transaction
        conn.commit()
        assert conn.execute("SELECT content FROM working_memory_snapshot").fetchall() == [("old",)]
        assert conn.execute("SELECT value FROM unrelated").fetchall() == [("keep pending",)]
    finally:
        conn.close()


def test_snapshot_success_commits_when_no_outer_transaction():
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE working_memory_snapshot(session_id TEXT, role TEXT, content TEXT, tokens INT, timestamp REAL, created_at INT)")
        fake = SimpleNamespace(
            _db=SimpleNamespace(get_connection=lambda: conn),
            _resolve=lambda sid: sid,
            _session_messages=lambda sid: [{"role": "user", "content": "new"}],
        )
        WorkingMemory._save_snapshot(fake, "s")
        assert not conn.in_transaction
        assert conn.execute("SELECT content FROM working_memory_snapshot").fetchall() == [("new",)]
    finally:
        conn.close()


def test_http_server_patch_preserves_transport_url():
    config = validate_server_config(name="http-test", url="https://example.invalid/mcp")
    record = SimpleNamespace(config=config, state=ServerState.READY, set_state=MagicMock())
    fake = SimpleNamespace(
        _lock=threading.RLock(), _records={config.name: record},
        _stop_record=MagicMock(), _unregister_server_tools=MagicMock(),
    )
    with patch("backend.mcp.pool.upsert_user_server_config") as persist:
        McpServerPool.update_server(fake, config.name, enabled=False)
    assert record.config.url == config.url
    assert record.config.enabled is False
    assert persist.call_args[0][0].url == config.url
    fake._stop_record.assert_called_once_with(record)


def test_disabling_job_removes_scheduler_entry_and_ignores_queued_callback(tmp_path):
    messages = MagicMock()
    sessions = SimpleNamespace(exists=lambda sid: True)
    service = SchedulerService(tmp_path / "tasks.json", messages, sessions)
    task = service.add_task("audit", "recurring", {"kind": "recurring", "cron": "0 8 * * *"}, "s", "hello")
    assert service._scheduler.get_job(task.id) is not None
    service.update_task(task.id, enabled=False)
    assert service._scheduler.get_job(task.id) is None
    service._fire_scheduled(task)
    messages.insert.assert_not_called()
    service.run_now(task.id)  # explicit manual action retains its existing semantics
    messages.insert.assert_called_once()
