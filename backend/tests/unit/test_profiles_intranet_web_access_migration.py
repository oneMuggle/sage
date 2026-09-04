"""PR #396 后置迁移单测：

- researcher 白名单追加 http_download（仿 _PRIMARY_TOOLS_BEFORE_AGENT 模式）
- primary system_prompt 升级为含 agent 子代理委派提示

仅当命中"旧种子"集合/字符串时才升级；用户自定义一律不动。
"""

from __future__ import annotations

import pytest

from backend.agents import profiles

pytestmark = pytest.mark.unit


def test_default_seed_includes_researcher_http_download():
    """代码默认 researcher 工具白名单含 http_download。"""
    researcher = next(a for a in profiles.create_default_agents() if a.id == "researcher")
    assert "http_download" in researcher.tools


def test_default_primary_system_prompt_has_delegation_hint():
    """代码默认 primary system_prompt 含 agent 子代理委派提示。"""
    primary = next(a for a in profiles.create_default_agents() if a.id == "primary")
    assert "agent" in primary.system_prompt
    assert "委派" in primary.system_prompt or "子代理" in primary.system_prompt


def test_default_seed_coder_uses_current_tool_names():
    """代码默认 coder 工具白名单必须用 PR #381 重命名后的工具名。

    触发原因: PR #381 把 TerminalTool 重写为 BashTool (name="bash"),
    旧名 "terminal" 在 tools/ 已不存在。同时 file_read/file_write 是
    拼写错位(真实工具名是 read_file/write_file)。coder 硬编码若不修,
    UI 选 coder 后 LLM 看到的工具列表近乎为空。

    2026-09-04: 加入本地开发环境三件套 (runtime_probe / project_diagnose /
    runtime_exec) —— coder 是唯一拿 runtime_exec 的 agent（PR #396 coordinator/
    executor 边界 —— primary 不直接执行）。
    """
    coder = next(a for a in profiles.create_default_agents() if a.id == "coder")
    assert coder.tools == [
        "read_file", "write_file", "bash", "calculator",
        "runtime_probe", "project_diagnose", "runtime_exec",
    ]


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
# researcher http_download 升级
# ---------------------------------------------------------------------------


def test_legacy_researcher_gets_http_download_appended(monkeypatch):
    """旧 researcher 种子（含 web_search/web_fetch/memory_search，无 http_download）
    → ensure_default_agents 追加 http_download。"""
    legacy = ["web_search", "web_fetch", "memory_search"]
    stored = {
        "primary": {"id": "primary", "enabled": True, "tools": []},
        "researcher": {"id": "researcher", "enabled": True, "tools": list(legacy)},
    }
    repo = FakeRepo(stored)
    monkeypatch.setattr(profiles, "_repo_factory_for_tests", lambda: repo)
    profiles.ensure_default_agents()
    assert "http_download" in stored["researcher"]["tools"]
    # 既有的不能丢
    for t in legacy:
        assert t in stored["researcher"]["tools"]


def test_current_shape_researcher_untouched(monkeypatch):
    """已是当前形状（含 http_download）→ 绝不再追加（防重复写入 + updated_at 抖动）。"""
    current = ["web_search", "web_fetch", "http_download", "memory_search"]
    stored = {
        "primary": {"id": "primary", "enabled": True, "tools": []},
        "researcher": {"id": "researcher", "enabled": True, "tools": list(current)},
    }
    repo = FakeRepo(stored)
    monkeypatch.setattr(profiles, "_repo_factory_for_tests", lambda: repo)
    profiles.ensure_default_agents()
    assert sorted(stored["researcher"]["tools"]) == sorted(current)
    # 幂等性断言：与 test_current_primary_system_prompt_untouched 对称。
    # researcher 已是当前形状 → 不应再 upsert（避免 updated_at 抖动 + 无意义写盘）。
    researcher_upserts = [u for u in repo.upserts if u["id"] == "researcher"]
    assert researcher_upserts == [], f"researcher 不应被 upsert，但收到: {researcher_upserts}"


# ---------------------------------------------------------------------------
# primary system_prompt 升级（含 agent 子代理委派提示）
# ---------------------------------------------------------------------------


def test_legacy_primary_system_prompt_gets_upgraded(monkeypatch):
    """旧 primary system_prompt（无委派提示）→ 升级到 PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT。

    2026-09-03: chain migration 合并为单次 upsert, final state 是 WITH_FETCH_DIRECT
    (含直接 fetch/download 段 + 保留委派段)。"""
    stored = {
        "primary": {
            "id": "primary",
            "enabled": True,
            "tools": [],
            "system_prompt": profiles._PRIMARY_SYSTEM_PROMPT_BEFORE_DELEGATION,
        },
    }
    repo = FakeRepo(stored)
    monkeypatch.setattr(profiles, "_repo_factory_for_tests", lambda: repo)
    profiles.ensure_default_agents()
    assert stored["primary"]["system_prompt"] == profiles.PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT


def test_customized_primary_system_prompt_untouched(monkeypatch):
    """用户自定义过 primary system_prompt → 绝不自动覆盖。"""
    custom = "我是用户自定的 Sage 提示词，完全改写。"
    stored = {
        "primary": {
            "id": "primary",
            "enabled": True,
            "tools": [],
            "system_prompt": custom,
        },
    }
    repo = FakeRepo(stored)
    monkeypatch.setattr(profiles, "_repo_factory_for_tests", lambda: repo)
    profiles.ensure_default_agents()
    assert stored["primary"]["system_prompt"] == custom


def test_current_primary_system_prompt_untouched(monkeypatch):
    """已是当前形状（含 fetch_direct 提示）→ 绝不再覆写（防重复写入 + updated_at 抖动）。

    2026-09-03: '当前' 改为 PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT；WITH_DELEGATION
    已不再是 current, 见 test_primary_system_prompt_with_delegation_one_step_migration。"""
    stored = {
        "primary": {
            "id": "primary",
            "enabled": True,
            "tools": [],
            "system_prompt": profiles.PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT,
        },
    }
    repo = FakeRepo(stored)
    monkeypatch.setattr(profiles, "_repo_factory_for_tests", lambda: repo)
    profiles.ensure_default_agents()
    assert stored["primary"]["system_prompt"] == profiles.PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT
    # 应只发生"已有 primary 不插入"的写入 —— 即没有针对 primary 的 upsert
    primary_upserts = [u for u in repo.upserts if u["id"] == "primary"]
    assert primary_upserts == [], f"primary 不应被 upsert，但收到: {primary_upserts}"


# ---------------------------------------------------------------------------
# 跨迁移互不破坏（顺序敏感 + 互相独立）
# ---------------------------------------------------------------------------


def test_legacy_db_full_migration_chain(monkeypatch):
    """模拟最旧 DB：primary 缺 agent/todo，system_prompt 是旧版；researcher 缺
    http_download。一次 ensure_default_agents 应同时把所有升级到位。"""
    legacy_primary_tools = list(profiles._PRIMARY_TOOLS_BEFORE_AGENT)
    legacy_researcher_tools = list(profiles._RESEARCHER_TOOLS_BEFORE_HTTP_DOWNLOAD)
    stored = {
        "primary": {
            "id": "primary",
            "enabled": True,
            "tools": legacy_primary_tools,
            "system_prompt": profiles._PRIMARY_SYSTEM_PROMPT_BEFORE_DELEGATION,
        },
        "researcher": {
            "id": "researcher",
            "enabled": True,
            "tools": legacy_researcher_tools,
        },
    }
    repo = FakeRepo(stored)
    monkeypatch.setattr(profiles, "_repo_factory_for_tests", lambda: repo)
    profiles.ensure_default_agents()

    # primary 应完成两段升级 + system_prompt 升级
    assert "agent" in stored["primary"]["tools"]
    assert "todo_write" in stored["primary"]["tools"]
    # 2026-09-03: chain migration 合并, 终态是 WITH_FETCH_DIRECT
    assert stored["primary"]["system_prompt"] == profiles.PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT

    # researcher 应追加 http_download
    assert "http_download" in stored["researcher"]["tools"]


# ---------------------------------------------------------------------------
# primary 直接 fetch/download（§5, 2026-09-03）
# ---------------------------------------------------------------------------


def test_default_seed_primary_includes_fetch_download():
    """代码默认 primary 工具白名单含 web_fetch + http_download（§5 用户可见方向）。"""
    primary = next(a for a in profiles.create_default_agents() if a.id == "primary")
    assert "web_fetch" in primary.tools
    assert "http_download" in primary.tools


def test_default_seed_primary_uses_fetch_direct_prompt():
    """代码默认 primary system_prompt 升级为 PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT。

    保留委派段（含 "委派" / "子代理"）— 复杂研究仍走 agent 工具委派。
    新增直接 fetch/download 段 — 用户可见 LLM 行为, 便于分步指导。
    """
    primary = next(a for a in profiles.create_default_agents() if a.id == "primary")
    assert primary.system_prompt == profiles.PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT
    assert "委派" in primary.system_prompt or "子代理" in primary.system_prompt
    # 直接 fetch/download 段必须新增
    assert "web_fetch" in primary.system_prompt
    assert "http_download" in primary.system_prompt


def test_primary_system_prompt_legacy_two_step_chain_migration(monkeypatch):
    """DB system_prompt 是 _PRIMARY_SYSTEM_PROMPT_BEFORE_DELEGATION →
    一气呵成升级到 PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT (合并为单次 upsert)。
    """
    stored = {
        "primary": {
            "id": "primary", "enabled": True, "tools": [],
            "system_prompt": profiles._PRIMARY_SYSTEM_PROMPT_BEFORE_DELEGATION,
        },
    }
    repo = FakeRepo(stored)
    monkeypatch.setattr(profiles, "_repo_factory_for_tests", lambda: repo)
    profiles.ensure_default_agents()
    assert stored["primary"]["system_prompt"] == profiles.PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT
    # 链式合并: 仅 1 次 primary upsert (而不是 2 次)
    primary_upserts = [u for u in repo.upserts if u["id"] == "primary"]
    assert len(primary_upserts) == 1, f"应有 1 次 upsert（链式合并），收到 {len(primary_upserts)}"


def test_primary_system_prompt_with_delegation_one_step_migration(monkeypatch):
    """DB system_prompt 是 PRIMARY_SYSTEM_PROMPT_WITH_DELEGATION →
    一步升级到 PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT。
    """
    stored = {
        "primary": {
            "id": "primary", "enabled": True, "tools": [],
            "system_prompt": profiles.PRIMARY_SYSTEM_PROMPT_WITH_DELEGATION,
        },
    }
    repo = FakeRepo(stored)
    monkeypatch.setattr(profiles, "_repo_factory_for_tests", lambda: repo)
    profiles.ensure_default_agents()
    assert stored["primary"]["system_prompt"] == profiles.PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT
    primary_upserts = [u for u in repo.upserts if u["id"] == "primary"]
    assert len(primary_upserts) == 1


def test_primary_system_prompt_already_fetch_direct_no_upsert(monkeypatch):
    """DB system_prompt 已是 PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT → 0 upsert。"""
    stored = {
        "primary": {
            "id": "primary", "enabled": True, "tools": [],
            "system_prompt": profiles.PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT,
        },
    }
    repo = FakeRepo(stored)
    monkeypatch.setattr(profiles, "_repo_factory_for_tests", lambda: repo)
    profiles.ensure_default_agents()
    assert stored["primary"]["system_prompt"] == profiles.PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT
    primary_upserts = [u for u in repo.upserts if u["id"] == "primary"]
    assert primary_upserts == [], f"primary 不应被 upsert，但收到: {primary_upserts}"
