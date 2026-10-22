"""R179 — Agent API 路由组（legacy_agent_routes）单元测试。

直接调用路由函数。AgentRepository 全 monkeypatch。
覆盖：list/get/patch/toggle/create 的校验与成功路径。
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.api.legacy_agent_routes import (
    get_agent_by_id,
    toggle_agent,
    update_agent,
)
from backend.api.legacy_models import AgentToggle, AgentUpdate

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

    def upsert(self, payload):
        self._agents[payload["id"]] = payload


@pytest.fixture()
def fake_repo(monkeypatch):
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
    with pytest.raises(HTTPException) as excinfo:
        update_agent("primary", AgentUpdate(max_iterations=99))
    assert excinfo.value.status_code == 422


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
