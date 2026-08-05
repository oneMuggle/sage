"""Memory tool LLM registration tests (Task 3, Gap C).

这些测试验证 ``memory_search`` / ``memory_save`` 两个工具:

1. 各自的 ``_build_schema`` 暴露正确的 LLM-facing schema 名称
2. ``ToolRegistry`` 注册后, ``ToolPort.list_tools()`` 把它们暴露给 LLM
3. ``ChatService.__init__`` 接受 ``tools`` 形参, 在 ``run_turn`` 时
   把 ``list_tools()`` 规格作为 ``tools`` 转发给 LLM 客户端

即: 一次 chat 调用的 LLM 端能拿到 ``memory_search`` 和 ``memory_save``
schema, 与"LLM 能在对话中调用记忆系统"链路对齐。
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, Mock

import pytest

from backend.application.services.chat_service import ChatService
from backend.tools.memory_tool import MemorySaveTool, MemorySearchTool

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------- #
# 1. Memory tool schema names
# ---------------------------------------------------------------------- #


def test_memory_search_tool_schema_present():
    """Tool must declare itself with schema name 'memory_search'."""
    tool = MemorySearchTool(memory_manager=None)  # manager not needed for schema
    assert tool.schema.name == "memory_search"
    # 校验 description / parameters 也有, 防止日后无意改写
    assert tool.schema.description
    assert "query" in tool.schema.parameters["required"]


def test_memory_save_tool_schema_present():
    """Tool must declare itself with schema name 'memory_save'."""
    tool = MemorySaveTool(memory_manager=None)
    assert tool.schema.name == "memory_save"
    assert tool.schema.description
    assert "content" in tool.schema.parameters["required"]


# ---------------------------------------------------------------------- #
# 2. ChatService accepts `tools`
# ---------------------------------------------------------------------- #


def test_chat_service_accepts_tools():
    """``ChatService.__init__`` 必须接受 ``tools`` 形参; LLM 工具链依赖它."""
    sig = inspect.signature(ChatService.__init__)
    assert "tools" in sig.parameters, "ChatService.__init__ must accept a `tools` parameter"


# ---------------------------------------------------------------------- #
# 2b. Agent profiles expose memory tools
# ---------------------------------------------------------------------- #


def test_primary_profile_has_memory_tools():
    """``primary`` agent profile 必须声明 ``memory_search`` + ``memory_save``.

    profile.tools 列表是 LLM 端"按 agent 过滤可用工具"的依据
    (虽然当前 ChatService 一次返回所有 tools, 但 profile.tools 是
    调度/路由层/未来按 agent 过滤时的契约). 缺一不可, 因为 primary
    是面向用户的默认 agent, 必须能写也能读.
    """
    from backend.agents.profiles import get_agent

    profile = get_agent("primary")
    assert profile is not None
    assert "memory_search" in profile.tools
    assert "memory_save" in profile.tools


def test_researcher_profile_has_memory_tools():
    """``researcher`` agent profile 必须声明 ``memory_search`` + ``memory_save``.

    researcher 查到资料后必须能落地为记忆, 否则下次 session 找不到 —
    这是"knowledge persistence"的核心闭环.
    """
    from backend.agents.profiles import get_agent

    profile = get_agent("researcher")
    assert profile is not None
    assert "memory_search" in profile.tools
    assert "memory_save" in profile.tools


# ---------------------------------------------------------------------- #
# 3. ToolRegistry exposes memory tools via ToolPort.list_tools()
# ---------------------------------------------------------------------- #


def test_inproc_adapter_exposes_memory_tools_to_llm():
    """``InprocToolAdapter.list_tools()`` 必须返回 ``memory_search`` / ``memory_save``.

    校验 LLM 端能够"看到"这两个工具的 spec. 这是 end-to-end 链路的核心:
    LLM 接收 `tools` 数组 → 模型选择 tool → ChatService 解析 →
    ``ToolPort.execute('memory_search', ...)`` 落到 ``MemorySearchTool``.
    """
    from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter
    from backend.tools import ToolRegistry, register_all_tools

    registry = ToolRegistry()
    register_all_tools(registry)
    adapter = InprocToolAdapter(registry=registry)

    specs = adapter.list_tools()
    names = [s.name for s in specs]

    assert "memory_search" in names, (
        f"memory_search tool missing from ToolPort.list_tools(): {names}"
    )
    assert "memory_save" in names, (
        f"memory_save tool missing from ToolPort.list_tools(): {names}"
    )


# ---------------------------------------------------------------------- #
# 4. ChatService.run_turn forwards memory tool specs to LLM
# ---------------------------------------------------------------------- #


@pytest.mark.asyncio()
async def test_chat_service_run_turn_passes_memory_tools_to_llm():
    """``ChatService.run_turn`` 必须把工具 spec 作为 ``tools`` 转发给 ``LLMPort.chat``.

    验证: register 完 ``memory_search`` / ``memory_save`` 后, 一次 chat
    调用 (LLM 端) 收到的 ``tools`` 数组中包含这两个工具.

    用最小的 mocks (LLM / storage / metrics / events / memory) 跑一次
    ``run_turn``; ``LLMPort.chat`` 是 AsyncMock, 调用后 assert ``tools``
    实参.
    """
    from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter
    from backend.domain.message import Message, Role
    from backend.tools import ToolRegistry, register_all_tools

    # 装配 ToolPort
    registry = ToolRegistry()
    register_all_tools(registry)
    adapter = InprocToolAdapter(registry=registry)

    # mock LLM - 返回无 tool_call 的简单 assistant 消息
    llm = Mock()
    llm.chat = AsyncMock(
        return_value=Message(
            role=Role.ASSISTANT,
            content="ok",
            tool_calls=[],
        )
    )

    # mock storage
    storage = Mock()
    storage.create_session = AsyncMock(return_value="session-1")
    storage.append_message = AsyncMock()
    storage.get_messages = AsyncMock(return_value=[])

    metrics = Mock()
    metrics.counter = Mock()
    metrics.histogram = Mock()
    metrics.gauge = Mock()

    events = Mock()
    events.emit = Mock()

    svc = ChatService(
        llm=llm,
        tools=adapter,
        skills=None,
        storage=storage,
        metrics=metrics,
        events=events,
        memory=None,
    )

    session_id = await svc.create_session()
    await svc.run_turn(
        session_id=session_id,
        user_message=Message(role=Role.USER, content="hi"),
    )

    # 校验 LLM.chat 收到了带 memory_* 的 tools 列表
    llm.chat.assert_awaited()
    call_args = llm.chat.call_args
    forwarded_tools = call_args.kwargs.get("tools")
    # 可能位置传 history + 关键字传 tools, 故查 kwargs
    assert forwarded_tools is not None, "LLM.chat must receive `tools` kwarg"
    names = [
        t["function"]["name"] if isinstance(t, dict) and "function" in t else t.get("name")
        for t in forwarded_tools
    ]
    assert "memory_search" in names
    assert "memory_save" in names
