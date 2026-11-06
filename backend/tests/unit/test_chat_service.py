"""验证 ChatService 用 mock adapters 编排 ports。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sage_core import LLMError, LLMErrorType, Message, Role, ToolCall

from backend.adapters.out.event.stdout_adapter import StdoutEventAdapter
from backend.adapters.out.llm.mock_adapter import MockLLMAdapter
from backend.adapters.out.metric.noop_adapter import NoopMetricAdapter
from backend.adapters.out.storage.memory_adapter import MemoryStorageAdapter
from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter
from backend.application.services.chat_service import ChatService

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


async def test_run_turn_serializes_structured_tool_output_for_messages():
    """结构化工具结果写入 TOOL 消息时保持 JSON 文本契约。"""
    llm_response = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[ToolCall(name="runtime_probe", args={})],
    )
    service = _make_service(llm_responses=[llm_response])
    service.tools._registry.get.return_value.execute.return_value = MagicMock(
        success=True,
        output={"runtimes": [], "recommended": None},
        error=None,
    )  # type: ignore[attr-defined]
    sid = await service.storage.create_session()

    await service.run_turn(sid, Message(role=Role.USER, content="probe"))

    messages = await service.storage.get_messages(sid)
    tool_message = next(message for message in messages if message.role == Role.TOOL)
    assert tool_message.content == '{"runtimes": [], "recommended": null}'


async def test_run_turn_uses_mock_tool_registry():
    """当 LLM 返回含 tool_calls 时执行工具"""
    llm_response = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[ToolCall(name="list_dir", args={"expression": "2+2"})],
    )
    service = _make_service(llm_responses=[llm_response])
    sid = await service.storage.create_session()

    await service.run_turn(sid, Message(role=Role.USER, content="compute"))
    # 工具被 InprocToolAdapter 通过 registry.get(name) 找到并 execute(**args)
    assert service.tools._registry.get.called  # type: ignore[attr-defined]
    assert service.tools._registry.get.call_args.args[0] == "list_dir"
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


async def test_complex_turn_appends_skill_nudge():
    """单轮工具调用 ≥ 阈值且未激活技能 → assistant 回复追加技能提示。"""
    from backend.application.services.chat_service import SKILL_NUDGE_SUFFIX

    llm_response = Message(
        role=Role.ASSISTANT,
        content="完成复杂任务",
        tool_calls=[ToolCall(name="list_dir", args={"expression": "2+2"})] * 4,
    )
    service = _make_service(llm_responses=[llm_response])
    sid = await service.storage.create_session()

    await service.run_turn(sid, Message(role=Role.USER, content="do complex thing"))

    msgs = await service.storage.get_messages(sid)
    assistant_msg = next(m for m in msgs if m.role == Role.ASSISTANT)
    assert SKILL_NUDGE_SUFFIX in assistant_msg.content


async def test_simple_turn_skips_skill_nudge():
    """低工具调用轮次不追加技能提示。"""
    from backend.application.services.chat_service import SKILL_NUDGE_SUFFIX

    llm_response = Message(role=Role.ASSISTANT, content="简单回答")
    service = _make_service(llm_responses=[llm_response])
    sid = await service.storage.create_session()

    await service.run_turn(sid, Message(role=Role.USER, content="hi"))

    msgs = await service.storage.get_messages(sid)
    assistant_msg = next(m for m in msgs if m.role == Role.ASSISTANT)
    assert SKILL_NUDGE_SUFFIX not in assistant_msg.content


# ------------------------------------------------------------------ #
# M1: Multi-turn ReAct regression tests
# ------------------------------------------------------------------ #


async def test_run_turn_tracked_returns_assistant_message_id():
    """run_turn_tracked 返回 (messages, assistant_message_id)。"""
    llm_response = Message(role=Role.ASSISTANT, content="hi there")
    service = _make_service(llm_responses=[llm_response])
    sid = await service.storage.create_session()
    user_msg = Message(role=Role.USER, content="hello")

    messages, assistant_id = await service.run_turn_tracked(sid, user_msg)
    assert len(messages) == 2
    assert messages[0].role == Role.USER
    assert messages[1].role == Role.ASSISTANT
    # assistant_id 是 storage 分配的字符串 ID，非空即通过
    assert isinstance(assistant_id, str)
    assert assistant_id


async def test_run_turn_tracked_default_max_iterations_is_single_turn():
    """run_turn_tracked 默认 max_iterations=1 → 与 run_turn 行为一致。"""
    llm_response = Message(role=Role.ASSISTANT, content="single turn")
    service = _make_service(llm_responses=[llm_response])
    sid = await service.storage.create_session()

    messages, assistant_id = await service.run_turn_tracked(sid, Message(role=Role.USER, content="hi"))
    assert len(service.llm.calls) == 1
    assert assistant_id is not None


async def test_multi_turn_tool_results_fed_back_to_llm():
    """max_iterations=2 时，工具结果回喂 LLM，触发二次调用。"""
    # 第 1 次 LLM 调用返回 tool_calls
    first_response = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[ToolCall(name="list_dir", args={"expression": "."})],
    )
    # 第 2 次 LLM 调用返回最终文本回复
    second_response = Message(role=Role.ASSISTANT, content="done after tools")
    service = _make_service(llm_responses=[first_response, second_response])
    sid = await service.storage.create_session()

    messages, assistant_id = await service.run_turn_tracked(
        sid,
        Message(role=Role.USER, content="do it"),
        max_iterations=2,
    )

    # LLM 应被调用 2 次
    assert len(service.llm.calls) == 2
    # 持久化消息顺序：user → assistant(tool_calls) → tool → assistant(final)
    all_msgs = await service.storage.get_messages(sid)
    roles = [m.role for m in all_msgs]
    assert roles == [Role.USER, Role.ASSISTANT, Role.TOOL, Role.ASSISTANT]
    # assistant_id 非空
    assert isinstance(assistant_id, str)
    assert assistant_id


async def test_multi_turn_stops_at_max_iterations():
    """达到 max_iterations 上限时停止循环，不继续调 LLM。"""
    # 每次 LLM 都返回 tool_calls → 永远不满足终止条件 A
    tool_response = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[ToolCall(name="list_dir", args={"expression": "."})],
    )
    # 提供足够多响应（虽然不应全部消费）
    service = _make_service(llm_responses=[tool_response] * 10)
    sid = await service.storage.create_session()

    await service.run_turn_tracked(
        sid,
        Message(role=Role.USER, content="go"),
        max_iterations=3,
    )

    # 恰好调用 3 次 LLM（不更多）
    assert len(service.llm.calls) == 3


async def test_multi_turn_tool_budget_exceeded_stops_early():
    """工具预算跨轮累计耗尽时提前停止循环（即使未达 max_iterations）。"""
    tool_response = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[ToolCall(name="list_dir", args={"expression": "."})],
    )
    service = _make_service(llm_responses=[tool_response] * 10)
    # 设置极低预算（单次 run 累计上限 = 1）
    from backend.domain.tool_policy import ToolPolicy

    service._tool_policy = ToolPolicy(max_tool_calls_per_run=1)
    sid = await service.storage.create_session()

    await service.run_turn_tracked(
        sid,
        Message(role=Role.USER, content="go"),
        max_iterations=5,
    )

    # 预算=1：第 1 轮执行 1 次工具；第 2 轮请求工具时累计已超预算 →
    # 立即停止（不再执行工具，也不进入第 3 轮），故恰好 2 次 LLM 调用。
    assert len(service.llm.calls) == 2
    # 底层工具仅真正执行 1 次（第 2 轮被预算拦下）
    mock_tool = service.tools._registry.get.return_value  # type: ignore[attr-defined]
    assert mock_tool.execute.call_count == 1


async def test_assistant_persisted_before_tool_messages():
    """多轮中 assistant(tool_calls) 消息先于 tool 消息落库。"""
    first_response = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[ToolCall(name="list_dir", args={"expression": "."})],
    )
    second_response = Message(role=Role.ASSISTANT, content="final")
    service = _make_service(llm_responses=[first_response, second_response])
    sid = await service.storage.create_session()

    await service.run_turn_tracked(
        sid,
        Message(role=Role.USER, content="do it"),
        max_iterations=2,
    )

    all_msgs = await service.storage.get_messages(sid)
    # 找到第一条 assistant（带 tool_calls）和第一条 tool 消息
    assistant_idx = next(
        i for i, m in enumerate(all_msgs) if m.role == Role.ASSISTANT and m.tool_calls
    )
    tool_idx = next(i for i, m in enumerate(all_msgs) if m.role == Role.TOOL)
    # assistant 消息在前（sequence 顺序正确）
    assert assistant_idx < tool_idx
