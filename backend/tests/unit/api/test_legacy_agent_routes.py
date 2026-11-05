"""R179 — Agent API 路由组（legacy_agent_routes）单元测试。

直接调用路由函数。AgentRepository 全 monkeypatch。
覆盖：list/get/patch/toggle/create 的校验与成功路径。
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.api.legacy_agent_routes import (
    create_agent,
    delete_agent,
    duplicate_agent,
    get_agent_by_id,
    toggle_agent,
    update_agent,
)
from backend.api.legacy_models import AgentCreate, AgentToggle, AgentUpdate

pytestmark = pytest.mark.unit


class _FakeAgentRepo:
    def __init__(self, agents=None):
        self._agents = agents or {}
        self.updated = []
        self.enabled_set = []

    def list_all(self):
        return list(self._agents.values())

    def get(self, agent_id):
        return self._agents.get(agent_id)

    def update(self, agent_id, payload):
        self.updated.append((agent_id, payload))
        if agent_id in self._agents:
            self._agents[agent_id].update(payload)

    def set_enabled(self, agent_id, enabled):
        self.enabled_set.append((agent_id, enabled))
        if agent_id in self._agents:
            self._agents[agent_id]["enabled"] = enabled

    def delete(self, agent_id):
        # M0 (2026-11-03): 删除 / 复制专家测试支撑
        return self._agents.pop(agent_id, None) is not None

    def upsert(self, payload):
        self._agents[payload["id"]] = payload


class _FakeMemoryManager:
    """M3-Task 7: 专家删除级联清理的记忆管理器替身。"""

    def __init__(self, error=None):
        self.error = error
        self.purged = []

    def purge_agent_memories(self, agent_id):
        self.purged.append(agent_id)
        if self.error is not None:
            raise self.error
        return {"episodic": 1, "semantic": 2, "vector": 3, "memory_ids": ["m1", "m2", "m3"]}


@pytest.fixture()
def fake_memory_manager(monkeypatch):
    """替换全局记忆管理器单例 —— 路由内 ``from backend.memory import
    get_memory_manager`` 在调用时解析模块属性，故须打在 ``backend.memory`` 上。"""
    manager = _FakeMemoryManager()
    monkeypatch.setattr("backend.memory.get_memory_manager", lambda: manager)
    return manager


@pytest.fixture()
def fake_repo(monkeypatch, fake_memory_manager):
    agents = {
        "primary": {"id": "primary", "name": "Primary", "enabled": True},
        "coder": {"id": "coder", "name": "Coder", "enabled": True},
    }
    repo = _FakeAgentRepo(agents)
    monkeypatch.setattr(
        "backend.data.agent_repo.AgentRepository", lambda: repo
    )
    return repo


# ---------------------------------------------------------------------------
# list / get
# ---------------------------------------------------------------------------


def test_list_agents_returns_list(fake_repo):
    from backend.api.legacy_agent_routes import list_agents

    out = list_agents()
    assert isinstance(out, list)
    assert len(out) == 2


def test_get_agent_by_id_hit(fake_repo):
    out = get_agent_by_id("primary")
    assert out["id"] == "primary"


def test_get_agent_by_id_miss_404(fake_repo):
    with pytest.raises(HTTPException) as excinfo:
        get_agent_by_id("ghost")
    assert excinfo.value.status_code == 404


# ---------------------------------------------------------------------------
# update_agent
# ---------------------------------------------------------------------------


def test_update_agent_invalid_role_422(fake_repo):
    with pytest.raises(HTTPException) as excinfo:
        update_agent("primary", AgentUpdate(role="hacker"))
    assert excinfo.value.status_code == 422


def test_update_agent_max_iterations_out_of_range_422(fake_repo):
    # 上限已从 50 提到 1000（backend.domain.agent_limits 单一真相源），
    # 越界值必须超过 MAX_ITERATIONS_CEILING 才算越界。
    with pytest.raises(HTTPException) as excinfo:
        update_agent("primary", AgentUpdate(max_iterations=1001))
    assert excinfo.value.status_code == 422
    assert excinfo.value.detail["type"] == "invalid_max_iterations"


def test_update_agent_max_iterations_previously_rejected_now_ok(fake_repo):
    # 99 在旧上限 (50) 下会被 422 拒掉；新上限 1000 下必须放行。
    out = update_agent("primary", AgentUpdate(max_iterations=99))
    assert out["max_iterations"] == 99


def test_update_agent_not_found_404(fake_repo):
    with pytest.raises(HTTPException) as excinfo:
        update_agent("ghost", AgentUpdate(name="x"))
    assert excinfo.value.status_code == 404


def test_update_agent_success_partial(fake_repo):
    out = update_agent("primary", AgentUpdate(name="Renamed"))
    assert out["name"] == "Renamed"
    assert out["id"] == "primary"  # partial update 保留其他字段


# ---------------------------------------------------------------------------
# toggle_agent
# ---------------------------------------------------------------------------


def test_toggle_agent_success(fake_repo):
    out = toggle_agent("primary", AgentToggle(enabled=False))
    assert out["enabled"] is False


def test_toggle_agent_not_found_404(fake_repo):
    with pytest.raises(HTTPException) as excinfo:
        toggle_agent("ghost", AgentToggle(enabled=True))
    assert excinfo.value.status_code == 404


# ---------------------------------------------------------------------------
# delete_agent（M0 2026-11-03）
# ---------------------------------------------------------------------------


def test_delete_agent_success(fake_repo):
    out = delete_agent("coder")
    assert out == {"ok": True, "id": "coder"}
    assert "coder" not in fake_repo._agents


def test_delete_agent_primary_protected_400(fake_repo):
    with pytest.raises(HTTPException) as excinfo:
        delete_agent("primary")
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail["type"] == "protected_agent"
    # primary 必须原样保留
    assert "primary" in fake_repo._agents


def test_delete_agent_not_found_404(fake_repo):
    with pytest.raises(HTTPException) as excinfo:
        delete_agent("ghost")
    assert excinfo.value.status_code == 404
    assert excinfo.value.detail["type"] == "agent_not_found"


# ---------------------------------------------------------------------------
# delete_agent（M3-Task 7 2026-11-04）级联清理私有记忆
# ---------------------------------------------------------------------------


def test_delete_agent_cascades_private_memory_purge(fake_repo, fake_memory_manager):
    out = delete_agent("coder")

    assert out == {"ok": True, "id": "coder"}
    # 私有记忆先清理，再删专家行
    assert fake_memory_manager.purged == ["coder"]
    assert "coder" not in fake_repo._agents


def test_delete_agent_purge_failure_keeps_agent(fake_repo, monkeypatch):
    """清理失败 → 500 且专家不删 —— 不留"专家没了但记忆还在"的半状态。"""
    monkeypatch.setattr(
        "backend.memory.get_memory_manager",
        lambda: _FakeMemoryManager(error=RuntimeError("db down")),
    )

    with pytest.raises(HTTPException) as excinfo:
        delete_agent("coder")

    assert excinfo.value.status_code == 500
    assert excinfo.value.detail["type"] == "memory_purge_failed"
    assert "coder" in fake_repo._agents


def test_delete_agent_primary_protected_skips_purge(fake_repo, fake_memory_manager):
    """受保护专家（primary）不触发清理 —— 校验早于级联。"""
    with pytest.raises(HTTPException) as excinfo:
        delete_agent("primary")

    assert excinfo.value.status_code == 400
    assert fake_memory_manager.purged == []


def test_delete_agent_not_found_skips_purge(fake_repo, fake_memory_manager):
    with pytest.raises(HTTPException) as excinfo:
        delete_agent("ghost")

    assert excinfo.value.status_code == 404
    assert fake_memory_manager.purged == []


# ---------------------------------------------------------------------------
# duplicate_agent（M0 2026-11-03）
# ---------------------------------------------------------------------------


def test_duplicate_agent_success(fake_repo):
    fake_repo._agents["writer"] = {
        "id": "writer",
        "name": "Writer",
        "enabled": True,
        "system_prompt": "你是写作专家",
        "tools": ["web_search"],
        "memory_access": ["private"],
        "model_config": {"model": "m1", "temperature": 0.7, "max_tokens": 0},
        "max_iterations": 20,
        "updated_at": 123,
    }
    out = duplicate_agent("writer")
    assert out["id"].startswith("writer-copy-")
    assert out["name"] == "Writer (副本)"
    assert out["enabled"] is False
    # 内容原样复制
    assert out["system_prompt"] == "你是写作专家"
    assert out["tools"] == ["web_search"]
    assert out["memory_access"] == ["private"]
    assert out["model_config"]["model"] == "m1"
    # updated_at 被 upsert 重填（fake 的 upsert 不重填，但残留的旧值必须被清掉
    # 再由真实 repo 填新值 —— 这里只断言不继承源的 123）
    assert out.get("updated_at") != 123
    # 源 agent 不受影响
    assert fake_repo._agents["writer"]["id"] == "writer"
    assert fake_repo._agents["writer"]["enabled"] is True


def test_duplicate_agent_not_found_404(fake_repo):
    with pytest.raises(HTTPException) as excinfo:
        duplicate_agent("ghost")
    assert excinfo.value.status_code == 404
    assert excinfo.value.detail["type"] == "agent_not_found"


# ---------------------------------------------------------------------------
# M1 (2026-11-03) 专家卡字段：permission_mode 校验 + version 自动递增
# ---------------------------------------------------------------------------


def test_update_agent_invalid_permission_mode_422(fake_repo):
    with pytest.raises(HTTPException) as excinfo:
        update_agent("primary", AgentUpdate(permission_mode="hacker"))
    assert excinfo.value.status_code == 422
    assert excinfo.value.detail["type"] == "invalid_permission_mode"


def test_update_agent_valid_permission_mode_persisted(fake_repo):
    out = update_agent("primary", AgentUpdate(permission_mode="read_only"))
    assert out["permission_mode"] == "read_only"


def test_update_agent_bumps_version_when_persona_changes(fake_repo):
    fake_repo._agents["primary"]["version"] = 4
    out = update_agent("primary", AgentUpdate(system_prompt="新的写作人设"))
    assert out["version"] == 5


def test_update_agent_explicit_version_wins(fake_repo):
    fake_repo._agents["primary"]["version"] = 4
    out = update_agent("primary", AgentUpdate(persona_ui={"tagline": "x"}, version=9))
    assert out["version"] == 9


def test_update_agent_non_persona_change_keeps_version(fake_repo):
    fake_repo._agents["primary"]["version"] = 4
    out = update_agent("primary", AgentUpdate(max_iterations=20))
    assert out["version"] == 4


def test_create_agent_invalid_permission_mode_422(fake_repo):
    with pytest.raises(HTTPException) as excinfo:
        create_agent(AgentCreate(id="newbie", name="Newbie", permission_mode="hacker"))
    assert excinfo.value.status_code == 422
    assert excinfo.value.detail["type"] == "invalid_permission_mode"


def test_create_agent_with_specialist_fields(fake_repo):
    out = create_agent(
        AgentCreate(
            id="writer-m1",
            name="Writer",
            skills=["writing"],
            memory_policy={"write_scope": "specialist"},
            permission_mode="prompt",
        )
    )
    assert out["skills"] == ["writing"]
    assert out["memory_policy"] == {"write_scope": "specialist"}
    assert out["permission_mode"] == "prompt"
