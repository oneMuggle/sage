"""primary 白名单 todo_write 升级路径单测（对齐 agent 工具升级模式）。"""

from __future__ import annotations

import pytest

from backend.agents import profiles

pytestmark = pytest.mark.unit


def test_default_seed_includes_todo_write():
    primary = next(a for a in profiles.create_default_agents() if a.id == "primary")
    assert "todo_write" in primary.tools


_LEGACY_SEED = [
    "calculator", "memory_search", "memory_save", "list_dir", "read_file",
    "grep_search", "glob_search", "file_summary", "agent",
]


class FakeRepo:
    def __init__(self, stored):
        self.stored = stored
        self.upserts = []

    def get(self, agent_id):
        return dict(self.stored[agent_id]) if agent_id in self.stored else None

    def upsert(self, data):
        self.upserts.append(data)
        self.stored[data["id"]] = data


def test_legacy_seed_gets_todo_write_appended(monkeypatch):
    """旧种子白名单（含 agent 不含 todo_write）→ ensure_default_agents 追加。"""
    stored = {"primary": {"id": "primary", "enabled": True, "tools": list(_LEGACY_SEED)}}
    repo = FakeRepo(stored)
    monkeypatch.setattr(profiles, "_repo_factory_for_tests", lambda: repo)
    profiles.ensure_default_agents()
    assert "todo_write" in stored["primary"]["tools"]
    assert "agent" in stored["primary"]["tools"]  # 升级链不丢既有工具


def test_customized_whitelist_untouched(monkeypatch):
    """用户自定义过白名单 → 不自动追加。"""
    stored = {"primary": {"id": "primary", "enabled": True, "tools": ["calculator"]}}
    repo = FakeRepo(stored)
    monkeypatch.setattr(profiles, "_repo_factory_for_tests", lambda: repo)
    profiles.ensure_default_agents()
    assert stored["primary"]["tools"] == ["calculator"]
