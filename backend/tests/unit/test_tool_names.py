"""domain.tool_names 与 register_all_tools 实际注册面的一致性验收（T3 防漂移）。

``ALL_BUILTIN_TOOL_NAMES`` 是启动期白名单校验的已知名集合 —— 若它漏掉
某个实际注册的工具，该工具会被合法白名单误告警；若它多出幽灵名字，
漂移检测就出现盲区。本文件把它钉死在注册面上。
"""

from __future__ import annotations

import pytest

from backend.agents.profiles import validate_profile_tools
from backend.domain.network_policy import NetworkPolicy
from backend.domain.tool_names import (
    ALL_BUILTIN_TOOL_NAMES,
    EXEC_TOOLS,
    PLUGIN_TOOL_PREFIX,
    is_plugin_tool_name,
    is_plugin_tool_reference,
    is_plugin_tool_wildcard,
    plugin_tool_belongs_to_plugin,
    plugin_tool_wildcard_for_plugin,
    tool_name_in_allowlist,
)
from backend.domain.tool_policy import ToolPolicy
from backend.tools import ToolRegistry, register_all_tools

pytestmark = pytest.mark.unit


def _registered_names() -> set:
    registry = ToolRegistry()
    register_all_tools(registry, policy=ToolPolicy(), network_policy=NetworkPolicy())
    return set(registry.list_names())


def test_all_builtin_names_match_registry():
    """清单 == register_all_tools 实际注册面（NetworkPolicy() 默认 ONLINE，
    出网三件套全注册）。新增内置工具漏更新 tool_names.py 时在此失败。"""
    assert set(ALL_BUILTIN_TOOL_NAMES) == _registered_names()


def test_exec_tools_trio_shape():
    """bash 三件套顺序与成员冻结 —— 暴露 bash 的白名单必须三件齐备。"""
    assert EXEC_TOOLS == ("bash", "bash_output", "kill_shell")


def test_profile_seeds_within_known_names():
    """全部默认 agent 种子白名单 ⊆ 已知名集合（防种子里的拼写漂移回归）。"""
    from backend.agents.profiles import create_default_agents

    for agent in create_default_agents():
        unknown = set(agent.tools) - set(ALL_BUILTIN_TOOL_NAMES)
        assert not unknown, f"{agent.id} 引用未注册名: {unknown}"


_PLUGIN_TOOL = "plugin__demo__hello"


def test_builtin_names_never_use_plugin_namespace():
    """动态插件命名空间不得混进静态内置清单（R92 通配只匹配插件面）。"""
    assert not any(
        name.startswith(PLUGIN_TOOL_PREFIX) for name in ALL_BUILTIN_TOOL_NAMES
    )


def test_plugin_tool_reference_shapes():
    """R92 只承认精确插件名与两种受限通配形状。"""
    assert is_plugin_tool_name(_PLUGIN_TOOL) is True
    assert is_plugin_tool_name("plugin__demo__*") is False
    assert is_plugin_tool_wildcard("plugin__*") is True
    assert is_plugin_tool_wildcard("plugin__demo__*") is True
    assert is_plugin_tool_reference(_PLUGIN_TOOL) is True
    assert is_plugin_tool_reference("plugin__demo__*") is True


def test_plugin_wildcard_derivation_from_authoritative_name():
    """R95 只能由合法插件名派生单个插件的受限通配。"""
    assert plugin_tool_wildcard_for_plugin("demo") == "plugin__demo__*"
    assert (
        plugin_tool_wildcard_for_plugin("demo-plugin")
        == "plugin__demo-plugin__*"
    )
    assert plugin_tool_belongs_to_plugin(_PLUGIN_TOOL, "demo") is True
    assert plugin_tool_belongs_to_plugin(_PLUGIN_TOOL, "other") is False
    assert plugin_tool_belongs_to_plugin("plugin__demo__*", "demo") is False
    assert plugin_tool_belongs_to_plugin("bash", "demo") is False


@pytest.mark.parametrize(
    "plugin_name", ["", "*", "de mo", "demo?", "demo[1]", None, 123]
)
def test_plugin_wildcard_derivation_rejects_unsafe_names(plugin_name):
    assert plugin_tool_wildcard_for_plugin(plugin_name) is None
    assert plugin_tool_belongs_to_plugin(_PLUGIN_TOOL, plugin_name) is False


@pytest.mark.parametrize(
    "entry",
    [
        "plugin__demo",
        "plugin__demo__",
        "plugin____hello",
        "plugin__demo*",
        "plugin__demo__**",
        "plugin__*__hello",
        "plugin__de mo__*",
        "*",
        "memory_*",
        "mcp__server__*",
        None,
        123,
    ],
)
def test_plugin_tool_reference_rejects_other_shapes(entry):
    assert is_plugin_tool_reference(entry) is False


def test_allowlist_matcher_exact_and_legacy_semantics():
    assert tool_name_in_allowlist("bash", None) is True  # None = 无白名单
    assert tool_name_in_allowlist("bash", []) is False  # [] = 不暴露任何工具
    assert tool_name_in_allowlist("bash", ["bash"]) is True
    assert tool_name_in_allowlist(_PLUGIN_TOOL, [_PLUGIN_TOOL]) is True
    assert tool_name_in_allowlist("bash", ["read_file"]) is False
    # 坏条目不崩溃、不放宽，其后的合法条目仍生效
    assert tool_name_in_allowlist("bash", [None, 123, "bash"]) is True
    assert tool_name_in_allowlist("bash", [None, 123]) is False
    assert tool_name_in_allowlist(None, ["bash"]) is False


def test_allowlist_matcher_plugin_wildcards():
    assert tool_name_in_allowlist(_PLUGIN_TOOL, ["plugin__*"]) is True
    assert tool_name_in_allowlist(_PLUGIN_TOOL, ["plugin__demo__*"]) is True
    assert (
        tool_name_in_allowlist("plugin__demo__a__b", ["plugin__demo__*"]) is True
    )
    assert tool_name_in_allowlist(_PLUGIN_TOOL, ["plugin__other__*"]) is False
    assert (
        tool_name_in_allowlist("plugin__demo2__hello", ["plugin__demo__*"])
        is False
    )
    # 通配只匹配合法插件工具形状，不匹配残缺名/内置/MCP
    assert tool_name_in_allowlist("plugin__demo", ["plugin__*"]) is False
    assert tool_name_in_allowlist("memory_search", ["plugin__*"]) is False
    assert tool_name_in_allowlist("mcp__server__tool", ["plugin__*"]) is False
    # 插件名含 __ 的既有拼接歧义：按命名空间前缀做文本匹配（如实记录）
    assert (
        tool_name_in_allowlist("plugin__a__b__c", ["plugin__a__*"]) is True
    )


@pytest.mark.parametrize(
    "pattern", ["*", "memory_*", "mcp__*", "plugin__demo*", "plugin__*__hello"]
)
def test_allowlist_matcher_never_expands_generic_globs(pattern):
    assert tool_name_in_allowlist("memory_search", [pattern]) is False
    assert tool_name_in_allowlist(_PLUGIN_TOOL, [pattern]) is False


def test_validate_profile_tools_warns_on_unknown(monkeypatch):
    """validate_profile_tools 对未注册名告警并计数，合法白名单零告警。"""

    class FakeRepo:
        def __init__(self, stored):
            self.stored = stored

        def list_all(self):
            return list(self.stored)

    repo = FakeRepo(
        [
            {"id": "legacy", "tools": ["terminal", "read_file"]},  # 旧名 terminal
            {"id": "ok", "tools": ["bash", "list_dir"]},
            {"id": "empty", "tools": []},
            # R92：合法插件精确名/通配是已知动态引用，不告警
            {
                "id": "plugin-ok",
                "tools": ["plugin__demo__hello", "plugin__demo__*", "plugin__*"],
            },
            # 无效通配写法仍按未注册名告警，帮助发现拼写错误
            {"id": "plugin-bad", "tools": ["plugin__demo*"]},
        ]
    )
    assert validate_profile_tools(repo) == 2
