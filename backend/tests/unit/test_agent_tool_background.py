"""M2: ``agent(background=True)`` —— 后台子代理与完成通知。

覆盖：
- 后台模式立即返回 running 句柄，不阻塞主循环
- 子代理完成后经 main agent ``inject_system_note`` 注入完成通知
- 失败同样注入失败通知
- 每 stream 并发上限
- 前台模式行为不变（不注入系统通知）
"""

from __future__ import annotations

import asyncio
from typing import Any, List

import pytest

from backend.core.legacy.agent_state import AgentEvent, AgentState
from backend.tools import agent_background
from backend.tools.agent_tool import AgentTool
from backend.tools.context import (
    ToolExecutionContext,
    reset_tool_context,
    set_tool_context,
)

pytestmark = pytest.mark.unit


class _BlockingSubagent:
    """启动后阻塞直到 release，再产出 DONE。"""

    def __init__(self, answer: str = "调研结论", fail: bool = False) -> None:
        self.answer = answer
        self.fail = fail
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def run_loop(self, messages, max_iterations=None, llm_config=None):
        self.started.set()
        await self.release.wait()
        if self.fail:
            yield AgentEvent(state=AgentState.FAILED, error="boom", agent_id="subagent")
        else:
            yield AgentEvent(state=AgentState.DONE, content=self.answer, agent_id="subagent")


class _FakeMainAgent:
    def __init__(self) -> None:
        self.notes: List[str] = []
        self.note_event = asyncio.Event()

    def inject_system_note(self, content: str) -> bool:
        self.notes.append(content)
        self.note_event.set()
        return True


def _make_tool(fake: _BlockingSubagent, main_agent: Any) -> AgentTool:
    def _factory(registry):
        return fake

    return AgentTool(
        llm_client=object(),
        subagent_factory=_factory,
        main_agent_resolver=lambda stream_id: main_agent if stream_id == "s-1" else None,
    )


def _bind_context():
    return set_tool_context(
        ToolExecutionContext(
            session_id="sess-1",
            stream_id="s-1",
            binding_generation=1,
            office_doc_scope=frozenset(),
        )
    )


@pytest.mark.asyncio()
async def test_background_returns_immediately_and_notifies_on_done():
    fake = _BlockingSubagent()
    main = _FakeMainAgent()
    tool = _make_tool(fake, main)
    token = _bind_context()
    try:
        result = await asyncio.wait_for(
            tool.execute_async(description="找资料", prompt="调研论文", background=True),
            timeout=1,
        )
        assert result.success is True
        assert isinstance(result.content, dict)
        assert result.content["status"] == "running"
        # 子代理在后台启动且未阻塞返回
        await asyncio.wait_for(fake.started.wait(), timeout=1)
        assert main.notes == []

        fake.release.set()
        await asyncio.wait_for(main.note_event.wait(), timeout=2)
        assert len(main.notes) == 1
        assert "找资料" in main.notes[0]
        assert "调研结论" in main.notes[0]
    finally:
        reset_tool_context(token)


@pytest.mark.asyncio()
async def test_background_failure_notifies_error():
    fake = _BlockingSubagent(fail=True)
    main = _FakeMainAgent()
    tool = _make_tool(fake, main)
    token = _bind_context()
    try:
        result = await tool.execute_async(description="会失败", prompt="x", background=True)
        assert result.success is True  # 立即受理
        await asyncio.wait_for(fake.started.wait(), timeout=1)
        fake.release.set()
        await asyncio.wait_for(main.note_event.wait(), timeout=2)
        assert "会失败" in main.notes[0]
        assert "boom" in main.notes[0]
    finally:
        reset_tool_context(token)


@pytest.mark.asyncio()
async def test_background_requires_active_stream():
    fake = _BlockingSubagent()
    tool = _make_tool(fake, _FakeMainAgent())

    # 无工具上下文 → 无法定位主 agent → 明确报错而不是静默丢通知
    result = await tool.execute_async(description="d", prompt="p", background=True)

    assert result.success is False
    assert "background_requires_stream" in (result.error or "")


@pytest.mark.asyncio()
async def test_background_limit_per_stream(monkeypatch):
    monkeypatch.setattr(agent_background, "MAX_BACKGROUND_AGENTS_PER_STREAM", 2)
    main = _FakeMainAgent()
    fakes = [_BlockingSubagent(f"答案{i}") for i in range(3)]
    tool = _make_tool(fakes[0], main)
    token = _bind_context()
    try:
        first = await tool.execute_async(description="a", prompt="p", background=True)
        assert first.success is True
        second = await tool.execute_async(description="b", prompt="p", background=True)
        assert second.success is True
        third = await tool.execute_async(description="c", prompt="p", background=True)
        assert third.success is False
        assert "background_agent_limit" in (third.error or "")

        for fake in fakes[:2]:
            fake.release.set()
        await asyncio.wait_for(main.note_event.wait(), timeout=2)
    finally:
        reset_tool_context(token)


def test_default_resolution_uses_domain_registry():
    """M2: 未注入 resolver 时经域层注册表解析主 agent（避免 tools→api import）。"""
    from backend.domain import active_agent_registry
    from backend.tools.agent_background import resolve_main_agent

    fake = object()
    active_agent_registry.set_main_agent_resolver(
        lambda stream_id: fake if stream_id == "s-1" else None
    )
    try:
        assert resolve_main_agent(None, "s-1") is fake
        assert resolve_main_agent(None, "unknown") is None
        assert resolve_main_agent(None, None) is None
    finally:
        active_agent_registry.set_main_agent_resolver(None)


@pytest.mark.asyncio()
async def test_foreground_mode_unchanged():
    fake = _BlockingSubagent()
    main = _FakeMainAgent()
    tool = _make_tool(fake, main)
    token = _bind_context()
    try:
        async def _release_soon() -> None:
            await fake.started.wait()
            fake.release.set()

        releaser = asyncio.create_task(_release_soon())
        result = await tool.execute_async(description="前台", prompt="p")
        await releaser
        assert result.success is True
        assert result.content["answer"] == "调研结论"
        assert main.notes == []
    finally:
        reset_tool_context(token)
