"""
SageAgent profile 接通测试（阶段 1）

验证:
1. SageAgent() 默认行为不变（向后兼容）
2. SageAgent(agent_id=...) 从 SQLite 读取 profile 并消费 system_prompt
3. enabled=False 的 agent_id 被拒绝（回退到默认 profile，不抛异常）
4. agent_id 不存在 → 同样回退到默认
5. profile.max_iterations 覆盖 run_loop 默认值
6. get_enabled_agent() 工具函数行为
7. AgentEvent 携带 agent_id 字段（为阶段 4 预留）
"""

from __future__ import annotations

from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.agents.profiles import get_enabled_agent
from backend.core.legacy.agent import SageAgent
from backend.core.legacy.agent_state import AgentState
from backend.core.legacy.llm_client import LLMResponse
from backend.data.agent_repo import AgentRepository

pytestmark = pytest.mark.unit


def _make_response(content: str = "", tool_calls: Optional[list] = None) -> LLMResponse:
    return LLMResponse(content=content, tool_calls=tool_calls or [])


# =============================================================================
# get_enabled_agent() 工具函数
# =============================================================================


def test_get_enabled_agent_returns_profile_for_primary():
    """primary agent 默认启用，应返回 profile dict。"""
    profile = get_enabled_agent("primary")
    assert profile is not None
    assert profile["id"] == "primary"
    assert profile["enabled"] is True


def test_get_enabled_agent_returns_none_for_disabled():
    """disabled 的 agent 应返回 None。"""
    repo = AgentRepository()
    repo.set_enabled("primary", False)

    profile = get_enabled_agent("primary")
    assert profile is None

    # 恢复
    repo.set_enabled("primary", True)


def test_get_enabled_agent_returns_none_for_missing():
    """不存在的 agent_id 应返回 None。"""
    profile = get_enabled_agent("nonexistent-agent-xyz")
    assert profile is None


# =============================================================================
# SageAgent 接受 agent_id 参数
# =============================================================================


def test_sage_agent_default_has_no_profile():
    """无参数时 SageAgent.profile 为 None（向后兼容）。"""
    agent = SageAgent()
    assert agent.profile is None


def test_sage_agent_with_agent_id_loads_profile_from_db():
    """传 agent_id 时，从 SQLite 加载 profile。"""
    agent = SageAgent(agent_id="primary")
    assert agent.profile is not None
    assert agent.profile["id"] == "primary"
    assert "system_prompt" in agent.profile


def test_sage_agent_with_disabled_agent_id_falls_back_to_none():
    """传 disabled agent_id 时，profile 回退到 None（不抛异常）。"""
    repo = AgentRepository()
    repo.set_enabled("coder", False)
    try:
        agent = SageAgent(agent_id="coder")
        assert agent.profile is None
    finally:
        repo.set_enabled("coder", True)


def test_sage_agent_with_missing_agent_id_falls_back_to_none():
    """传不存在的 agent_id 时，profile 回退到 None（不抛异常）。"""
    agent = SageAgent(agent_id="nonexistent-xyz")
    assert agent.profile is None


# =============================================================================
# system_prompt 从 profile 读取 (chat() 路径, 通过 _call_llm)
#
# 注: run_loop 不负责注入 system_prompt (由调用方 producer 构造 messages 时
# 负责), 所以这里测的是 chat() 同步路径 — 它内部调 _call_llm 注入 system_prompt。
# 阶段 2 会改 /chat/stream producer 也从 profile 读, 那时再加对应测试。
# =============================================================================


@pytest.mark.asyncio()
async def test_sage_agent_call_llm_uses_profile_system_prompt():
    """_call_llm 调用 LLM 时, 第一条 system message 应是 profile.system_prompt。"""
    repo = AgentRepository()
    custom_prompt = "你是一个专业的研究助手，只输出研究报告格式的内容。"
    repo.update("primary", {"system_prompt": custom_prompt})

    agent = SageAgent(agent_id="primary")
    agent.llm_client = MagicMock()

    captured_messages = {}

    async def capture_chat(messages, **kwargs):
        captured_messages["messages"] = messages
        return _make_response(content="ok")

    agent.llm_client.chat = AsyncMock(side_effect=capture_chat)

    await agent._call_llm("hi", memory_context="")

    assert "messages" in captured_messages
    first_msg = captured_messages["messages"][0]
    assert first_msg["role"] == "system"
    assert first_msg["content"] == custom_prompt


@pytest.mark.asyncio()
async def test_sage_agent_call_llm_default_system_prompt_when_no_agent_id():
    """无 agent_id 时, _call_llm 使用 build_system_base() 构建默认提示（含 agent 列表）。"""
    agent = SageAgent()
    agent.llm_client = MagicMock()

    captured_messages = {}

    async def capture_chat(messages, **kwargs):
        captured_messages["messages"] = messages
        return _make_response(content="ok")

    agent.llm_client.chat = AsyncMock(side_effect=capture_chat)

    await agent._call_llm("hi", memory_context="")

    first_msg = captured_messages["messages"][0]
    assert first_msg["role"] == "system"
    # 默认 system prompt 以身份开头，并包含 agent 列表
    assert first_msg["content"].startswith("你是 Sage，一个智能 AI 助手。")
    assert "可用 Agent" in first_msg["content"]


@pytest.mark.asyncio()
async def test_sage_agent_call_llm_appends_memory_context_to_system_prompt():
    """_call_llm 应把 memory_context 拼到 system_prompt 之后。"""
    agent = SageAgent()
    agent.llm_client = MagicMock()

    captured_messages = {}

    async def capture_chat(messages, **kwargs):
        captured_messages["messages"] = messages
        return _make_response(content="ok")

    agent.llm_client.chat = AsyncMock(side_effect=capture_chat)

    await agent._call_llm("hi", memory_context="用户喜欢咖啡")

    first_msg = captured_messages["messages"][0]
    assert first_msg["role"] == "system"
    assert first_msg["content"].startswith("你是 Sage，一个智能 AI 助手。")
    assert "用户喜欢咖啡" in first_msg["content"]


# =============================================================================
# profile.max_iterations 覆盖默认值
# =============================================================================


@pytest.mark.asyncio()
async def test_sage_agent_profile_max_iterations_used_when_not_overridden():
    """run_loop 不传 max_iterations 时，使用 profile 的值。"""
    repo = AgentRepository()
    repo.update("coder", {"max_iterations": 7})

    agent = SageAgent(agent_id="coder")

    from backend.core.legacy.llm_client import LLMToolCall

    tool_call = LLMToolCall(id="c", name="calc", arguments="{}")
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(return_value=_make_response(tool_calls=[tool_call]))

    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(return_value=MagicMock(success=True, content={}, error=None))
    agent.tool_registry.get = MagicMock(return_value=mock_tool)

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}]):
        events.append(evt)

    failed = [e for e in events if e.state == AgentState.FAILED]
    assert len(failed) == 1
    assert failed[0].iteration == 7


@pytest.mark.asyncio()
async def test_sage_agent_explicit_max_iterations_overrides_profile():
    """run_loop 显式传 max_iterations 时，覆盖 profile 的值。"""
    repo = AgentRepository()
    repo.update("coder", {"max_iterations": 10})

    agent = SageAgent(agent_id="coder")

    from backend.core.legacy.llm_client import LLMToolCall

    tool_call = LLMToolCall(id="c", name="calc", arguments="{}")
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(return_value=_make_response(tool_calls=[tool_call]))

    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(return_value=MagicMock(success=True, content={}, error=None))
    agent.tool_registry.get = MagicMock(return_value=mock_tool)

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}], max_iterations=3):
        events.append(evt)

    failed = [e for e in events if e.state == AgentState.FAILED]
    assert len(failed) == 1
    assert failed[0].iteration == 3


# =============================================================================
# agent_id 透传到事件（为阶段 4 预留）
# =============================================================================


@pytest.mark.asyncio()
async def test_sage_agent_events_carry_agent_id_when_loaded():
    """传 agent_id 时，每个事件都携带该 agent_id。"""
    agent = SageAgent(agent_id="primary")
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(return_value=_make_response(content="ok"))

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "hi"}]):
        events.append(evt)

    for evt in events:
        assert evt.agent_id == "primary"


@pytest.mark.asyncio()
async def test_sage_agent_events_carry_none_when_no_agent_id():
    """无 agent_id 时，事件的 agent_id 为 None（向后兼容）。"""
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(return_value=_make_response(content="ok"))

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "hi"}]):
        events.append(evt)

    for evt in events:
        assert evt.agent_id is None
