"""R21: 数据安全第二批单元测试 —— 备份恢复 + 记忆导入

- restore_backup: marker/pending 文件写入、pre-restore 安全备份、
  非法 name 与缺失备份拒绝
- apply_pending_restore: 原子替换主库（内容确实换了）、marker 清理、
  无 marker 幂等
- POST /system/backups/{name}/restore 与 POST /memory/import 信封
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.services import backup_service

pytestmark = pytest.mark.unit


def _mk_db(path: Path, content: str = "v1") -> None:
    """建库（首调用）或改值（后续调用，模拟数据演进）。"""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE IF NOT EXISTS t (x TEXT)")
    conn.execute("DELETE FROM t")
    conn.execute("INSERT INTO t VALUES (?)", (content,))
    conn.commit()
    conn.close()


def _read_db(path: Path) -> str:
    conn = sqlite3.connect(str(path))
    row = conn.execute("SELECT x FROM t LIMIT 1").fetchone()
    conn.close()
    return row[0] if row else ""


def test_restore_schedules_and_writes_pending(tmp_path: Path):
    db = tmp_path / "sage.db"
    _mk_db(db, "old")
    backup = backup_service.create_backup("manual", db_path=str(db))
    assert backup is not None
    # 主库随后改数据 —— 备份仍是 old
    _mk_db(db, "changed")

    result = backup_service.restore_backup(backup["name"], db_path=str(db))
    assert result == {"ok": True, "applied_at_startup": True, "backup": backup["name"]}
    assert (tmp_path / "sage.db.restore-pending").is_file()
    marker = tmp_path / "backups" / backup_service.RESTORE_MARKER
    assert marker.is_file()
    # pre-restore 安全备份存在（9 份 = 1 原备份 + 1 安全备份）
    assert len(backup_service.list_backups(db_path=str(db))) == 2


def test_restore_rejects_bad_names(tmp_path: Path):
    db = tmp_path / "sage.db"
    _mk_db(db)
    assert backup_service.restore_backup("../evil", db_path=str(db)) is None
    assert backup_service.restore_backup("sage-backup-99999999-000000.db", db_path=str(db)) is None
    assert backup_service.restore_backup("", db_path=str(db)) is None


def test_apply_pending_restore_swaps_content(tmp_path: Path):
    db = tmp_path / "sage.db"
    _mk_db(db, "old")
    backup = backup_service.create_backup("manual", db_path=str(db))
    _mk_db(db, "changed")
    assert backup_service.restore_backup(backup["name"], db_path=str(db))

    applied = backup_service.apply_pending_restore(db_path=str(db))
    assert applied is True
    assert _read_db(db) == "old"  # 内容回到备份点
    assert not (tmp_path / "sage.db.restore-pending").exists()
    # marker 已清理；再跑幂等 False
    assert backup_service.apply_pending_restore(db_path=str(db)) is False


def test_apply_pending_restore_noop_without_marker(tmp_path: Path):
    db = tmp_path / "sage.db"
    _mk_db(db)
    assert backup_service.apply_pending_restore(db_path=str(db)) is False


class _FakeRepo:
    """类级共享存储 —— 路由每次请求新建 MemoryManager，去重状态需跨请求。"""

    items: list = []

    def exists_by_content(self, content: str) -> bool:
        return any(it["content"] == content for it in _FakeRepo.items)

    def save(self, content: str, **kwargs):
        _FakeRepo.items.append({"content": content, **kwargs})
        return f"m{len(_FakeRepo.items)}"


class _FakeManager:
    def __init__(self):
        self.episodic = _FakeRepo()
        self.semantic = _FakeRepo()

    def reset(self):
        _FakeRepo.items.clear()


def test_system_routes_restore_and_memory_import(tmp_path: Path, monkeypatch):
    db = tmp_path / "sage.db"
    _mk_db(db)
    monkeypatch.setattr(
        "backend.services.backup_service.Database",
        lambda: type("D", (), {"db_path": str(db)})(),
    )
    monkeypatch.setattr(
        "backend.memory.manager.MemoryManager",
        _FakeManager,
    )
    from fastapi import FastAPI

    from backend.api.system_routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    client = TestClient(app)

    # 建一个备份
    created = client.post("/api/v1/system/backups").json()["backup"]["name"]

    # 非法 name → 400
    res = client.post("/api/v1/system/backups/../evil/restore")
    assert res.status_code in (400, 404)

    # 合法恢复 → 200 + 安排语义
    res = client.post(f"/api/v1/system/backups/{created}/restore")
    assert res.status_code == 200
    assert res.json()["applied_at_startup"] is True

    # 记忆导入：版本防御
    res = client.post("/api/v1/memory/import", json={"version": 99, "episodic": []})
    assert res.status_code == 400

    _FakeManager().reset()
    # 记忆导入：空集
    res = client.post("/api/v1/memory/import", json={"version": 1, "episodic": [], "semantic": []})
    assert res.status_code == 200
    body = res.json()
    assert body["imported"] == 0
    assert body["skipped"] == 0
    assert body["failed"] == 0

    # 记忆导入：真实写入 + 去重（同 content 二次导入 → skipped）
    envelope = {
        "version": 1,
        "episodic": [{"content": "ep1", "importance": 7}],
        "semantic": [{"content": "se1", "tags": ["t"]}],
    }
    res = client.post("/api/v1/memory/import", json=envelope)
    assert res.status_code == 200
    assert res.json()["imported"] == 2
    res = client.post("/api/v1/memory/import", json=envelope)
    assert res.json()["skipped"] == 2
