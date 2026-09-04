"""存量 DB 的差集兜底迁移单测。

触发原因: PR #264 / P0-5 / P1 todo / PR #396 的累计迁移都用
`set(tools) == 旧种子` 严格相等判定; 用户 DB 实际是 PR-3 时期的
5 工具种子, 不命中任何 _BEFORE_* 段, 4 段迁移全哑炮。

本文件锁住差集段的行为契约:
- 真子集 → 追加缺的, 原有顺序保留, 新项按默认顺序追加到尾部
- 真超集 / 完全不相交 → 不动, 且不 upsert
- 已是当前形状 → 不 upsert
- 连续跑两次, 第二次 0 upsert
"""

from __future__ import annotations

import pytest

from backend.agents import profiles

pytestmark = pytest.mark.unit


class FakeRepo:
    """最小化 AgentRepository mock —— 与 test_profiles_legacy_tool_rename 同款。"""

    def __init__(self, stored):
        self.stored = stored
        self.upserts = []

    def get(self, agent_id):
        return dict(self.stored[agent_id]) if agent_id in self.stored else None

    def list_all(self):
        return [dict(row) for row in self.stored.values()]

    def upsert(self, data):
        self.upserts.append(data)
        self.stored[data["id"]] = data


def _seed_repo(monkeypatch, stored):
    repo = FakeRepo(stored)
    monkeypatch.setattr(profiles, "_repo_factory_for_tests", lambda: repo)
    return repo


def test_primary_subset_gets_missing_appended(monkeypatch):
    """PR-3 时期 primary 种子(5 工具) → 差集段追加所有缺的当前默认项。"""
    legacy_5 = ["calculator", "memory_search", "memory_save", "list_dir", "read_file"]
    stored = {"primary": {"id": "primary", "enabled": True, "tools": list(legacy_5)}}
    _seed_repo(monkeypatch, stored)
    profiles.ensure_default_agents()
    result = stored["primary"]["tools"]
    # 原有 5 项顺序不变, 位于最前
    assert result[:5] == legacy_5
    # 当前默认集全部就位
    assert set(profiles._PRIMARY_CURRENT_DEFAULT_TOOLS).issubset(set(result))
    # 无重复
    assert len(result) == len(set(result))


def test_primary_superset_untouched(monkeypatch):
    """primary 真超集(含用户额外项) → 差集段不动, 不 upsert。"""
    superset = list(profiles._PRIMARY_CURRENT_DEFAULT_TOOLS) + ["user_extra"]
    stored = {"primary": {"id": "primary", "enabled": True, "tools": list(superset)}}
    repo = _seed_repo(monkeypatch, stored)
    profiles.ensure_default_agents()
    assert stored["primary"]["tools"] == superset
    primary_upserts = [u for u in repo.upserts if u["id"] == "primary"]
    assert primary_upserts == [], f"primary 不应被 upsert, 但收到: {primary_upserts}"


def test_primary_disjoint_untouched(monkeypatch):
    """primary 完全不相交(用户整个白名单换掉) → 差集段不动。"""
    stored = {"primary": {"id": "primary", "enabled": True, "tools": ["my_a", "my_b"]}}
    repo = _seed_repo(monkeypatch, stored)
    profiles.ensure_default_agents()
    assert stored["primary"]["tools"] == ["my_a", "my_b"]
    primary_upserts = [u for u in repo.upserts if u["id"] == "primary"]
    assert primary_upserts == [], f"primary 不应被 upsert, 但收到: {primary_upserts}"


def test_researcher_subset_gets_missing_appended(monkeypatch):
    """researcher 子集(刻意不命中既有集合相等段) → 差集段补缺。"""
    stored = {
        "researcher": {
            "id": "researcher",
            "enabled": True,
            "tools": ["web_fetch", "http_download", "memory_search"],
        },
    }
    _seed_repo(monkeypatch, stored)
    profiles.ensure_default_agents()
    assert "web_search" in stored["researcher"]["tools"]
    assert stored["researcher"]["tools"] == [
        "web_fetch", "http_download", "memory_search", "web_search",
    ]


def test_writer_subset_gets_missing_appended(monkeypatch):
    """writer 也进差集迁移（Task 4 给它加 office 工具后这条才有实际作用）。"""
    stored = {
        "writer": {"id": "writer", "enabled": True, "tools": ["read_file"]},
    }
    _seed_repo(monkeypatch, stored)
    profiles.ensure_default_agents()
    result = stored["writer"]["tools"]
    assert result[0] == "read_file"
    assert set(profiles._WRITER_CURRENT_DEFAULT_TOOLS).issubset(set(result))


def test_already_current_no_upsert(monkeypatch):
    """三个 agent 都已是当前默认形状 → 0 次 upsert。"""
    # 把另 3 个默认 agent 也预置, 避开 ensure_default_agents 的"缺则补"段,
    # 让本测试只盯差集迁移的 0 触发。
    stored = {
        "primary": {
            "id": "primary", "enabled": True,
            "tools": list(profiles._PRIMARY_CURRENT_DEFAULT_TOOLS),
        },
        "researcher": {
            "id": "researcher", "enabled": True,
            "tools": list(profiles._RESEARCHER_CURRENT_DEFAULT_TOOLS),
        },
        "writer": {
            "id": "writer", "enabled": True,
            "tools": list(profiles._WRITER_CURRENT_DEFAULT_TOOLS),
        },
        "coder": {"id": "coder", "enabled": True, "tools": ["read_file", "write_file", "bash", "calculator"]},
        "memory_manager": {"id": "memory_manager", "enabled": True, "tools": ["memory_search", "memory_save"]},
        "reviewer": {"id": "reviewer", "enabled": True, "tools": []},
    }
    repo = _seed_repo(monkeypatch, stored)
    profiles.ensure_default_agents()
    assert repo.upserts == [], f"不应有 upsert, 但收到: {[u['id'] for u in repo.upserts]}"


def test_subset_migration_idempotent(monkeypatch):
    """连续跑两次 ensure_default_agents(), 第二次 0 新增 upsert。"""
    stored = {
        "primary": {
            "id": "primary", "enabled": True,
            "tools": ["calculator", "memory_search", "memory_save", "list_dir", "read_file"],
        },
        "researcher": {
            "id": "researcher", "enabled": True,
            "tools": ["web_search", "web_fetch", "memory_search"],
        },
    }
    repo = _seed_repo(monkeypatch, stored)
    profiles.ensure_default_agents()
    first = len(repo.upserts)
    profiles.ensure_default_agents()
    assert len(repo.upserts) == first, (
        f"第二次跑应不触发 upsert, 但新增了 {len(repo.upserts) - first} 次"
    )


def test_append_missing_tools_returns_false_when_nothing_missing():
    """助手函数本身的契约: 无缺项返回 False, 不改 dict。"""
    agent = {"id": "x", "tools": ["a", "b"]}
    changed = profiles._append_missing_tools(agent, ["a", "b"])
    assert changed is False
    assert agent["tools"] == ["a", "b"]


def test_append_missing_tools_appends_in_default_order():
    agent = {"id": "x", "tools": ["b"]}
    changed = profiles._append_missing_tools(agent, ["a", "b", "c"])
    assert changed is True
    assert agent["tools"] == ["b", "a", "c"]
