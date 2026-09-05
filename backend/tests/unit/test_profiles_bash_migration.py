"""2026-09-04 bash 三件套迁移单测：

- primary 种子白名单追加 bash/bash_output/kill_shell（D1 决策：
  默认聊天可执行命令，INTERACTIVE 模式下 EXEC 先询问用户）
- coder 白名单补齐 bash_output/kill_shell（T2 孤儿 shell 修复：
  run_in_background 的 shell_id 必须可轮询、可终止）

仅当命中"旧种子"集合时才升级；用户自定义一律不动。
"""

from __future__ import annotations

import pytest

from backend.agents import profiles
from backend.domain.tool_names import EXEC_TOOLS

pytestmark = pytest.mark.unit


class FakeRepo:
    """最小化 AgentRepository mock —— 复刻 test_profiles_todo_upgrade 风格。"""

    def __init__(self, stored):
        self.stored = stored
        self.upserts = []

    def get(self, agent_id):
        return dict(self.stored[agent_id]) if agent_id in self.stored else None

    def upsert(self, data):
        self.upserts.append(data)
        self.stored[data["id"]] = data


# ---------------------------------------------------------------------------
# 代码默认种子
# ---------------------------------------------------------------------------


def test_default_seed_primary_includes_bash_trio():
    """代码默认 primary 白名单含 bash 三件套（D1：默认聊天可执行命令）。"""
    primary = next(a for a in profiles.create_default_agents() if a.id == "primary")
    for tool in EXEC_TOOLS:
        assert tool in primary.tools


def test_default_seed_coder_includes_bash_trio():
    """代码默认 coder 白名单含 bash 三件套（T2：后台 shell 可轮询/终止）。"""
    coder = next(a for a in profiles.create_default_agents() if a.id == "coder")
    for tool in EXEC_TOOLS:
        assert tool in coder.tools


def test_default_seed_subagent_whitelist_stays_readonly():
    """D1 边界：子代理只读白名单（SUBAGENT_TOOL_WHITELIST）不含 bash 类工具。"""
    from backend.tools.agent_tool import SUBAGENT_TOOL_WHITELIST

    assert not (set(SUBAGENT_TOOL_WHITELIST) & set(EXEC_TOOLS))


# ---------------------------------------------------------------------------
# primary 存量迁移
# ---------------------------------------------------------------------------


def test_legacy_primary_gets_bash_trio_appended(monkeypatch):
    """旧 primary 种子（fetch_direct 时代，无 bash）→ 追加三件套，既有工具不丢。"""
    legacy = sorted(profiles._PRIMARY_TOOLS_BEFORE_BASH)
    stored = {
        "primary": {"id": "primary", "enabled": True, "tools": list(legacy)},
    }
    repo = FakeRepo(stored)
    monkeypatch.setattr(profiles, "_repo_factory_for_tests", lambda: repo)
    profiles.ensure_default_agents()
    for tool in EXEC_TOOLS:
        assert tool in stored["primary"]["tools"]
    for tool in legacy:
        assert tool in stored["primary"]["tools"]


def test_current_primary_untouched(monkeypatch):
    """已是当前形状（含 bash 三件套）→ 绝不再追加（防重复写入 + updated_at 抖动）。"""
    current = sorted(profiles._PRIMARY_TOOLS_BEFORE_BASH) + list(EXEC_TOOLS)
    stored = {
        "primary": {"id": "primary", "enabled": True, "tools": current},
    }
    repo = FakeRepo(stored)
    monkeypatch.setattr(profiles, "_repo_factory_for_tests", lambda: repo)
    profiles.ensure_default_agents()
    primary_upserts = [u for u in repo.upserts if u["id"] == "primary"]
    assert primary_upserts == [], f"primary 不应被 upsert，但收到: {primary_upserts}"


def test_customized_primary_whitelist_untouched(monkeypatch):
    """用户整体替换过 primary 白名单（与当前默认完全不相交）→ 绝不自动改动。

    与当前默认相交的子集形状会被差集兜底段补齐（remote 语义，见
    test_profiles_subset_migration.py），不再属于"自定义不动"的范畴。
    """
    custom = ["my_a", "my_b"]
    stored = {
        "primary": {"id": "primary", "enabled": True, "tools": list(custom)},
    }
    repo = FakeRepo(stored)
    monkeypatch.setattr(profiles, "_repo_factory_for_tests", lambda: repo)
    profiles.ensure_default_agents()
    assert stored["primary"]["tools"] == custom


# ---------------------------------------------------------------------------
# coder 存量迁移
# ---------------------------------------------------------------------------


def test_legacy_coder_gets_bash_output_kill_shell(monkeypatch):
    """PR #402 修复形状的 coder（缺 bash_output/kill_shell）→ 补齐两件。"""
    legacy = ["read_file", "write_file", "bash", "calculator"]
    stored = {
        "coder": {"id": "coder", "enabled": True, "tools": list(legacy)},
    }
    repo = FakeRepo(stored)
    monkeypatch.setattr(profiles, "_repo_factory_for_tests", lambda: repo)
    profiles.ensure_default_agents()
    assert stored["coder"]["tools"] == [
        "read_file",
        "write_file",
        "bash",
        "calculator",
        "bash_output",
        "kill_shell",
    ]


def test_customized_coder_whitelist_untouched(monkeypatch):
    """用户自定义过 coder 白名单（≠ 旧种子）→ 绝不自动改动。"""
    custom = ["read_file", "bash"]
    stored = {
        "coder": {"id": "coder", "enabled": True, "tools": list(custom)},
    }
    repo = FakeRepo(stored)
    monkeypatch.setattr(profiles, "_repo_factory_for_tests", lambda: repo)
    profiles.ensure_default_agents()
    assert stored["coder"]["tools"] == custom


# ---------------------------------------------------------------------------
# 迁移链顺序敏感（旧 DB 一次跑到位）
# ---------------------------------------------------------------------------


def test_legacy_db_primary_full_chain(monkeypatch):
    """最旧 DB（primary 缺 agent/todo/web 对/bash）→ 一次 ensure_default_agents
    链式跑完全部段，终态含 agent + todo_write + web 两件套 + bash 三件套
    （= 当前种子形状）。"""
    stored = {
        "primary": {
            "id": "primary",
            "enabled": True,
            "tools": list(profiles._PRIMARY_TOOLS_BEFORE_AGENT),
        },
    }
    repo = FakeRepo(stored)
    monkeypatch.setattr(profiles, "_repo_factory_for_tests", lambda: repo)
    profiles.ensure_default_agents()
    for tool in ("agent", "todo_write", "web_fetch", "http_download", *EXEC_TOOLS):
        assert tool in stored["primary"]["tools"]
