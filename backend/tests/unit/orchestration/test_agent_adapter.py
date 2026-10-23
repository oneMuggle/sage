"""R129 — 种子 Agent 适配器单元测试。

覆盖：dict profile → orchestration Agent 映射、enabled 过滤（缺键默认
启用）、tools JSON 字符串解析与损坏降级、name 缺省回退 id、get_agent
三态、repo 缺省懒加载。
"""

from __future__ import annotations

import pytest

from backend.orchestration.agent_adapter import SeededAgentRegistry
from backend.orchestration.models import Agent

pytestmark = pytest.mark.unit


class _FakeRepo:
    def __init__(self, profiles=None, by_id=None):
        self._profiles = profiles or []
        self._by_id = by_id or {}

    def list_all(self):
        return list(self._profiles)

    def get(self, agent_id):
        return self._by_id.get(agent_id)


def _profile(**overrides):
    base = {
        "id": "researcher",
        "name": "Researcher",
        "role": "research",
        "tools": ["web_search", "read_file"],
    }
    base.update(overrides)
    return base


def test_list_agents_maps_to_orchestration_agent():
    reg = SeededAgentRegistry(_FakeRepo([_profile()]))
    agents = reg.list_agents()
    assert len(agents) == 1
    a = agents[0]
    assert isinstance(a, Agent)
    assert a.agent_id == "researcher"
    assert a.name == "Researcher"
    assert a.status == "active"
    assert a.capabilities == ["web_search", "read_file"]
    assert a.max_concurrent_tasks == 2
    assert a.default_permission == "implement"


def test_disabled_agents_filtered_and_missing_key_defaults_enabled():
    profiles = [
        _profile(id="off", enabled=False),
        _profile(id="implicit"),  # 无 enabled 键
    ]
    agents = SeededAgentRegistry(_FakeRepo(profiles)).list_agents()
    assert [a.agent_id for a in agents] == ["implicit"]


def test_tools_json_string_parsed():
    profile = _profile(tools='["t1", "t2"]')
    a = SeededAgentRegistry(_FakeRepo([profile])).list_agents()[0]
    assert a.capabilities == ["t1", "t2"]


def test_tools_corrupt_json_falls_back_to_role():
    profile = _profile(tools="{not json")
    a = SeededAgentRegistry(_FakeRepo([profile])).list_agents()[0]
    assert a.capabilities == ["research"]


def test_tools_missing_falls_back_to_role():
    profile = _profile(tools=None, role="coder")
    a = SeededAgentRegistry(_FakeRepo([profile])).list_agents()[0]
    assert a.capabilities == ["coder"]


def test_name_defaults_to_id_only_when_key_absent():
    profile = _profile(id="anon")
    del profile["name"]  # 键缺省才回退 id（dict.get 语义：显式 None 不回退）
    a = SeededAgentRegistry(_FakeRepo([profile])).list_agents()[0]
    assert a.name == "anon"


def test_get_agent_hit_miss_disabled():
    repo = _FakeRepo(
        profiles=[],
        by_id={
            "on": _profile(id="on"),
            "off": _profile(id="off", enabled=False),
        },
    )
    reg = SeededAgentRegistry(repo)
    assert reg.get_agent("on").agent_id == "on"
    assert reg.get_agent("missing") is None
    assert reg.get_agent("off") is None  # 禁用的查单个同样不可见


def test_default_repo_lazily_constructed(monkeypatch):
    constructed = []

    class _FakeModuleRepo:
        def __init__(self):
            constructed.append(self)

        def list_all(self):
            return []

    import backend.data.agent_repo as agent_repo_mod

    monkeypatch.setattr(agent_repo_mod, "AgentRepository", _FakeModuleRepo)
    SeededAgentRegistry()
    assert len(constructed) == 1  # repo=None → 默认构造 AgentRepository
