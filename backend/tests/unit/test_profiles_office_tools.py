"""Office 工具的 profile 可见性契约。

背景: office_create 于 2026-08-03 落地, 而 profile 白名单过滤 2026-08-01
才生效 —— 五个 office 工具从来没进过任何 profile 的 tools 列表, LLM 一直
看不见, 而 system prompt 已在声明这些能力。本文件锁住:

- primary 能看到全部 office 工具
- writer 能看到读写四件套, 但看不到 delete
- coder / researcher / memory_manager / reviewer 看不到任何 office 工具
- 未绑定工作区时 office_list / office_read 自动隐藏(requires_tool_context)
"""

from __future__ import annotations

import pytest

from backend.agents.profiles import create_default_agents
from backend.tools import ToolRegistry, register_all_tools
from backend.tools.context import ToolExecutionContext

pytestmark = pytest.mark.unit


@pytest.fixture()
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    register_all_tools(reg)
    return reg


@pytest.fixture()
def bound_ctx() -> ToolExecutionContext:
    """模拟已绑定工作区的 chat turn。"""
    return ToolExecutionContext(
        session_id="sess-vis",
        stream_id="stream-vis",
        binding_generation=1,
        office_doc_scope=frozenset(),
    )


def _profile(agent_id: str):
    return next(p for p in create_default_agents() if p.id == agent_id)


def _visible_office_tools(registry, ctx, allowed_tools):
    return sorted(
        s["name"]
        for s in registry.get_schemas_for_llm(context=ctx, allowed_tools=allowed_tools)
        if s["name"].startswith("office_")
    )


def test_primary_sees_all_office_tools(registry, bound_ctx):
    visible = _visible_office_tools(registry, bound_ctx, _profile("primary").tools)
    # 2026-09-04: PR-2 (archive/restore) 给 primary 加了 office_restore, 测试同步更新。
    assert visible == [
        "office_create",
        "office_delete",
        "office_list",
        "office_read",
        "office_restore",
        "office_update",
    ]


def test_writer_sees_read_write_but_not_delete(registry, bound_ctx):
    visible = _visible_office_tools(registry, bound_ctx, _profile("writer").tools)
    # 2026-09-04: PR-2 (archive/restore) 给 writer 加了 office_restore, 测试同步更新。
    assert visible == ["office_create", "office_list", "office_read", "office_restore", "office_update"]
    assert "office_delete" not in visible


@pytest.mark.parametrize("agent_id", ["coder", "researcher", "memory_manager", "reviewer"])
def test_other_profiles_see_no_office_tools(registry, bound_ctx, agent_id):
    assert _visible_office_tools(registry, bound_ctx, _profile(agent_id).tools) == []


def test_list_and_read_hidden_without_workspace_binding(registry):
    """未绑定工作区(context=None) → requires_tool_context 的工具自动隐藏。

    office_create / office_update / office_delete 的 requires_tool_context 是
    False(它们支持 file_path 模式), 所以仍可见 —— 这是有意的。
    """
    visible = _visible_office_tools(registry, None, _profile("primary").tools)
    assert visible == ["office_create", "office_delete", "office_update"]


def test_office_tools_are_in_current_default_constants():
    """白名单与差集迁移常量必须同步, 否则存量 DB 补不到 office 工具。"""
    from backend.agents import profiles

    primary_tools = set(_profile("primary").tools)
    assert primary_tools == set(profiles._PRIMARY_CURRENT_DEFAULT_TOOLS), (
        "primary 种子与 _PRIMARY_CURRENT_DEFAULT_TOOLS 不一致 —— "
        "存量 DB 会补不齐 office 工具"
    )
    writer_tools = set(_profile("writer").tools)
    assert writer_tools == set(profiles._WRITER_CURRENT_DEFAULT_TOOLS)
