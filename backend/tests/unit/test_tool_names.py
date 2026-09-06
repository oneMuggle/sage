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
            {"id": "ok", "tools": ["bash", "calculator"]},
            {"id": "empty", "tools": []},
        ]
    )
    assert validate_profile_tools(repo) == 1
