"""AgentTool 嵌套深度守卫（O5）单测。

- 深度达到上限 → execute_async 拒绝（subagent_depth_exceeded）
- 深度 0（conductor 上下文）→ 守卫放行（走到后续依赖缺失的错误面）
- depth 模块本身：置位/恢复、env 上限解析
"""

from __future__ import annotations

import pytest

from backend.orchestration.depth import (
    DEFAULT_MAX_SUBAGENT_DEPTH,
    current_subagent_depth,
    enter_subagent_depth,
    exit_subagent_depth,
    is_nesting_allowed,
    max_nested_subagent_depth,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------- depth module

def test_default_depth_is_zero():
    assert current_subagent_depth() == 0
    assert is_nesting_allowed() is True


def test_enter_exit_restores_depth():
    token = enter_subagent_depth(1)
    try:
        assert current_subagent_depth() == 1
        assert is_nesting_allowed() is False
    finally:
        exit_subagent_depth(token)
    assert current_subagent_depth() == 0
    assert is_nesting_allowed() is True


def test_env_override_raises_limit(monkeypatch):
    monkeypatch.setenv("SAGE_MAX_SUBAGENT_DEPTH", "3")
    assert max_nested_subagent_depth() == 3
    token = enter_subagent_depth(2)
    try:
        # 深度 2 < 上限 3 → 仍允许
        assert is_nesting_allowed() is True
    finally:
        exit_subagent_depth(token)


def test_env_invalid_falls_back(monkeypatch):
    monkeypatch.setenv("SAGE_MAX_SUBAGENT_DEPTH", "not-a-number")
    assert max_nested_subagent_depth() == DEFAULT_MAX_SUBAGENT_DEPTH
    monkeypatch.setenv("SAGE_MAX_SUBAGENT_DEPTH", "0")
    assert max_nested_subagent_depth() == DEFAULT_MAX_SUBAGENT_DEPTH


# ------------------------------------------------------------------ agent tool

@pytest.mark.asyncio()
async def test_agent_tool_refuses_at_depth_limit():
    """深度 1（编排子代理上下文）→ 拒绝派生，错误含 subagent_depth_exceeded。"""
    from backend.tools.agent_tool import AgentTool

    token = enter_subagent_depth(1)
    try:
        tool = AgentTool()
        result = await tool.execute_async(description="孙代理", prompt="深度攻击")
        assert result.success is False
        assert "subagent_depth_exceeded" in (result.error or "")
    finally:
        exit_subagent_depth(token)


@pytest.mark.asyncio()
async def test_agent_tool_allows_at_conductor_depth():
    """深度 0 → 守卫放行（走到 llm 缺失的既有错误面，证明守卫未拦截）。"""
    from unittest.mock import patch

    from backend.tools.agent_tool import AgentTool

    with patch(
        "backend.tools.agent_tool.build_llm_client_from_settings",
        return_value=None,
    ):
        tool = AgentTool()
        result = await tool.execute_async(description="合法委派", prompt="做点事")
    assert result.success is False
    assert "subagent_depth_exceeded" not in (result.error or "")
    assert "no_llm_configured" in (result.error or "")
