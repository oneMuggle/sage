"""Rescue repair — 修复动作的幂等性与备份审计."""
from __future__ import annotations

import importlib
import json

from backend.services.rescue import repair


def test_clear_caches_dry_run(tmp_path):
    for d in ("Cache", "Code Cache", "GPUCache"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "x").write_bytes(b"a" * 1024)
    result = repair.clear_caches(user_data_dir=tmp_path, confirm=False)
    assert result["dry_run"] is True
    assert len(result["would_clear"]) == 3
    # 原目录仍在
    for d in ("Cache", "Code Cache", "GPUCache"):
        assert (tmp_path / d).exists()


def test_clear_caches_removes_and_records(tmp_path):
    for d in ("Cache", "GPUCache"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "x").write_bytes(b"b" * 2048)
    result = repair.clear_caches(user_data_dir=tmp_path, confirm=True)
    assert result["freed_bytes"] == 2 * 2048
    assert not (tmp_path / "Cache").exists()
    actions = (tmp_path / "diagnostics" / "rescue-actions.jsonl").read_text(encoding="utf-8")
    records = [json.loads(line) for line in actions.splitlines() if line.strip()]
    assert any(r["action"] == "clear_caches" for r in records)


def test_reset_window_state(tmp_path):
    target = tmp_path / "window-state.json"
    target.write_text('{"x":1}', encoding="utf-8")
    dry = repair.reset_window_state(user_data_dir=tmp_path, confirm=False)
    assert dry["dry_run"] is False  # 文件存在，dry_run=False 但没删除
    assert target.exists()
    result = repair.reset_window_state(user_data_dir=tmp_path, confirm=True)
    assert result["removed"] is True
    assert not target.exists()


def test_truncate_logs_keeps_small_files_untouched(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    small = logs / "sage-1.ndjson"
    small.write_bytes(b"x" * 100)
    result = repair.truncate_logs(user_data_dir=tmp_path, max_mb=1)
    assert result["scanned"] == 1
    assert result["truncated"] == 0
    assert small.stat().st_size == 100


def test_truncate_logs_backs_up_and_truncates(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    big = logs / "sage-1.ndjson"
    # 3 MB 文件
    big.write_bytes(b"a" * (3 * 1024 * 1024))
    result = repair.truncate_logs(user_data_dir=tmp_path, max_mb=1)
    assert result["truncated"] == 1
    # 截断后 <= 1 MB
    assert big.stat().st_size <= 1024 * 1024
    # 备份存在
    assert any((tmp_path / "backups" / "logs").glob("sage-1-*.ndjson"))


def test_kill_orphan_backend_unsupported_on_linux(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    importlib.reload(repair)
    result = repair.kill_orphan_backend(confirm=True)
    assert result["unsupported"] is True


def test_check_db_integrity_missing_db(tmp_path):
    result = repair.check_db_integrity(user_data_dir=tmp_path)
    assert result["ok"] is False
    assert result["missing"] is True


def test_check_db_integrity_ok_with_schema_version(tmp_path):
    import sqlite3

    db_path = tmp_path / "sage.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE schema_version (version INTEGER, applied_at TEXT, description TEXT)"
    )
    conn.execute("INSERT INTO schema_version VALUES (13, 'x', 'y')")
    conn.execute("CREATE TABLE t1 (x)")
    conn.commit()
    conn.close()
    result = repair.check_db_integrity(user_data_dir=tmp_path)
    assert result["ok"] is True
    assert result["schema_version"] == 13


def test_reset_config_dry_run_does_not_change_db(tmp_path):
    import sqlite3

    db_path = tmp_path / "sage.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE preferences (key TEXT PRIMARY KEY, value TEXT, value_type TEXT, category TEXT, created_at INTEGER, updated_at INTEGER)"
    )
    conn.execute(
        "INSERT INTO preferences VALUES (?, ?, ?, ?, ?, ?)",
        (
            "app_settings",
            json.dumps({"version": 1, "endpoints": [{"id": "e1"}]}),
            "json",
            "general",
            0,
            0,
        ),
    )
    conn.commit()
    conn.close()

    dry = repair.reset_config(confirm=False, user_data_dir=tmp_path)
    assert dry["dry_run"] is True

    # 数据库没变
    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT value FROM preferences WHERE key='app_settings'").fetchone()
    conn.close()
    assert "e1" in row[0]
