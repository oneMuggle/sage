"""
agent.run_loop() 状态机测试

验证 SageAgent.run_loop():
1. LLM 返回纯文本时，状态机经过 THINKING → DONE
2. LLM 返回工具调用时，状态机经过 THINKING → ACTING → OBSERVING → THINKING → DONE
3. max_iterations 限制：超过时发出 FAILED 事件
4. 工具成功 / 失败 / 不存在 / 抛异常 四种路径
5. LLM 异常透传（不会被吞为 FAILED 事件）
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.agent import SageAgent
from backend.core.agent_state import AgentState
from backend.core.errors import LLMError, LLMErrorType
from backend.core.exceptions import AgentError
from backend.core.llm_client import LLMResponse, LLMToolCall

pytestmark = pytest.mark.unit


def _make_response(content: str = "", tool_calls: list = None) -> LLMResponse:
    return LLMResponse(
        content=content,
        tool_calls=tool_calls or [],
    )


@pytest.mark.asyncio()
async def test_run_loop_returns_done_when_no_tool_call():
    """LLM 返回纯文本时，状态机经过 THINKING → DONE。"""
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(return_value=_make_response(content="你好"))

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "hi"}]):
        events.append(evt)

    states = [e.state for e in events]
    assert AgentState.THINKING in states
    assert AgentState.DONE in states
    done_evt = next(e for e in events if e.state == AgentState.DONE)
    assert done_evt.content == "你好"


@pytest.mark.asyncio()
async def test_run_loop_executes_tool_and_observes():
    """LLM 返回工具调用时，状态机经过 THINKING → ACTING → OBSERVING → THINKING → DONE。"""
    tool_call = LLMToolCall(
        id="call_1",
        name="calculator",
        arguments='{"expression": "1+1"}',
    )
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        side_effect=[
            _make_response(content="", tool_calls=[tool_call]),
            _make_response(content="答案是 2"),
        ]
    )

    # 替换 tool_registry.get
    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(
        return_value=MagicMock(
            success=True,
            content={"result": 2},
            error=None,
        )
    )
    agent.tool_registry.get = MagicMock(return_value=mock_tool)

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "1+1 等于几"}]):
        events.append(evt)

    states = [e.state for e in events]
    assert AgentState.ACTING in states
    assert AgentState.OBSERVING in states
    assert AgentState.DONE in states


@pytest.mark.asyncio()
async def test_run_loop_respects_max_iterations():
    """max_iterations=2 时，应发出 FAILED。"""
    tool_call = LLMToolCall(id="c", name="calculator", arguments="{}")
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(return_value=_make_response(tool_calls=[tool_call]))

    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(return_value=MagicMock(success=True, content={}, error=None))
    agent.tool_registry.get = MagicMock(return_value=mock_tool)

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}], max_iterations=2):
        events.append(evt)

    failed = [e for e in events if e.state == AgentState.FAILED]
    assert len(failed) == 1
    assert failed[0].error == "max_iterations_exceeded"


# =============================================================================
# PG1.1 扩展测试 (Task 1.1.2): 工具调用 / 错误恢复 / 边界路径
# =============================================================================


@pytest.mark.asyncio()
async def test_run_loop_tool_success_yields_observation_with_content():
    """工具调用成功:THINKING → ACTING → OBSERVING(带 tool_result) → THINKING → DONE。"""
    tool_call = LLMToolCall(
        id="call_ok",
        name="calculator",
        arguments='{"expression": "2+2"}',
    )
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        side_effect=[
            _make_response(content="", tool_calls=[tool_call]),
            _make_response(content="答案是 4"),
        ]
    )

    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(
        return_value=MagicMock(
            success=True,
            content={"result": 4},
            error=None,
        )
    )
    agent.tool_registry.get = MagicMock(return_value=mock_tool)

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "2+2=?"}]):
        events.append(evt)

    # 必须有 ACTING 和 OBSERVING
    acting = next(e for e in events if e.state == AgentState.ACTING)
    observing = next(e for e in events if e.state == AgentState.OBSERVING)

    # ACTING 携带 tool_call
    assert acting.tool_call is not None
    assert acting.tool_call.name == "calculator"

    # OBSERVING 携带 tool_call 和 tool_result
    assert observing.tool_call is not None
    assert observing.tool_result is not None
    assert observing.tool_result.is_error is False
    assert observing.tool_result.tool_call_id == "call_ok"

    # OBSERVING 后回到 THINKING 然后 DONE
    states = [e.state for e in events]
    assert states[-1] == AgentState.DONE
    obs_idx = states.index(AgentState.OBSERVING)
    assert AgentState.THINKING in states[obs_idx + 1 :]

    # 工具被以正确参数调用
    mock_tool.execute.assert_called_once_with(expression="2+2")


@pytest.mark.asyncio()
async def test_run_loop_tool_returns_error_observation_continues():
    """工具返回 success=False → 标记 is_error=True 但不进入 FAILED,继续 THINKING 循环。"""
    tool_call = LLMToolCall(
        id="call_err",
        name="calculator",
        arguments='{"expression": "bad"}',
    )
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        side_effect=[
            _make_response(content="", tool_calls=[tool_call]),
            _make_response(content="工具报错,我换个方式回答"),
        ]
    )

    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(
        return_value=MagicMock(
            success=False,
            content=None,
            error="除数不能为零",
        )
    )
    agent.tool_registry.get = MagicMock(return_value=mock_tool)

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}]):
        events.append(evt)

    # 没有 FAILED 事件(单次迭代内完成)
    failed = [e for e in events if e.state == AgentState.FAILED]
    assert failed == []

    # OBSERVING 携带 is_error=True
    observing = next(e for e in events if e.state == AgentState.OBSERVING)
    assert observing.tool_result.is_error is True
    # 错误信息被序列化
    assert "除数不能为零" in observing.tool_result.content

    # 最后是 DONE(LLM 给了最终回答)
    assert events[-1].state == AgentState.DONE


@pytest.mark.asyncio()
async def test_run_loop_tool_not_found_marks_error_and_continues():
    """工具不存在 → result_content 标记错误,继续循环(不抛异常)。"""
    tool_call = LLMToolCall(
        id="call_missing",
        name="nonexistent_tool",
        arguments="{}",
    )
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        side_effect=[
            _make_response(content="", tool_calls=[tool_call]),
            _make_response(content="该工具不可用,直接回答"),
        ]
    )
    # 工具注册表找不到
    agent.tool_registry.get = MagicMock(return_value=None)

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "hi"}]):
        events.append(evt)

    observing = next(e for e in events if e.state == AgentState.OBSERVING)
    assert observing.tool_result.is_error is True
    assert "工具不存在" in observing.tool_result.content
    assert "nonexistent_tool" in observing.tool_result.content
    # 没 FAILED,正常收尾
    assert events[-1].state == AgentState.DONE


@pytest.mark.asyncio()
async def test_run_loop_tool_raises_exception_is_caught():
    """工具 execute() 抛异常 → 内部 try/except 捕获,is_error=True,继续循环。"""
    tool_call = LLMToolCall(
        id="call_exc",
        name="boom",
        arguments="{}",
    )
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        side_effect=[
            _make_response(content="", tool_calls=[tool_call]),
            _make_response(content="降级回答"),
        ]
    )

    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(side_effect=RuntimeError("工具内部炸了"))
    agent.tool_registry.get = MagicMock(return_value=mock_tool)

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}]):
        events.append(evt)

    observing = next(e for e in events if e.state == AgentState.OBSERVING)
    assert observing.tool_result.is_error is True
    assert "工具内部炸了" in observing.tool_result.content
    assert events[-1].state == AgentState.DONE


@pytest.mark.asyncio()
async def test_run_loop_malformed_tool_arguments_fall_back_to_empty_dict():
    """LLM 返回的 tool_call.arguments 是非 JSON 字符串时,降级为 {} 而不抛。"""
    tool_call = LLMToolCall(
        id="call_bad_json",
        name="noop",
        arguments="not-valid-json{{{",
    )
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        side_effect=[
            _make_response(content="", tool_calls=[tool_call]),
            _make_response(content="done"),
        ]
    )

    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(
        return_value=MagicMock(
            success=True,
            content={"ok": True},
            error=None,
        )
    )
    agent.tool_registry.get = MagicMock(return_value=mock_tool)

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}]):
        events.append(evt)

    # 不应抛 JSONDecodeError,正常收敛到 DONE
    assert events[-1].state == AgentState.DONE
    # 工具用空 dict 调用
    mock_tool.execute.assert_called_once_with()


@pytest.mark.asyncio()
async def test_run_loop_llm_empty_content_yields_done_with_empty_string():
    """LLM 返回空 content 且无 tool_call → 直接 DONE,content 为空串。"""
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(return_value=_make_response(content=""))

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}]):
        events.append(evt)

    # 只有 THINKING → DONE 两个事件
    assert [e.state for e in events] == [AgentState.THINKING, AgentState.DONE]
    done = events[-1]
    assert done.content == ""


@pytest.mark.asyncio()
async def test_run_loop_max_iterations_exceeded_yields_failed_event():
    """max_iterations=1 且 LLM 持续返回 tool_call → 第 1 次迭代后发出 FAILED 事件。

    注:实际行为是发出 FAILED(不是 DONE)。plan 写 DONE 是笔误,以代码为准。
    """
    tool_call = LLMToolCall(id="c", name="loop", arguments="{}")
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(return_value=_make_response(tool_calls=[tool_call]))

    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(return_value=MagicMock(success=True, content={}, error=None))
    agent.tool_registry.get = MagicMock(return_value=mock_tool)

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}], max_iterations=1):
        events.append(evt)

    # 序列应包含:THINKING, ACTING, OBSERVING, FAILED
    states = [e.state for e in events]
    assert AgentState.FAILED in states
    failed = next(e for e in events if e.state == AgentState.FAILED)
    assert failed.error == "max_iterations_exceeded"
    # FAILED 后不应有 DONE
    failed_idx = states.index(AgentState.FAILED)
    assert AgentState.DONE not in states[failed_idx + 1 :]


@pytest.mark.asyncio()
async def test_run_loop_llm_exception_propagates_without_being_swallowed():
    """LLM 抛 LLMError 时不会被 run_loop 捕获,直接向上传播(由 chat() 统一处理)。

    注:plan 写 "state FAILED + re-raise" 是预期外的设计,实际行为是直接透传。
    """
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(side_effect=LLMError(LLMErrorType.RATE_LIMITED, "too fast"))

    async def _consume():
        async for _ in agent.run_loop([{"role": "user", "content": "x"}]):
            pass

    with pytest.raises(LLMError) as exc_info:
        await _consume()

    assert exc_info.value.type == LLMErrorType.RATE_LIMITED


@pytest.mark.asyncio()
async def test_run_loop_raises_agent_error_when_llm_client_unset():
    """self.llm_client is None 时,run_loop 启动就抛 AgentError,不发任何事件。"""
    agent = SageAgent()
    # 显式置为 None,模拟未配置 LLM 的场景
    agent.llm_client = None

    async def _consume():
        async for _ in agent.run_loop([{"role": "user", "content": "x"}]):
            pass

    with pytest.raises(AgentError, match="LLM 未配置"):
        await _consume()


@pytest.mark.asyncio()
async def test_run_loop_appends_tool_message_to_messages_in_place():
    """run_loop 应当在原 messages 列表中追加 tool 消息(供下一轮 LLM 看到工具结果)。"""
    tool_call = LLMToolCall(id="c1", name="calc", arguments="{}")
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        side_effect=[
            _make_response(content="", tool_calls=[tool_call]),
            _make_response(content="final"),
        ]
    )

    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(
        return_value=MagicMock(success=True, content={"v": 1}, error=None)
    )
    agent.tool_registry.get = MagicMock(return_value=mock_tool)

    messages = [{"role": "user", "content": "x"}]
    async for _ in agent.run_loop(messages):
        pass

    # 应追加:assistant(tool_calls) → tool → assistant(content="final")
    roles = [m["role"] for m in messages]
    assert "tool" in roles
    tool_msg = next(m for m in messages if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == "c1"


@pytest.mark.asyncio()
async def test_run_loop_tool_with_non_typed_result_serializes_via_default():
    """工具返回非 success/content 对象(例如裸 str)时,走 default=str 序列化路径。"""
    tool_call = LLMToolCall(id="c1", name="weird", arguments="{}")
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        side_effect=[
            _make_response(content="", tool_calls=[tool_call]),
            _make_response(content="done"),
        ]
    )

    # 工具返回裸字符串(无 success/content 属性)
    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(return_value="plain string result")
    agent.tool_registry.get = MagicMock(return_value=mock_tool)

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}]):
        events.append(evt)

    observing = next(e for e in events if e.state == AgentState.OBSERVING)
    # 非 success/content 形态时,is_error 默认为 False
    assert observing.tool_result.is_error is False
    assert "plain string result" in observing.tool_result.content


@pytest.mark.asyncio()
async def test_run_loop_handles_multiple_tool_calls_in_one_iteration():
    """单轮 LLM 响应包含多个 tool_call 时,每个都应被独立执行 + 观察。"""
    tc1 = LLMToolCall(id="c1", name="a", arguments="{}")
    tc2 = LLMToolCall(id="c2", name="b", arguments="{}")
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        side_effect=[
            _make_response(content="", tool_calls=[tc1, tc2]),
            _make_response(content="done"),
        ]
    )

    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(return_value=MagicMock(success=True, content={}, error=None))
    agent.tool_registry.get = MagicMock(return_value=mock_tool)

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}]):
        events.append(evt)

    # 应有 2 次 ACTING + 2 次 OBSERVING
    assert sum(1 for e in events if e.state == AgentState.ACTING) == 2
    assert sum(1 for e in events if e.state == AgentState.OBSERVING) == 2
    # 工具被调用 2 次
    assert mock_tool.execute.call_count == 2
    assert events[-1].state == AgentState.DONE
