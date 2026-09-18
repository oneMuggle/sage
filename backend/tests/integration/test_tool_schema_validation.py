"""工具调用 schema 校验集成测试。

验证工具调用框架在 LLM 漏传 required 参数时返回友好错误，
而不是抛出 Python TypeError。

Issue: 2026-09-15 win7 安装包测试发现 office_read 工具报错
"execute() missing 1 required positional argument: 'doc_id'"，
原因是工具调用框架直接传 parameters 给 execute()，没有做 schema 校验。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.legacy.agent import SageAgent
from backend.core.legacy.agent_state import AgentState
from backend.core.legacy.llm_client import LLMResponse, LLMToolCall
from backend.data.settings_repo import SettingsRepository
from backend.domain.risk import RiskClass
from backend.services.permission_gate import (
    init_permission_gate,
    reset_permission_gate,
)
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.permissions import (
    PermissionEnforcer,
    PermissionMode,
)

pytestmark = pytest.mark.integration


class MockRequiredParamTool(BaseTool):
    """Mock 工具：有 required 参数。"""

    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="mock_required_param",
            description="Mock tool with required parameter",
            parameters={
                "type": "object",
                "properties": {
                    "required_field": {
                        "type": "string",
                        "description": "A required field",
                    },
                    "optional_field": {
                        "type": "string",
                        "description": "An optional field",
                    },
                },
                "required": ["required_field"],
            },
        )

    def execute(
        self,
        required_field: str,
        optional_field: str = "default",
        **kwargs,
    ) -> ToolResult:
        return ToolResult(
            success=True,
            content={
                "required": required_field,
                "optional": optional_field,
            },
        )


class MockNoRequiredTool(BaseTool):
    """Mock 工具：没有 required 参数。"""

    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="mock_no_required",
            description="Mock tool without required parameters",
            parameters={
                "type": "object",
                "properties": {
                    "optional_field": {
                        "type": "string",
                        "description": "An optional field",
                    },
                },
                "required": [],
            },
        )

    def execute(self, optional_field: str = "default", **kwargs) -> ToolResult:
        return ToolResult(
            success=True,
            content={"optional": optional_field},
        )


def _make_response(content: str = "", tool_calls=None) -> LLMResponse:
    return LLMResponse(content=content, tool_calls=tool_calls or [])


@pytest.fixture(autouse=True)
def _gate_lifecycle():
    """每个测试独立 gate, 防止跨测试挂起请求泄漏。"""
    reset_permission_gate()
    yield
    reset_permission_gate()


class TestToolSchemaValidation:
    """工具调用 schema 校验测试。"""

    def test_execute_tool_with_all_required_params_succeeds(self):
        """测试：LLM 传入所有 required 参数，工具调用成功。"""
        agent = SageAgent()
        agent.permission_enforcer = PermissionEnforcer(
            mode=PermissionMode.FULL_ACCESS,
            rules=[],
        )
        tool = MockRequiredParamTool()
        agent.tool_registry.register(tool)

        result = agent.execute_tool(
            "mock_required_param",
            {"required_field": "test_value"},
        )
        assert result["success"] is True
        assert result["content"]["required"] == "test_value"
        assert result["content"]["optional"] == "default"

    def test_execute_tool_with_optional_params_succeeds(self):
        """测试：LLM 传入 required + optional 参数，工具调用成功。"""
        agent = SageAgent()
        agent.permission_enforcer = PermissionEnforcer(
            mode=PermissionMode.FULL_ACCESS,
            rules=[],
        )
        tool = MockRequiredParamTool()
        agent.tool_registry.register(tool)

        result = agent.execute_tool(
            "mock_required_param",
            {"required_field": "test_value", "optional_field": "custom"},
        )
        assert result["success"] is True
        assert result["content"]["required"] == "test_value"
        assert result["content"]["optional"] == "custom"

    def test_execute_tool_missing_required_param_returns_friendly_error(self):
        """测试：LLM 漏传 required 参数，返回友好错误而不是抛异常。

        这是本次修复的核心场景：office_read 的 doc_id 是 required，
        LLM 漏传时应该返回友好错误，而不是 TypeError。
        """
        agent = SageAgent()
        agent.permission_enforcer = PermissionEnforcer(
            mode=PermissionMode.FULL_ACCESS,
            rules=[],
        )
        tool = MockRequiredParamTool()
        agent.tool_registry.register(tool)

        # LLM 漏传 required_field
        result = agent.execute_tool(
            "mock_required_param",
            {"optional_field": "custom"},  # 缺少 required_field
        )

        # 应该返回失败，但不是 Python 异常
        assert result["success"] is False
        assert "error" in result
        # 错误消息应该明确指出缺少的参数
        error_msg = result["error"].lower()
        assert "required_field" in error_msg or "必需" in error_msg or "required" in error_msg

    def test_execute_tool_with_no_required_params_and_empty_args_succeeds(self):
        """测试：工具没有 required 参数，LLM 传空参数，调用成功。"""
        agent = SageAgent()
        agent.permission_enforcer = PermissionEnforcer(
            mode=PermissionMode.FULL_ACCESS,
            rules=[],
        )
        tool = MockNoRequiredTool()
        agent.tool_registry.register(tool)

        result = agent.execute_tool("mock_no_required", {})
        assert result["success"] is True
        assert result["content"]["optional"] == "default"

    def test_execute_tool_missing_multiple_required_params(self):
        """测试：工具多个 required 参数，LLM 漏传多个，错误消息列出所有缺失参数。"""

        class MultiRequiredTool(BaseTool):
            risk = RiskClass.READ

            def _build_schema(self) -> ToolSchema:
                return ToolSchema(
                    name="mock_multi_required",
                    description="Mock tool with multiple required parameters",
                    parameters={
                        "type": "object",
                        "properties": {
                            "field_a": {"type": "string"},
                            "field_b": {"type": "string"},
                            "field_c": {"type": "string"},
                        },
                        "required": ["field_a", "field_b", "field_c"],
                    },
                )

            def execute(
                self, field_a: str, field_b: str, field_c: str, **kwargs
            ) -> ToolResult:
                return ToolResult(success=True, content={})

        agent = SageAgent()
        agent.permission_enforcer = PermissionEnforcer(
            mode=PermissionMode.FULL_ACCESS,
            rules=[],
        )
        tool = MultiRequiredTool()
        agent.tool_registry.register(tool)

        # LLM 只传了 field_a，漏传 field_b 和 field_c
        result = agent.execute_tool(
            "mock_multi_required",
            {"field_a": "value_a"},
        )

        assert result["success"] is False
        assert "error" in result
        # 错误消息应该提到缺失的参数
        error_lower = result["error"].lower()
        assert "field_b" in error_lower or "field_c" in error_lower or "必需" in error_lower

    def test_execute_tool_with_extra_unknown_params_ignored(self):
        """测试：LLM 传了未知参数，工具调用成功（未知参数被忽略）。"""
        agent = SageAgent()
        agent.permission_enforcer = PermissionEnforcer(
            mode=PermissionMode.FULL_ACCESS,
            rules=[],
        )
        tool = MockRequiredParamTool()
        agent.tool_registry.register(tool)

        result = agent.execute_tool(
            "mock_required_param",
            {
                "required_field": "test_value",
                "unknown_field": "ignored",  # 未知参数
            },
        )
        assert result["success"] is True
        assert result["content"]["required"] == "test_value"


class TestRunLoopSchemaValidation:
    """run_loop 中 schema 校验测试。"""

    @pytest.mark.asyncio()
    async def test_run_loop_missing_required_param_returns_friendly_error(self):
        """测试：run_loop 中 LLM 漏传 required 参数，返回友好错误。"""
        SettingsRepository().set("permission_mode", "full_access")
        init_permission_gate()

        agent = SageAgent()
        tool = MockRequiredParamTool()
        agent.tool_registry.register(tool)

        # Mock LLM：第一次返回工具调用（漏传 required_field），第二次返回终答
        agent.llm_client = MagicMock()
        agent.llm_client.chat = AsyncMock(
            side_effect=[
                _make_response(
                    content="",
                    tool_calls=[
                        LLMToolCall(
                            id="call_1",
                            name="mock_required_param",
                            arguments=json.dumps({"optional_field": "custom"}),  # 漏传 required_field
                        )
                    ],
                ),
                _make_response(content="执行完毕"),
            ]
        )

        events = []
        async for evt in agent.run_loop([{"role": "user", "content": "测试"}]):
            events.append(evt)

        # 应该有一个 OBSERVING 事件，包含错误信息
        observing_events = [
            e for e in events if e.state == AgentState.OBSERVING and e.tool_result is not None
        ]
        assert len(observing_events) > 0

        # 错误消息应该友好，不是 Python TypeError
        tool_result = observing_events[0].tool_result
        assert tool_result is not None
        assert tool_result.is_error is True
        error_msg = tool_result.content.lower()
        assert "required_field" in error_msg or "必需" in error_msg or "required" in error_msg
        # 不应该是 Python TypeError 消息格式
        assert "missing 1 required positional argument" not in error_msg
