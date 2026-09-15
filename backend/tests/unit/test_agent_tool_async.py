"""live-events P2 单元测试 —— ``agent`` 工具异步通路治理。

覆盖：
- ``agent_event_bridge``：登记/查询/注销生命周期。
- ``AgentTool.execute_async``：事件投影转发（acting/observing 镜像 +
  终态合成 task_status）+ 成功/校验失败/无 LLM/超时取消（L12 根修：
  ``wait_for`` 超时不再遗弃线程,子协程被真正取消）。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from backend.core.legacy.agent_state import AgentEvent, AgentState, ToolCallRequest, ToolCallResult
from backend.tools import agent_tool as agent_tool_module
from backend.tools.agent_event_bridge import (
    get_stream_emitter,
    register_stream_emitter,
    unregister_stream_emitter,
)
from backend.tools.agent_tool import SUBAGENT_ANSWER_CAP, AgentTool

# ---------------------------------------------------------------------------
# 测试替身
# ---------------------------------------------------------------------------


class _ScriptedSubagent:
    """按脚本 yield AgentEvent 的假子代理（覆盖 subagent_factory 注入口）。"""

    def __init__(self, script, hang_before_done: bool = False) -> None:
        self.script = list(script)
        self.hang_before_done = hang_before_done
        self.cancelled = False

    async def run_loop(self, messages, max_iterations=None, llm_config=None):
        try:
            for evt in self.script:
                yield evt
            if self.hang_before_done:
                await asyncio.sleep(30)
            yield AgentEvent(state=AgentState.DONE, content="调研结论", agent_id="subagent")
        except asyncio.CancelledError:
            self.cancelled = True
            raise


def _acting(tool_id: str = "tc-1", name: str = "read_file") -> AgentEvent:
    return AgentEvent(
        state=AgentState.ACTING,
        iteration=0,
        agent_id="subagent",
        tool_call=ToolCallRequest(id=tool_id, name=name, arguments={"path": "docs/a.md"}),
    )


def _observing(tool_id: str = "tc-1", content: str = "doc body") -> AgentEvent:
    return AgentEvent(
        state=AgentState.OBSERVING,
        iteration=0,
        agent_id="subagent",
        tool_result=ToolCallResult(tool_call_id=tool_id, content=content, is_error=False),
    )


def _make_tool(script, hang_before_done: bool = False):
    """构造 (tool, fake) 对 —— fake 供取消断言用。"""
    fake = _ScriptedSubagent(script, hang_before_done=hang_before_done)

    def _factory(registry):
        return fake

    return AgentTool(llm_client=object(), subagent_factory=_factory), fake


# ---------------------------------------------------------------------------
# 事件桥
# ---------------------------------------------------------------------------


def test_bridge_register_get_unregister():
    emitted: List[Dict[str, Any]] = []
    register_stream_emitter("sess-1", emitted.append)
    try:
        emitter = get_stream_emitter("sess-1")
        assert emitter is not None
        emitter({"state": "subagent_event"})
        assert emitted
    finally:
        unregister_stream_emitter("sess-1")
    assert get_stream_emitter("sess-1") is None
    assert get_stream_emitter(None) is None


# ---------------------------------------------------------------------------
# AgentTool.execute_async
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_execute_async_forwards_events_and_succeeds():
    """有桥时: acting/observing 镜像 + 终态合成 task_status done;结果正常。"""
    emitted: List[Dict[str, Any]] = []
    register_stream_emitter("sess-live", emitted.append)
    try:
        with patch(
            "backend.tools.context.current_tool_context", create=True
        ) as mock_ctx, patch.object(
            agent_tool_module, "SUBAGENT_TIMEOUT_S", 10.0
        ):
            ctx = type("Ctx", (), {"session_id": "sess-live"})()
            mock_ctx.return_value = ctx
            tool, _fake = _make_tool([_acting(), _observing()])
            result = await tool.execute_async(
                description="调研依赖",
                prompt="读文件",
                _tool_call_id="call-parent-9",
            )
    finally:
        unregister_stream_emitter("sess-live")

    assert result.success is True
    content = result.content
    assert content["answer"] == "调研结论"
    assert content["truncated"] is False

    mirrors = [e for e in emitted if e.get("state") == "subagent_event"]
    assert [m["phase"] for m in mirrors] == ["tool_call", "tool_result"]
    assert all(m["run_id"].startswith("agent-") for m in mirrors)
    assert all(m["parent_tool_call_id"] == "call-parent-9" for m in mirrors)

    terminal = [e for e in emitted if e.get("state") == "task_status"]
    assert len(terminal) == 1
    assert terminal[0]["status"] == "done"
    assert terminal[0]["output_preview"] == "调研结论"


@pytest.mark.asyncio()
async def test_execute_async_timeout_cancels_subagent():
    """超时 → 内层协程被取消（L12 根修）+ lane 失败 + 合成 task_status failed。"""
    emitted: List[Dict[str, Any]] = []
    register_stream_emitter("sess-timeout", emitted.append)
    try:
        with patch(
            "backend.tools.context.current_tool_context", create=True
        ) as mock_ctx, patch.object(
            agent_tool_module, "SUBAGENT_TIMEOUT_S", 0.05
        ):
            ctx = type("Ctx", (), {"session_id": "sess-timeout"})()
            mock_ctx.return_value = ctx
            tool, fake = _make_tool([], hang_before_done=True)
            result = await tool.execute_async(description="慢任务", prompt="等 30 秒")
    finally:
        unregister_stream_emitter("sess-timeout")

    assert result.success is False
    assert "timeout" in (result.error or "")
    # 关键断言: 子代理协程收到取消（wait_for 根修 —— 不再遗弃后台线程空跑）
    assert fake.cancelled is True
    terminal = [e for e in emitted if e.get("state") == "task_status"]
    assert terminal
    assert terminal[0]["status"] == "failed"


@pytest.mark.asyncio()
async def test_execute_async_without_bridge_still_succeeds():
    """无桥（非流上下文）→ 行为退化为纯执行,不产生镜像也不崩溃。"""
    tool, _fake = _make_tool([_acting(), _observing()])
    result = await tool.execute_async(description="调研", prompt="读文件")
    assert result.success is True
    assert result.content["answer"] == "调研结论"


@pytest.mark.asyncio()
async def test_execute_async_validates_inputs():
    tool, _fake = _make_tool([])
    result = await tool.execute_async(description="", prompt="x")
    assert result.success is False
    result = await tool.execute_async(description="x", prompt="")
    assert result.success is False


@pytest.mark.asyncio()
async def test_execute_async_requires_llm():
    tool = AgentTool(llm_client=None, subagent_factory=lambda registry: None)
    with patch("backend.tools.agent_tool.build_llm_client_from_settings", return_value=None):
        result = await tool.execute_async(description="x", prompt="y")
    assert result.success is False
    assert "no_llm_configured" in (result.error or "")


@pytest.mark.asyncio()
async def test_execute_async_caps_answer():
    long_answer = "x" * (SUBAGENT_ANSWER_CAP + 100)

    class _OnlyDone(_ScriptedSubagent):
        async def run_loop(self, messages, max_iterations=None, llm_config=None):
            yield AgentEvent(state=AgentState.DONE, content=long_answer, agent_id="subagent")

    tool = AgentTool(
        llm_client=object(), subagent_factory=lambda registry: _OnlyDone([])
    )
    result = await tool.execute_async(description="d", prompt="p")
    assert result.success is True
    assert len(result.content["answer"]) == SUBAGENT_ANSWER_CAP
    assert result.content["truncated"] is True
