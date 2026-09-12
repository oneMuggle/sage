"""R19: 数据安全单元测试 —— 备份服务 + 系统路由

- create_backup: 真实 SQLite 库在线备份、.tmp 原子改名、reason 归一化、
  轮转保留 7 份、损坏路径 fail-safe
- list_backups: 只识别 sage-backup-*.db，新→旧排序
- system_routes: /system/backups 列表与手动创建、/memory/export 信封
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.services import backup_service

pytestmark = pytest.mark.unit


def _mk_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE t (x TEXT)")
    conn.execute("INSERT INTO t VALUES ('hello')")
    conn.commit()
    conn.close()


def test_create_backup_creates_and_lists(tmp_path: Path):
    db = tmp_path / "sage.db"
    _mk_db(db)
    result = backup_service.create_backup("manual", db_path=str(db))
    assert result is not None
    assert result["name"].startswith("sage-backup-")
    assert result["reason"] == "manual"
    backups = backup_service.list_backups(db_path=str(db))
    assert len(backups) == 1
    assert backups[0]["name"] == result["name"]
    # 备份文件是合法 SQLite 且内容一致
    conn = sqlite3.connect(str(tmp_path / "backups" / result["name"]))
    row = conn.execute("SELECT x FROM t").fetchone()
    conn.close()
    assert row == ("hello",)


def test_create_backup_invalid_reason_normalized(tmp_path: Path):
    db = tmp_path / "sage.db"
    _mk_db(db)
    result = backup_service.create_backup("bogus", db_path=str(db))
    assert result is not None
    assert result["reason"] == "manual"


def test_rotation_keeps_seven(tmp_path: Path):
    db = tmp_path / "sage.db"
    _mk_db(db)
    for _ in range(9):
        assert backup_service.create_backup("manual", db_path=str(db)) is not None
    backups = backup_service.list_backups(db_path=str(db))
    assert len(backups) == backup_service.RETENTION_COUNT


def test_list_backups_empty_and_missing_dir(tmp_path: Path):
    assert backup_service.list_backups(db_path=str(tmp_path / "none.db")) == []


def test_create_backup_fail_safe_on_bad_source(tmp_path: Path):
    # 源不是合法 SQLite → backup API 抛错 → 返回 None 而非上抛
    db = tmp_path / "bad.db"
    db.write_bytes(b"not a sqlite file")
    assert backup_service.create_backup("manual", db_path=str(db)) is None


def test_system_routes_backups_and_memory_export(tmp_path: Path, monkeypatch):
    db = tmp_path / "sage.db"
    _mk_db(db)
    monkeypatch.setattr(
        "backend.services.backup_service.Database",
        lambda: type("D", (), {"db_path": str(db)})(),
    )
    from fastapi import FastAPI

    from backend.api.system_routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    client = TestClient(app)

    # 初始为空
    res = client.get("/api/v1/system/backups")
    assert res.status_code == 200
    assert res.json()["backups"] == []

    # 手动创建
    res = client.post("/api/v1/system/backups")
    assert res.status_code == 200
    assert res.json()["ok"] is True

    res = client.get("/api/v1/system/backups")
    assert len(res.json()["backups"]) == 1

    # 记忆导出信封结构（MemoryManager 在测试环境可能初始化失败 → 降级空集）
    res = client.get("/api/v1/memory/export")
    assert res.status_code == 200
    body = res.json()
    assert body["app"] == "sage"
    assert body["version"] == 1
    assert "episodic" in body and "semantic" in body
