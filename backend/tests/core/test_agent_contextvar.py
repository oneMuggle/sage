# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""Regression test: ContextVar propagation through executor dispatch.

Verifies that ``current_tool_context()`` returns a non-None value inside
an ``is_blocking=True`` tool's ``execute()`` when dispatched through the
real ``asyncio`` executor path (``py_compat.to_thread``).

Root cause: ``loop.run_in_executor(None, functools.partial(...))`` creates
a fresh context in the worker thread, dropping the ContextVar. Fix: use
``py_compat.to_thread`` which calls ``contextvars.copy_context()``.
"""

from __future__ import annotations

from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.legacy.agent import SageAgent
from backend.core.legacy.llm_client import LLMResponse, LLMToolCall
from backend.domain.risk import RiskClass
from backend.tools.context import (
    ToolExecutionContext,
    current_tool_context,
    reset_tool_context,
    set_tool_context,
)

pytestmark = pytest.mark.unit


class _ContextCapturingBlockingTool:
    """Fake blocking tool that captures ``current_tool_context()`` during execute."""

    def __init__(self) -> None:
        self.name = "design_generate"
        self.risk = "write"
        self.is_blocking = True
        self.captured_context: Optional[ToolExecutionContext] = "NOT_SET"  # type: ignore[assignment]

    def execute(self, **kwargs: Any) -> MagicMock:
        self.captured_context = current_tool_context()
        return MagicMock(success=True, content="generated", error=None)


def _make_agent_with_tool(tool: _ContextCapturingBlockingTool) -> SageAgent:
    """Create a minimal SageAgent with the given tool registered."""
    agent = SageAgent()
    registry = MagicMock()
    registry.get = lambda name: tool if name == tool.name else None
    agent.tool_registry = registry
    return agent


@pytest.mark.asyncio()
async def test_blocking_tool_sees_tool_context_via_executor():
    """is_blocking=True tool dispatched via executor sees current_tool_context().

    This is the regression test for the ContextVar loss bug: before the fix,
    ``loop.run_in_executor(None, functools.partial(tool.execute, **args))``
    dropped the ContextVar, so ``current_tool_context()`` returned None
    inside the executor thread. After switching to ``py_compat.to_thread``
    (which uses ``contextvars.copy_context()``), the context is preserved.
    """
    tool = _ContextCapturingBlockingTool()
    agent = _make_agent_with_tool(tool)

    ctx = ToolExecutionContext(
        session_id="test-session-123",
        stream_id="test-stream-456",
        binding_generation=1,
        office_doc_scope=frozenset({"doc-abc"}),
        agent_id="primary",
    )
    token = set_tool_context(ctx)
    try:
        cancelled, result = await agent._await_tool_execution_inner(
            tool=tool,
            name=tool.name,
            args={"prompt": "generate something"},
            tool_call_id="tc-001",
        )
    finally:
        reset_tool_context(token)

    assert cancelled is False
    assert result is not None
    assert tool.captured_context is not None, (
        "current_tool_context() returned None inside is_blocking=True tool's "
        "execute() — ContextVar was lost during executor dispatch. "
        "Ensure py_compat.to_thread (which copies context) is used instead "
        "of bare loop.run_in_executor."
    )
    assert tool.captured_context.session_id == "test-session-123"
    assert tool.captured_context.stream_id == "test-stream-456"
    assert tool.captured_context.agent_id == "primary"


@pytest.mark.asyncio()
async def test_non_blocking_tool_context_always_visible():
    """Non-blocking tools execute synchronously (no executor), context always visible."""

    class _SyncTool:
        def __init__(self) -> None:
            self.name = "quick_calc"
            self.risk = "read"
            self.is_blocking = False
            self.captured_context: Optional[ToolExecutionContext] = "NOT_SET"  # type: ignore[assignment]

        def execute(self, **kwargs: Any) -> MagicMock:
            self.captured_context = current_tool_context()
            return MagicMock(success=True, content="42", error=None)

    tool = _SyncTool()
    agent = _make_agent_with_tool(tool)

    ctx = ToolExecutionContext(
        session_id="sync-session",
        stream_id="sync-stream",
        binding_generation=1,
        office_doc_scope=frozenset(),
    )
    token = set_tool_context(ctx)
    try:
        cancelled, result = await agent._await_tool_execution_inner(
            tool=tool,
            name=tool.name,
            args={},
            tool_call_id="tc-sync",
        )
    finally:
        reset_tool_context(token)

    assert cancelled is False
    assert tool.captured_context is not None
    assert tool.captured_context.session_id == "sync-session"


class _ParallelPoolTool:
    """READ 工具, 走并行只读批次（pool 分支）时捕获 current_tool_context()。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.risk = RiskClass.READ
        self.is_blocking = False
        self.captured_context: Optional[ToolExecutionContext] = "NOT_SET"  # type: ignore[assignment]

    def execute(self, **kwargs: Any) -> MagicMock:
        self.captured_context = current_tool_context()
        return MagicMock(success=True, content="pool-result", error=None)


@pytest.mark.asyncio()
async def test_parallel_pool_tool_sees_tool_context():
    """并行只读批次（pool 分支）里的工具也能看到 current_tool_context()。

    pool 分支把 ``_run_one`` 卸载到线程池执行（``_run_one_with_timeout``），
    那里原先也是裸 ``run_in_executor`` —— 同样会丢 ContextVar。
    """
    t1 = _ParallelPoolTool("read_file")
    t2 = _ParallelPoolTool("list_dir")
    tools = {"read_file": t1, "list_dir": t2}

    agent = SageAgent()
    registry = MagicMock()
    registry.get = lambda name: tools.get(name)
    agent.tool_registry = registry
    client = MagicMock()
    client.chat = AsyncMock(
        side_effect=[
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(id="c0", name="read_file", arguments="{}"),
                    LLMToolCall(id="c1", name="list_dir", arguments="{}"),
                ],
            ),
            LLMResponse(content="done"),
        ]
    )
    agent.llm_client = client

    ctx = ToolExecutionContext(
        session_id="pool-session",
        stream_id="pool-stream",
        binding_generation=1,
        office_doc_scope=frozenset(),
    )
    token = set_tool_context(ctx)
    try:
        async for _evt in agent.run_loop([{"role": "user", "content": "x"}]):
            pass
    finally:
        reset_tool_context(token)

    assert t1.captured_context is not None, (
        "parallel pool 分支丢失了 ToolExecutionContext —— "
        "_run_one_with_timeout 必须走 py_compat.to_thread"
    )
    assert t1.captured_context.session_id == "pool-session"
    assert t2.captured_context is not None
    assert t2.captured_context.session_id == "pool-session"


@pytest.mark.asyncio()
async def test_design_generate_bridge_fires_end_to_end_via_executor():
    """端到端：design_generate 经真实 executor 分发后，产物真的落进 artifacts 表。

    这是 Task 3 桥接（``DesignGenerateTool.execute`` → ``_record_artifact_safely``）
    的真实链路验证。``DesignGenerateTool.is_blocking = True`` → 走
    ``_await_tool_execution_inner`` → executor 线程。修复前该线程拿不到
    ``ToolExecutionContext``，``session_id`` 为 None，桥接静默跳过。

    与 ``backend/tests/tools/test_design_generate_tool.py`` 的区别：那个用例
    直接 patch 掉 ``current_tool_context``，没有触碰 ContextVar 传播；
    本用例用真实的 ``set_tool_context`` + 真实 executor 路径。
    """
    from unittest.mock import patch

    from backend.tools.design_generate_tool import DesignGenerateTool

    mock_artifact = MagicMock()
    mock_artifact.id = "design_art_ctx"
    mock_artifact.version = 1
    mock_artifact.title = "Test Design"
    mock_artifact.file_path = "/workspace/design/proj/v1.html"
    mock_artifact.html_content = "<html>test</html>"

    mock_project = MagicMock()
    mock_project.id = "proj_ctx"
    mock_project.name = "Test Project"

    mock_studio = MagicMock()
    mock_studio.create_project.return_value = mock_project

    async def _mock_generate(project_id):
        return mock_artifact

    mock_studio.generate.side_effect = _mock_generate

    tool = DesignGenerateTool()
    agent = SageAgent()
    registry = MagicMock()
    registry.get = lambda name: tool if name == tool.name else None
    agent.tool_registry = registry

    ctx = ToolExecutionContext(
        session_id="e2e-session",
        stream_id="e2e-stream",
        binding_generation=1,
        office_doc_scope=frozenset(),
    )
    token = set_tool_context(ctx)
    try:
        with patch(
            "backend.tools.design_generate_tool.get_design_studio",
            return_value=mock_studio,
        ), patch(
            "backend.tools.design_generate_tool._record_artifact_safely"
        ) as mock_record:
            cancelled, result = await agent._await_tool_execution_inner(
                tool=tool,
                name=tool.name,
                args={
                    "name": "Test",
                    "kind": "web",
                    "system_id": "sys_1",
                    "template_id": "tpl_1",
                    "brief": "Test brief",
                },
                tool_call_id="tc-e2e",
            )
    finally:
        reset_tool_context(token)

    assert cancelled is False
    assert result is not None
    # 桥接真的被调用了 —— 修复前这里是 0 次（session_id 为 None 被跳过）
    mock_record.assert_called_once()
    call_kwargs = mock_record.call_args.kwargs
    assert call_kwargs["session_id"] == "e2e-session"
    assert call_kwargs["resolved_path"] == "/workspace/design/proj/v1.html"
