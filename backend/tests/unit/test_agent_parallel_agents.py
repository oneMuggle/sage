"""M2: 同轮多个 ``agent`` 调用并发执行。

覆盖：一条 assistant 消息里的两个 agent tool call 必须在主循环串行等待前
同时启动（否则本测试会超时失败），结果仍按模型顺序回填。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from backend.core.legacy.agent import SageAgent
from backend.core.legacy.agent_state import AgentState
from backend.core.legacy.llm_client import LLMResponse, LLMToolCall
from backend.tools.base import ToolResult
from backend.tools.permissions import PermissionDecision

pytestmark = pytest.mark.unit


class _BarrierAgentTool:
    """同名 ``agent`` 假工具：等两个调用都启动后才放行。"""

    def __init__(self) -> None:
        self.started = 0
        self.both_started = asyncio.Event()
        self.release = asyncio.Event()

    async def execute_async(self, **kwargs: Any) -> ToolResult:
        self.started += 1
        if self.started >= 2:
            self.both_started.set()
        await self.release.wait()
        return ToolResult(
            success=True,
            content={"answer": f"ok-{kwargs.get('description')}"},
        )


def _make_response(content: str = "", tool_calls: list = None) -> LLMResponse:
    return LLMResponse(content=content, tool_calls=tool_calls or [])


@pytest.mark.asyncio()
async def test_two_agent_calls_in_one_turn_run_concurrently():
    from unittest.mock import MagicMock

    agent = SageAgent()
    agent.llm_client = MagicMock()

    fake_tool = _BarrierAgentTool()
    calls = {"n": 0}

    async def _chat(messages, tools=None, tool_choice=None, retry_callback=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return _make_response(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="a1",
                        name="agent",
                        arguments=json.dumps({"description": "A", "prompt": "p1"}),
                    ),
                    LLMToolCall(
                        id="a2",
                        name="agent",
                        arguments=json.dumps({"description": "B", "prompt": "p2"}),
                    ),
                ],
            )
        return _make_response(content="done")

    agent.llm_client.chat = _chat
    agent.tool_registry.get = lambda name: fake_tool if name == "agent" else None
    # 避免依赖真实 enforcer/策略：本测试只验证调度并发性
    agent._check_permission = lambda enforcer, name, args: PermissionDecision(
        allowed=True, needs_approval=False, reason=""
    )

    messages = [{"role": "user", "content": "并行调研"}]
    events = []

    async def _drive() -> None:
        async for evt in agent.run_loop(messages, max_iterations=3):
            events.append(evt)

    driver = asyncio.create_task(_drive())
    try:
        await asyncio.wait_for(fake_tool.both_started.wait(), timeout=2)
    finally:
        fake_tool.release.set()
    await asyncio.wait_for(driver, timeout=5)

    acting = [e for e in events if e.state == AgentState.ACTING]
    observing = [e for e in events if e.state == AgentState.OBSERVING]
    assert len(acting) == 2
    assert len(observing) == 2
    # 结果按模型顺序回填
    assert [e.tool_result.tool_call_id for e in observing] == ["a1", "a2"]
    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["a1", "a2"]
    assert AgentState.DONE in [e.state for e in events]
