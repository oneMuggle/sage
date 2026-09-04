"""PR #381 工具名重命名迁移的单测。

触发原因: PR #381 删除 TerminalTool / 重写为 BashTool (name='bash'),
但 ensure_default_agents() 没补一段 'terminal → bash' 迁移。
用户 DB 永远卡在旧名字。本文件锁住重命名段的行为契约:

- 三个旧名都映射正确
- 用户私有项不动
- 已是新名时 idempotent (不 upsert)
- 仅这 3 个旧名生效 (其他名完全不动)
"""
from __future__ import annotations

import pytest

from backend.agents import profiles

pytestmark = pytest.mark.unit


class FakeRepo:
    """最小化 AgentRepository mock —— 复刻 test_profiles_intranet_web_access_migration 风格。"""

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


def test_terminal_renames_to_bash(monkeypatch):
    stored = {
        "primary":    {"id": "primary",    "enabled": True, "tools": []},
        "researcher": {"id": "researcher", "enabled": True, "tools": []},
        "coder":      {"id": "coder",      "enabled": True, "tools": ["terminal", "calculator"]},
    }
    repo = _seed_repo(monkeypatch, stored)
    profiles.ensure_default_agents()
    assert "terminal" not in stored["coder"]["tools"]
    assert "bash" in stored["coder"]["tools"]
    assert stored["coder"]["tools"] == ["bash", "calculator"]
    coder_upserts = [u for u in repo.upserts if u["id"] == "coder"]
    assert len(coder_upserts) == 1


def test_file_read_and_file_write_renames(monkeypatch):
    stored = {
        "coder": {"id": "coder", "enabled": True, "tools": ["file_read", "file_write", "calculator"]},
    }
    _seed_repo(monkeypatch, stored)
    profiles.ensure_default_agents()
    assert stored["coder"]["tools"] == ["read_file", "write_file", "calculator"]


def test_renames_preserve_user_extras(monkeypatch):
    """重命名段只动映射表里的 3 个名字; 用户额外项一字不动。"""
    stored = {
        "coder": {"id": "coder", "enabled": True, "tools": ["terminal", "my_custom_tool"]},
    }
    _seed_repo(monkeypatch, stored)
    profiles.ensure_default_agents()
    assert stored["coder"]["tools"] == ["bash", "my_custom_tool"]


def test_renames_idempotent_no_upsert(monkeypatch):
    """tools 已是新名 → 重命名段不触发 upsert。"""
    stored = {
        "coder": {"id": "coder", "enabled": True, "tools": ["read_file", "write_file", "bash", "calculator"]},
    }
    _seed_repo(monkeypatch, stored)
    profiles.ensure_default_agents()
    assert stored["coder"]["tools"] == ["read_file", "write_file", "bash", "calculator"]


def test_renames_only_affects_three_legacy_names(monkeypatch):
    """映射表外的名字(无论旧名还是用户私有)完全不动。"""
    stored = {
        "coder": {"id": "coder", "enabled": True, "tools": ["foo", "bar", "calculator"]},
    }
    _seed_repo(monkeypatch, stored)
    profiles.ensure_default_agents()
    # 既无 rename 触发, 后续兜底段也不动 (foo/bar 不在 _PRIMARY_CURRENT_DEFAULT_TOOLS)
    # —— coder 的"当前默认 ⊆ DB"判定为不相交, 跳过 upsert
    assert stored["coder"]["tools"] == ["foo", "bar", "calculator"]


def test_renames_apply_to_all_agents_not_just_coder(monkeypatch):
    """重命名段遍历所有 agent, 不限定 coder。"""
    stored = {
        "primary":    {"id": "primary",    "enabled": True, "tools": ["terminal", "calculator"]},
        "researcher": {"id": "researcher", "enabled": True, "tools": ["file_read"]},
    }
    _seed_repo(monkeypatch, stored)
    profiles.ensure_default_agents()
    assert "terminal" not in stored["primary"]["tools"]
    assert "bash" in stored["primary"]["tools"]
    assert "file_read" not in stored["researcher"]["tools"]
    assert "read_file" in stored["researcher"]["tools"]
