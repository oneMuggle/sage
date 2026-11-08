"""P2-a: ``POST /agents/batch`` 批量操作契约测试。

覆盖：enable/disable 透传、delete 走级联删除、primary / sage-guide 保护进入 failed、
非法 action 返回 400。
"""
from typing import Any, Dict, List

import pytest
from fastapi import HTTPException

from backend.api import legacy_agent_routes as agent_routes


class _FakeRepo:
    def __init__(self, existing: List[str]) -> None:
        self.existing = set(existing)
        self.updates: List[Dict[str, Any]] = []
        self.deleted: List[str] = []

    def get(self, agent_id: str):
        return {"id": agent_id} if agent_id in self.existing else None

    def update(self, agent_id: str, profile: Dict[str, Any]) -> bool:
        self.updates.append({"id": agent_id, **profile})
        return agent_id in self.existing

    def delete(self, agent_id: str) -> bool:
        self.deleted.append(agent_id)
        self.existing.discard(agent_id)
        return True


class _FakeMemoryManager:
    def purge_agent_memories(self, agent_id: str) -> Dict[str, int]:
        return {"episodic": 0, "semantic": 0, "vector": 0}


class _FakeVersionRepo:
    def delete_all_for_agent(self, agent_id: str) -> int:
        return 0


class _FakeCursor:
    rowcount = 0


class _FakeConn:
    def execute(self, *_args, **_kwargs):
        return _FakeCursor()

    def commit(self) -> None:
        pass


def _install_repo(monkeypatch, existing: List[str]) -> _FakeRepo:
    repo = _FakeRepo(existing)
    monkeypatch.setattr("backend.data.agent_repo.AgentRepository", lambda: repo)
    # 删除级联依赖：记忆管理器 / 版本仓储 / eval 表连接
    monkeypatch.setattr(
        "backend.memory.get_memory_manager", lambda: _FakeMemoryManager()
    )
    monkeypatch.setattr(
        "backend.data.agent_version_repo.AgentVersionRepository",
        lambda: _FakeVersionRepo(),
    )
    monkeypatch.setattr(
        "backend.api.legacy_agent_routes.get_database", lambda: _FakeConn()
    )
    return repo


def test_batch_enable_updates_each_agent(monkeypatch) -> None:
    repo = _install_repo(monkeypatch, ["a1", "a2"])

    result = agent_routes.batch_agents({"action": "enable", "ids": ["a1", "a2"]})

    assert result["succeeded"] == ["a1", "a2"]
    assert result["failed"] == []
    assert repo.updates == [
        {"id": "a1", "enabled": True},
        {"id": "a2", "enabled": True},
    ]


def test_batch_disable_reports_missing_agent_in_failed(monkeypatch) -> None:
    _install_repo(monkeypatch, ["a1"])

    result = agent_routes.batch_agents({"action": "disable", "ids": ["a1", "missing"]})

    assert result["succeeded"] == ["a1"]
    assert len(result["failed"]) == 1
    assert result["failed"][0]["id"] == "missing"


def test_batch_delete_protects_primary(monkeypatch) -> None:
    repo = _install_repo(monkeypatch, ["primary", "a1"])

    result = agent_routes.batch_agents({"action": "delete", "ids": ["primary", "a1"]})

    assert result["succeeded"] == ["a1"]
    assert result["failed"][0]["id"] == "primary"
    assert "primary" not in repo.deleted
    assert repo.deleted == ["a1"]


def test_batch_delete_protects_sage_guide(monkeypatch) -> None:
    repo = _install_repo(monkeypatch, ["sage-guide", "a1"])

    result = agent_routes.batch_agents(
        {"action": "delete", "ids": ["sage-guide", "a1"]}
    )

    assert result["succeeded"] == ["a1"]
    assert result["failed"][0]["id"] == "sage-guide"
    assert "sage-guide" not in repo.deleted
    assert repo.deleted == ["a1"]


def test_batch_rejects_invalid_action() -> None:
    with pytest.raises(HTTPException) as exc:
        agent_routes.batch_agents({"action": "explode", "ids": ["a1"]})
    assert exc.value.status_code == 400
