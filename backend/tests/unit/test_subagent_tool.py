"""dispatch_subagents 工具单元测试。

- schema 名称/参数钳制（minItems 1 / maxItems 4 / goal maxLength 2000）
- execute_async 委托 dispatcher.dispatch 并包装 ToolResult
- execute() 同步调用返回明确错误（提示走 run_loop special-case）
- run_loop 对 dispatch_subagents 走 execute_async（而非同步 execute）
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.tools.subagent_tool import INPUT_SCHEMA, DispatchSubagentsTool


def _make_dispatcher(aggregated: str = "聚合结果"):
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=aggregated)
    return dispatcher


class TestSchema:
    def test_schema_name_and_parameters(self):
        tool = DispatchSubagentsTool(_make_dispatcher())
        assert tool.name == "dispatch_subagents"
        assert tool.schema.parameters == INPUT_SCHEMA

    def test_schema_tasks_cardinality(self):
        tasks = INPUT_SCHEMA["properties"]["tasks"]
        assert tasks["minItems"] == 1
        assert tasks["maxItems"] == 4
        assert tasks["items"]["properties"]["goal"]["maxLength"] == 2000
        assert tasks["items"]["required"] == ["agent_id", "goal"]


class TestExecuteAsync:
    @pytest.mark.asyncio()
    async def test_execute_async_delegates_to_dispatcher(self):
        dispatcher = _make_dispatcher("调研完毕")
        tool = DispatchSubagentsTool(dispatcher)
        tasks = [{"agent_id": "researcher", "goal": "搜集资料"}]

        result = await tool.execute_async(tasks=tasks)

        assert result.success is True
        assert result.content == "调研完毕"
        dispatcher.dispatch.assert_awaited_once_with(tasks)

    @pytest.mark.asyncio()
    async def test_execute_async_passes_errors_through(self):
        dispatcher = _make_dispatcher()
        dispatcher.dispatch = AsyncMock(side_effect=RuntimeError("dispatch boom"))
        tool = DispatchSubagentsTool(dispatcher)

        result = await tool.execute_async(tasks=[{"agent_id": "r", "goal": "g"}])

        assert result.success is False
        assert "dispatch boom" in result.error


class TestExecuteSync:
    def test_execute_returns_clear_async_error(self):
        """同步 execute 不假装能跑 —— 明确提示走 run_loop special-case。"""
        tool = DispatchSubagentsTool(_make_dispatcher())
        result = tool.execute(tasks=[{"agent_id": "r", "goal": "g"}])
        assert result.success is False
        assert "execute_async" in result.error


class TestRunLoopSpecialCase:
    """真实 run_loop：mock LLM 返回 dispatch_subagents 工具调用 → 断言走 execute_async。"""

    @pytest.mark.asyncio()
    async def test_run_loop_dispatches_via_execute_async(self):
        from backend.core.legacy.agent import SageAgent
        from backend.core.legacy.agent_state import AgentEvent, AgentState
        from backend.core.legacy.llm_client import LLMResponse, LLMToolCall

        dispatcher = _make_dispatcher("子 agent 聚合结果")

        # bare 构造（跳过 register_all_tools），手动注册 dispatch 工具
        agent = SageAgent(agent_id=None, bare=True)
        agent.tool_registry.register(DispatchSubagentsTool(dispatcher))

        # mock llm_client.chat：第一轮工具调用，第二轮 DONE
        mock_client = MagicMock()
        mock_client.chat = AsyncMock(
            side_effect=[
                LLMResponse(
                    content="",
                    finish_reason="tool_calls",
                    tool_calls=[
                        LLMToolCall(
                            id="call_1",
                            name="dispatch_subagents",
                            arguments=json.dumps(
                                {"tasks": [{"agent_id": "researcher", "goal": "调研"}]}
                            ),
                        )
                    ],
                ),
                LLMResponse(content="最终答案", finish_reason="stop", tool_calls=[]),
            ]
        )
        agent.llm_client = mock_client

        events = []
        async for evt in agent.run_loop(
            [{"role": "user", "content": "复杂任务"}], max_iterations=2
        ):
            events.append(evt)

        assert events[-1].state == AgentState.DONE
        assert events[-1].content == "最终答案"
        dispatcher.dispatch.assert_awaited_once()  # execute_async 被调（不是 execute）
        observed = [e for e in events if e.state == AgentState.OBSERVING]
        assert observed, "run_loop 应产出 OBSERVING 事件（含 dispatch 结果）"
