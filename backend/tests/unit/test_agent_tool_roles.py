"""M3.1: ``agent`` 工具 ``subagent_type`` 角色注册表测试。

覆盖：
- 默认/内置/未知 角色解析
- schema 枚举包含内置三角色；DB profile 角色可列出
- explore/plan 只读；general-purpose 含写/命令；profile 按 tools 白名单过滤
- 未知显式类型返回错误；plan 角色注入规划 system prompt
"""

from __future__ import annotations

import pytest

from backend.core.legacy.agent_state import AgentEvent, AgentState
from backend.tools import agent_tool as agent_tool_module
from backend.tools.agent_tool import AgentTool
from backend.tools.subagent_roles import (
    BUILTIN_ROLES,
    PLAN_SYSTEM_PROMPT,
    resolve_subagent_role,
)

pytestmark = pytest.mark.unit


def _tool() -> AgentTool:
    return AgentTool(llm_client=object())


def test_resolve_default_is_explore():
    role, known = resolve_subagent_role(None)
    assert known is True
    assert role.kind == "explore"
    assert role.role_id == "explore"


def test_resolve_builtin_roles():
    for key in ("explore", "plan", "general-purpose"):
        role, known = resolve_subagent_role(key)
        assert known is True
        assert role.role_id == key
    assert resolve_subagent_role("PLAN")[0].kind == "plan"


def test_resolve_unknown_returns_explore_but_not_known():
    role, known = resolve_subagent_role("does-not-exist")
    assert known is False
    assert role.role_id == "explore"


def test_unknown_subagent_type_returns_error():
    result = _tool().execute(
        description="d", prompt="p", subagent_type="does-not-exist"
    )
    assert result.success is False
    assert "unknown_subagent_type" in (result.error or "")


def test_schema_enum_contains_builtin_roles():
    schema = _tool().schema
    prop = schema.parameters["properties"]["subagent_type"]
    enum = prop["enum"]
    for key in ("explore", "plan", "general-purpose"):
        assert key in enum
    assert "可选子代理角色" in prop["description"]


def test_schema_includes_enabled_db_profile(monkeypatch):
    profile = {
        "id": "researcher-x",
        "name": "Researcher X",
        "description": "检索专家",
        "enabled": True,
        "role": "specialist",
    }
    from backend.tools import subagent_roles

    original = subagent_roles.list_subagent_roles

    def _fake_list(max_profiles=12):
        return original(max_profiles) + [subagent_roles._profile_role(profile)]

    monkeypatch.setattr(subagent_roles, "list_subagent_roles", _fake_list)
    monkeypatch.setattr(
        agent_tool_module, "schema_role_options", subagent_roles.schema_role_options
    )
    schema = _tool().schema
    enum = schema.parameters["properties"]["subagent_type"]["enum"]
    assert "researcher-x" in enum
    assert "检索专家" in schema.parameters["properties"]["subagent_type"]["description"]


def test_explore_registry_is_readonly():
    tool = _tool()
    registry = tool._build_role_registry(BUILTIN_ROLES["explore"])
    names = set(registry.list_names())
    assert "read_file" in names
    assert "write_file" not in names
    assert "bash" not in names


def test_plan_registry_is_readonly():
    tool = _tool()
    registry = tool._build_role_registry(BUILTIN_ROLES["plan"])
    names = set(registry.list_names())
    assert "read_file" in names
    assert "write_file" not in names


def test_general_registry_has_write_and_bash():
    tool = _tool()
    registry = tool._build_role_registry(BUILTIN_ROLES["general-purpose"])
    names = set(registry.list_names())
    assert "write_file" in names
    assert "edit_file" in names
    assert "apply_patch" in names
    assert "bash" in names


def test_profile_registry_filters_by_whitelist():
    from backend.tools.subagent_roles import SubagentRole

    role = SubagentRole(
        role_id="reader",
        label="Reader",
        description="read only",
        kind="profile",
        profile={"id": "reader", "tools": ["read_file", "list_dir"]},
    )
    tool = _tool()
    registry = tool._build_role_registry(role)
    assert set(registry.list_names()) == {"read_file", "list_dir"}


def test_profile_without_tools_defaults_readonly():
    from backend.tools.subagent_roles import SubagentRole

    role = SubagentRole(
        role_id="plain",
        label="Plain",
        description="",
        kind="profile",
        profile={"id": "plain"},
    )
    registry = _tool()._build_role_registry(role)
    names = set(registry.list_names())
    assert "read_file" in names
    assert "write_file" not in names


class _CapturingSubagent:
    def __init__(self) -> None:
        self.messages = []

    async def run_loop(self, messages, **kwargs):
        self.messages = list(messages)
        yield AgentEvent(state=AgentState.DONE, content="ok", agent_id="subagent")


@pytest.mark.asyncio()
async def test_plan_role_injects_planning_prompt():
    captured = _CapturingSubagent()
    tool = AgentTool(
        llm_client=object(),
        subagent_factory=lambda registry: captured,
    )
    answer, error = await tool._run_subagent_async(
        object(),
        "规划任务",
        "给出重构计划",
        role=BUILTIN_ROLES["plan"],
    )
    assert error is None
    assert answer == "ok"
    assert captured.messages[0] == {"role": "system", "content": PLAN_SYSTEM_PROMPT}


@pytest.mark.asyncio()
async def test_default_role_keeps_explore_prompt():
    captured = _CapturingSubagent()
    tool = AgentTool(
        llm_client=object(),
        subagent_factory=lambda registry: captured,
    )
    await tool._run_subagent_async(object(), "调研", "查资料")
    assert captured.messages[0]["content"].startswith(
        "You are a focused Sage sub-agent"
    )


def test_role_max_iterations_used_when_profile_provides():
    from backend.tools.subagent_roles import SubagentRole, role_max_iterations

    role = SubagentRole(
        role_id="p",
        label="P",
        description="",
        kind="profile",
        profile={"id": "p", "max_iterations": 9},
    )
    assert role_max_iterations(role) == 9
    assert role_max_iterations(BUILTIN_ROLES["explore"]) is None
