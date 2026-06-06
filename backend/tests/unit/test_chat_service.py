"""验证 ChatService 用 mock adapters 编排 ports。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.adapters.out.event.stdout_adapter import StdoutEventAdapter
from backend.adapters.out.llm.mock_adapter import MockLLMAdapter
from backend.adapters.out.metric.noop_adapter import NoopMetricAdapter
from backend.adapters.out.storage.memory_adapter import MemoryStorageAdapter
from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter
from backend.application.services.chat_service import ChatService
from backend.domain.errors import LLMError, LLMErrorType
from backend.domain.message import Message, Role, ToolCall

pytestmark = pytest.mark.unit


def _make_service(llm_responses=None, llm=None):
    """Helper to build ChatService with mock adapters."""
    mock_tool = MagicMock()
    mock_tool.execute.return_value = MagicMock(success=True, output="ok", error=None)
    mock_tool_registry = MagicMock()
    mock_tool_registry.list.return_value = []
    mock_tool_registry.get.return_value = mock_tool

    tools = InprocToolAdapter(registry=mock_tool_registry)
    skills = MagicMock()
    storage = MemoryStorageAdapter()

    actual_llm = llm if llm is not None else MockLLMAdapter(responses=llm_responses or [])

    return ChatService(
        llm=actual_llm,
        tools=tools,
        skills=skills,
        storage=storage,
        metrics=NoopMetricAdapter(),
        events=StdoutEventAdapter(verbose=False),
    )


async def test_run_turn_persists_user_message():
    """run_turn 持久化 user message"""
    service = _make_service()
    sid = await service.storage.create_session()
    user_msg = Message(role=Role.USER, content="hello")

    await service.run_turn(sid, user_msg)
    msgs = await service.storage.get_messages(sid)
    assert any(m.content == "hello" and m.role == Role.USER for m in msgs)


async def test_run_turn_calls_llm():
    """run_turn 调用 LLM"""
    llm_response = Message(role=Role.ASSISTANT, content="hi there")
    service = _make_service(llm_responses=[llm_response])
    sid = await service.storage.create_session()

    await service.run_turn(sid, Message(role=Role.USER, content="hello"))
    assert len(service.llm.calls) == 1


async def test_run_turn_persists_assistant_response():
    """run_turn 持久化 assistant 回复"""
    llm_response = Message(role=Role.ASSISTANT, content="hi there")
    service = _make_service(llm_responses=[llm_response])
    sid = await service.storage.create_session()

    await service.run_turn(sid, Message(role=Role.USER, content="hello"))
    msgs = await service.storage.get_messages(sid)
    contents = [m.content for m in msgs]
    assert "hello" in contents
    assert "hi there" in contents


async def test_run_turn_emits_events():
    """run_turn emit 事件不抛错"""
    service = _make_service(llm_responses=[Message(role=Role.ASSISTANT, content="ok")])
    sid = await service.storage.create_session()
    await service.run_turn(sid, Message(role=Role.USER, content="hi"))


async def test_run_turn_handles_llm_error():
    """LLM 抛错时记录指标 + 事件 + 重抛"""
    llm = AsyncMock()
    llm.chat.side_effect = LLMError(LLMErrorType.TIMEOUT, "test timeout")

    service = _make_service(llm=llm)
    sid = await service.storage.create_session()

    with pytest.raises(LLMError):
        await service.run_turn(sid, Message(role=Role.USER, content="hi"))


async def test_run_turn_uses_mock_tool_registry():
    """当 LLM 返回含 tool_calls 时执行工具"""
    llm_response = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[ToolCall(name="calculator", args={"expression": "2+2"})],
    )
    service = _make_service(llm_responses=[llm_response])
    sid = await service.storage.create_session()

    await service.run_turn(sid, Message(role=Role.USER, content="compute"))
    # 工具被 InprocToolAdapter 通过 registry.get(name) 找到并 execute(**args)
    assert service.tools._registry.get.called  # type: ignore[attr-defined]
    assert service.tools._registry.get.call_args.args[0] == "calculator"
    # 工具的 execute 被调用，参数是 args 解包
    mock_tool = service.tools._registry.get.return_value  # type: ignore[attr-defined]
    mock_tool.execute.assert_called_once_with(expression="2+2")


async def test_returns_user_and_assistant_messages():
    """run_turn 返回 [user_msg, response]"""
    llm_response = Message(role=Role.ASSISTANT, content="response")
    service = _make_service(llm_responses=[llm_response])
    sid = await service.storage.create_session()
    user_msg = Message(role=Role.USER, content="question")

    result = await service.run_turn(sid, user_msg)
    assert len(result) == 2
    assert result[0].role == Role.USER
    assert result[1].role == Role.ASSISTANT
