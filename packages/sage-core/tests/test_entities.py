"""sage-core 单元测试。"""

from __future__ import annotations

import pytest
from sage_core import (
    AgentState,
    AgentDecision,
    Message,
    Role,
    ToolCall,
    SkillSpec,
    SkillResult,
)
from sage_core.exceptions import AgentError, ValidationError


class TestAgentState:
    """测试 Agent 状态机。"""

    def test_initial_state(self):
        """测试初始状态。"""
        state = AgentState.initial()
        assert state == AgentState.IDLE

    def test_valid_transitions(self):
        """测试合法状态转换。"""
        # IDLE → THINKING
        assert AgentState.IDLE.can_transition_to(AgentState.THINKING)

        # THINKING → ACTING
        assert AgentState.THINKING.can_transition_to(AgentState.ACTING)

        # ACTING → OBSERVING
        assert AgentState.ACTING.can_transition_to(AgentState.OBSERVING)

        # OBSERVING → THINKING
        assert AgentState.OBSERVING.can_transition_to(AgentState.THINKING)

    def test_invalid_transitions(self):
        """测试非法状态转换。"""
        # IDLE 不能直接到 ACTING
        assert not AgentState.IDLE.can_transition_to(AgentState.ACTING)

        # DONE 是终态
        assert not AgentState.DONE.can_transition_to(AgentState.IDLE)

        # FAILED 是终态
        assert not AgentState.FAILED.can_transition_to(AgentState.IDLE)


class TestAgentDecision:
    """测试 Agent 决策。"""

    def test_create_decision(self):
        """测试创建决策。"""
        decision = AgentDecision(
            state=AgentState.ACTING,
            action_name="search_web",
            action_args={"query": "Python tutorial"},
        )

        assert decision.state == AgentState.ACTING
        assert decision.action_name == "search_web"
        assert decision.action_args == {"query": "Python tutorial"}

    def test_immutable_decision(self):
        """测试决策不可变性。"""
        decision = AgentDecision(state=AgentState.THINKING)

        with pytest.raises(AttributeError):
            decision.state = AgentState.ACTING  # type: ignore


class TestMessage:
    """测试消息系统。"""

    def test_create_user_message(self):
        """测试创建用户消息。"""
        msg = Message(role=Role.USER, content="你好")

        assert msg.role == Role.USER
        assert msg.content == "你好"
        assert msg.tool_calls == []
        assert msg.tool_call_id is None

    def test_create_tool_call(self):
        """测试创建工具调用。"""
        tool_call = ToolCall(
            name="get_weather",
            args={"city": "北京"},
            id="call_123",
        )

        assert tool_call.name == "get_weather"
        assert tool_call.args == {"city": "北京"}
        assert tool_call.id == "call_123"

    def test_create_assistant_message_with_tool_calls(self):
        """测试创建带工具调用的助手消息。"""
        tool_call = ToolCall(name="search", args={"q": "test"})
        msg = Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[tool_call],
        )

        assert msg.role == Role.ASSISTANT
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].name == "search"


class TestSkillSpec:
    """测试技能规格。"""

    def test_create_skill_spec(self):
        """测试创建技能规格。"""
        spec = SkillSpec(
            name="web_search",
            description="搜索网页",
            triggers=["搜索", "查找"],
            parameters={"query": {"type": "string"}},
            examples=["搜索 Python 教程"],
        )

        assert spec.name == "web_search"
        assert spec.description == "搜索网页"
        assert "搜索" in spec.triggers
        assert "query" in spec.parameters


class TestSkillResult:
    """测试技能结果。"""

    def test_create_success_result(self):
        """测试创建成功结果。"""
        result = SkillResult(
            success=True,
            content="搜索结果...",
            metadata={"count": 10},
        )

        assert result.success is True
        assert result.content == "搜索结果..."
        assert result.metadata == {"count": 10}
        assert result.error is None

    def test_create_error_result(self):
        """测试创建错误结果。"""
        result = SkillResult(
            success=False,
            content=None,
            error="搜索失败",
        )

        assert result.success is False
        assert result.error == "搜索失败"


class TestExceptions:
    """测试异常类。"""

    def test_agent_error(self):
        """测试 Agent 错误。"""
        error = AgentError("Agent 执行失败")
        assert str(error) == "Agent 执行失败"
        assert isinstance(error, Exception)

    def test_validation_error(self):
        """测试验证错误。"""
        error = ValidationError("无效的参数")
        assert str(error) == "无效的参数"
        assert isinstance(error, Exception)
