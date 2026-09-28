"""R70 — system 系统维护路由单元测试。

直接调用路由函数（同步）。backup_service 与 MemoryManager 全 monkeypatch。
覆盖：备份清单/创建成功/创建失败信封/恢复成功/恢复失败 400、记忆导入的
版本守卫/新增/去重跳过/空内容跳过/单条失败计数/管理器不可用 500、
记忆导出信封结构与失败降级。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.api import system_routes as sr

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 备份
# ---------------------------------------------------------------------------


def test_list_backups_passthrough(monkeypatch):
    monkeypatch.setattr(
        sr.backup_service, "list_backups", lambda: [{"name": "b1"}, {"name": "b2"}]
    )
    out = sr.list_backups()
    assert out == {"backups": [{"name": "b1"}, {"name": "b2"}]}


def test_create_backup_success(monkeypatch):
    monkeypatch.setattr(
        sr.backup_service, "create_backup", lambda tag: {"name": tag, "size": 1}
    )
    out = sr.create_backup()
    assert out == {"ok": True, "backup": {"name": "manual", "size": 1}}


def test_create_backup_failure_envelope(monkeypatch):
    monkeypatch.setattr(sr.backup_service, "create_backup", lambda tag: None)
    out = sr.create_backup()
    assert out == {"ok": False, "error": "backup failed (see server log)"}


def test_restore_backup_success(monkeypatch):
    result = {"scheduled": True, "name": "b1"}
    monkeypatch.setattr(sr.backup_service, "restore_backup", lambda name: result)
    out = sr.restore_backup("b1")
    assert out is result


def test_restore_backup_missing_400(monkeypatch):
    monkeypatch.setattr(sr.backup_service, "restore_backup", lambda name: None)
    resp = sr.restore_backup("ghost")
    assert resp.status_code == 400
    assert "ghost" in json.loads(resp.body)["error"]


# ---------------------------------------------------------------------------
# 记忆导入
# ---------------------------------------------------------------------------


def _memory_envelope(episodic, semantic, version=1):
    return {"version": version, "episodic": episodic, "semantic": semantic}


class _FakeRepo:
    def __init__(self, existing=(), save_error=None):
        self.existing = set(existing)
        self.saved = []
        self.save_error = save_error

    def exists_by_content(self, content):
        return content in self.existing

    def save(self, content, **kwargs):
        if self.save_error:
            raise self.save_error
        self.saved.append({"content": content, **kwargs})


def _install_memory(monkeypatch, episodic_repo, semantic_repo):
    mgr = SimpleNamespace(episodic=episodic_repo, semantic=semantic_repo)
    monkeypatch.setattr("backend.memory.manager.MemoryManager", lambda: mgr)


def test_import_memory_rejects_bad_version(monkeypatch):
    resp = sr.import_memory({"version": 99, "episodic": [], "semantic": []})
    assert resp.status_code == 400
    assert "version" in json.loads(resp.body)["error"]


def test_import_memory_happy_path_with_dedup(monkeypatch):
    epi = _FakeRepo(existing=["already-there"])
    sem = _FakeRepo()
    _install_memory(monkeypatch, epi, sem)
    payload = _memory_envelope(
        episodic=[
            {"content": "new memory", "importance": 8, "session_id": "s1"},
            {"content": "already-there"},
        ],
        semantic=[
            {"content": "sem new", "summary": "sum", "tags": ["a", "b"]},
            {"content": "sem new"},  # 新会话内重复仍会再存（无全局去重表）→ 记 imported
        ],
    )
    out = sr.import_memory(payload)
    assert out["imported"] == 3
    assert out["skipped"] == 1
    assert out["failed"] == 0
    assert epi.saved[0]["importance"] == 8
    assert sem.saved[0]["tags"] == ["a", "b"]
    assert "imported_at" in out


def test_import_memory_blank_and_non_dict_entries(monkeypatch):
    epi = _FakeRepo()
    sem = _FakeRepo()
    _install_memory(monkeypatch, epi, sem)
    payload = _memory_envelope(
        episodic=[{"content": "   "}, "not-a-dict", {"content": "kept"}],
        semantic=[42, {"content": "sem kept"}],
    )
    out = sr.import_memory(payload)
    assert out["imported"] == 2
    assert out["skipped"] == 1
    assert out["failed"] == 2


def test_import_memory_single_failure_does_not_abort(monkeypatch):
    epi = _FakeRepo(save_error=RuntimeError("db busy"))
    sem = _FakeRepo()
    _install_memory(monkeypatch, epi, sem)
    payload = _memory_envelope(
        episodic=[{"content": "a"}, {"content": "b"}],
        semantic=[{"content": "c"}],
    )
    out = sr.import_memory(payload)
    assert out["failed"] == 2
    assert len(epi.saved) == 0
    assert out["imported"] == 1  # semantic 成功
    assert len(out["errors"]) == 2


def test_import_memory_manager_unavailable_500(monkeypatch):
    def boom():
        raise RuntimeError("no memory db")

    monkeypatch.setattr("backend.memory.manager.MemoryManager", boom)
    resp = sr.import_memory(_memory_envelope([], []))
    assert resp.status_code == 500
    assert "unavailable" in json.loads(resp.body)["error"]


def test_export_memory_envelope(monkeypatch):
    epi = _FakeRepo()
    epi.get_recent = lambda limit: [{"content": "e1"}]
    sem = _FakeRepo()
    sem.get_all = lambda: [{"content": "s1"}]
    _install_memory(monkeypatch, epi, sem)
    out = sr.export_memory()
    assert out["app"] == "sage"
    assert out["version"] == 1
    assert out["episodic"] == [{"content": "e1"}]
    assert out["semantic"] == [{"content": "s1"}]
    assert "exported_at" in out


def test_export_memory_failure_degrades_to_empty(monkeypatch):
    def boom():
        raise RuntimeError("broken")

    monkeypatch.setattr("backend.memory.manager.MemoryManager", boom)
    out = sr.export_memory()
    assert out["episodic"] == []
    assert out["semantic"] == []
    assert out["app"] == "sage"
