"""M3-Task 5 —— 子代理记忆归属父专家（subagent → parent specialist）。

安全不变式：

- 子代理的私有记忆写入落在**父会话绑定的专家层**，不是 primary 层；
- 归属来自父会话绑定（``sessions.specialist_id``），不依赖环境上下文的
  ``agent_id`` 缺省值（缺省是 ``"primary"``，漏解析会静默串层）；
- 无环境上下文时**不凭空造**上下文 —— memory 工具保持 fail-closed；
- 子代理结束后上下文复原，不泄漏给后续调用。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from backend.core.legacy.agent_state import AgentEvent, AgentState
from backend.orchestration.subagent_runner import SubagentRunner
from backend.tools.context import (
    ToolExecutionContext,
    current_tool_context,
    reset_tool_context,
    set_tool_context,
)
from backend.tools.memory_tool import MemorySaveTool

pytestmark = pytest.mark.unit

_DUMMY_PROFILE = {"system_prompt": "你是测试子 agent", "tools": []}


def _make_task(goal: str = "调研 X"):
    from backend.orchestration.models import Task

    return Task(
        task_id="task-t1", name="T1", description=goal,
        parameters={"goal": goal},
    )


def _ctx(
    agent_id: str = "primary",
    session_id: str = "sess-parent",
) -> ToolExecutionContext:
    return ToolExecutionContext(
        session_id=session_id,
        stream_id="stream-1",
        binding_generation=1,
        office_doc_scope=frozenset(),
        agent_id=agent_id,
    )


class _CtxCaptureAgent:
    """记录子代理运行期间看到的工具上下文。"""

    def __init__(self, agent_id=None, policy=None):
        self.agent_id = agent_id
        self.policy = policy
        self.seen: List[Optional[ToolExecutionContext]] = []

    async def run_loop(
        self, messages, max_iterations=None, llm_config=None, session_id=None
    ):
        self.seen.append(current_tool_context())
        yield AgentEvent(state=AgentState.DONE, content="ok")


class _MemoryWriteAgent:
    """子代理在运行期间调用 memory_save —— 记录写入归属。"""

    def __init__(self, agent_id=None, policy=None):
        self.agent_id = agent_id
        self.policy = policy
        self.manager = MagicMock()
        self.manager.memorize.return_value = "mem-1"
        self.tool = MemorySaveTool(memory=self.manager)
        self.save_result: Any = None

    async def run_loop(
        self, messages, max_iterations=None, llm_config=None, session_id=None
    ):
        self.save_result = self.tool.execute(content="子代理学到的事实")
        yield AgentEvent(state=AgentState.DONE, content="ok")


async def _run(runner: SubagentRunner, agent: Any, task=None, agent_role="researcher"):
    """跑一次子代理（patch 掉 profile，agent 构造固定返回断言用的实例）。"""
    with patch(
        "backend.orchestration.subagent_runner.get_enabled_agent",
        return_value=_DUMMY_PROFILE,
    ), patch(
        "backend.orchestration.subagent_runner.SageAgent", return_value=agent
    ):
        return await runner(task or _make_task(), agent_role)


class TestSubagentMemoryAttribution:
    @pytest.mark.asyncio()
    async def test_child_sees_parent_session_specialist(self):
        """父会话绑定 specialist-writer → 子代理上下文 agent_id 同步为它。

        环境上下文的 agent_id 是缺省值 "primary"（构造点漏解析时的静默
        串层根源），子代理必须以父会话绑定为准。
        """
        agent = _CtxCaptureAgent()
        ctx = _ctx(agent_id="primary")
        token = set_tool_context(ctx)
        try:
            with patch(
                "backend.orchestration.subagent_runner.resolve_bound_specialist",
                return_value="specialist-writer",
            ):
                runner = SubagentRunner(session_id="sess-parent")
                await _run(runner, agent)
        finally:
            reset_tool_context(token)
        assert agent.seen[0] is not None
        assert agent.seen[0].agent_id == "specialist-writer"

    @pytest.mark.asyncio()
    async def test_child_memory_write_attributed_to_parent_specialist(self):
        """子代理写记忆 → memorize 收到父专家的 agent_id。"""
        agent = _MemoryWriteAgent()
        ctx = _ctx(agent_id="primary")
        token = set_tool_context(ctx)
        try:
            with patch(
                "backend.orchestration.subagent_runner.resolve_bound_specialist",
                return_value="specialist-writer",
            ):
                runner = SubagentRunner(session_id="sess-parent")
                await _run(runner, agent)
        finally:
            reset_tool_context(token)
        assert agent.save_result.success is True
        kwargs: Dict[str, Any] = agent.manager.memorize.call_args[1]
        assert kwargs["agent_id"] == "specialist-writer"

    @pytest.mark.asyncio()
    async def test_explicit_agent_id_wins_over_session_binding(self):
        """显式 agent_id 优先于父会话绑定。"""
        agent = _CtxCaptureAgent()
        ctx = _ctx(agent_id="primary")
        token = set_tool_context(ctx)
        try:
            with patch(
                "backend.orchestration.subagent_runner.resolve_bound_specialist",
                return_value="specialist-writer",
            ):
                runner = SubagentRunner(
                    session_id="sess-parent", agent_id="specialist-explicit"
                )
                await _run(runner, agent)
        finally:
            reset_tool_context(token)
        assert agent.seen[0].agent_id == "specialist-explicit"

    @pytest.mark.asyncio()
    async def test_ambient_context_used_when_session_absent(self):
        """无父会话 → 回落到环境上下文的 agent_id。"""
        agent = _CtxCaptureAgent()
        ctx = _ctx(agent_id="specialist-ambient")
        token = set_tool_context(ctx)
        try:
            runner = SubagentRunner()
            await _run(runner, agent)
        finally:
            reset_tool_context(token)
        assert agent.seen[0].agent_id == "specialist-ambient"

    @pytest.mark.asyncio()
    async def test_no_context_is_not_fabricated(self):
        """既无父会话也无环境上下文 → 不凭空造上下文。"""
        agent = _CtxCaptureAgent()
        runner = SubagentRunner()
        await _run(runner, agent)
        assert agent.seen[0] is None

    @pytest.mark.asyncio()
    async def test_no_context_keeps_memory_tools_fail_closed(self):
        """无环境上下文时子代理写记忆被拒（fail-closed，不落 primary）。"""
        agent = _MemoryWriteAgent()
        runner = SubagentRunner()
        await _run(runner, agent)
        assert agent.save_result.success is False
        assert "可信会话上下文" in agent.save_result.error
        agent.manager.memorize.assert_not_called()

    @pytest.mark.asyncio()
    async def test_context_restored_after_child_run(self):
        """子代理结束后上下文复原，后续调用不受影响。"""
        agent = _CtxCaptureAgent()
        ctx = _ctx(agent_id="primary")
        token = set_tool_context(ctx)
        try:
            with patch(
                "backend.orchestration.subagent_runner.resolve_bound_specialist",
                return_value="specialist-writer",
            ):
                runner = SubagentRunner(session_id="sess-parent")
                await _run(runner, agent)
            assert current_tool_context() is ctx
            assert current_tool_context().agent_id == "primary"
        finally:
            reset_tool_context(token)
