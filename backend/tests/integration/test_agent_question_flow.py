"""M2 part B — SageAgent.run_loop AskUserQuestion 集成测试。

验证分发前特判接线:
- ask_user_question 工具调用 → ASK_USER_QUESTION 流事件（完整载荷）;
  并发任务应答 → 工具结果携带用户选择 → DONE。
- custom 自由文本随应答进入工具结果。
- 超时未应答 → "用户未回答"软结果（is_error=False），循环继续到 DONE。
- gate 未初始化 → 同样不挂起，软结果 + DONE。
- 参数非法（options 不足 2 项）→ 错误 ToolResult，不发提问事件。
- 不经过权限执行器（不产生 PERMISSION_REQUEST 事件）。
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.legacy.agent import SageAgent
from backend.core.legacy.agent_state import AgentState
from backend.core.legacy.llm_client import LLMResponse, LLMToolCall
from backend.data.settings_repo import SettingsRepository
from backend.services.question_gate import (
    get_question_gate,
    init_question_gate,
    reset_question_gate,
)
from backend.tools.ask_user_tool import UNANSWERED_RESULT_TEXT

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _gate_lifecycle():
    """每个测试独立 gate, 防止跨测试挂起请求泄漏。"""
    # question_gate 是进程级单例；本文件改写 settings.permission_mode
    # 后写回原值（写后必还）。注意 permission_mode 残留并非跨测试泄漏
    # 的实际根因——autouse setup_test_db 给每个测试独立 temp DB；真正
    # 的跨测试残留源是 main.py lifespan 装配的全局 gate（shutdown 已
    # reset）。
    _repo = SettingsRepository()
    _prev_mode = _repo.get("permission_mode")
    reset_question_gate()
    yield
    reset_question_gate()
    if _prev_mode is None:
        _repo.delete("permission_mode")
    else:
        _repo.set("permission_mode", _prev_mode)


def _make_response(content: str = "", tool_calls=None) -> LLMResponse:
    return LLMResponse(content=content, tool_calls=tool_calls or [])


def _ask_call(
    call_id: str = "call_ask",
    options=None,
    question: str = "选择输出格式?",
    multi_select: bool = False,
) -> LLMToolCall:
    args = {
        "question": question,
        "options": options
        or [{"label": "Markdown", "description": "纯文本"}, {"label": "PDF"}],
        "multi_select": multi_select,
    }
    return LLMToolCall(
        id=call_id, name="ask_user_question", arguments=json.dumps(args, ensure_ascii=False)
    )


def _agent_with_ask_tool(tool_calls, final_content: str = "好的，按您的选择执行") -> SageAgent:
    """构造 LLM mock（先返回 ask tool_call 再返回终答）。

    不 mock tool_registry —— 用真实注册的 ask_user_question 工具（纯渲染器）。
    """
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        side_effect=[
            _make_response(content="", tool_calls=tool_calls),
            _make_response(content=final_content),
        ]
    )
    return agent


async def test_run_loop_ask_user_emits_event_and_carries_selection_to_done():
    """提问事件 → 并发应答 → 工具结果携带选择 → DONE。"""
    # Arrange
    gate = init_question_gate()
    agent = _agent_with_ask_tool([_ask_call()])

    answered = {}

    async def responder():
        await asyncio.sleep(0.05)
        pending = gate.pending()
        assert len(pending) == 1
        answered["request"] = pending[0]
        assert gate.answer(pending[0].request_id, answers=["PDF"], custom=None) is True

    # Act
    responder_task = asyncio.create_task(responder())
    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "给我个报告"}]):
        events.append(evt)
    await responder_task

    # Assert —— 事件顺序与载荷契约
    states = [e.state for e in events]
    assert AgentState.ASK_USER_QUESTION in states
    assert states.index(AgentState.ACTING) < states.index(AgentState.ASK_USER_QUESTION)
    assert states.index(AgentState.ASK_USER_QUESTION) < states.index(AgentState.OBSERVING)

    ask_evt = next(e for e in events if e.state == AgentState.ASK_USER_QUESTION)
    payload = ask_evt.user_question
    assert payload is not None
    assert set(payload.keys()) == {
        "request_id",
        "question",
        "header",
        "options",
        "multi_select",
        "created_at",
    }
    assert payload["question"] == "选择输出格式?"
    assert payload["request_id"] == answered["request"].request_id
    assert [opt["label"] for opt in payload["options"]] == ["Markdown", "PDF"]

    # 工具结果携带用户选择，循环走到 DONE
    observing = next(e for e in events if e.state == AgentState.OBSERVING)
    assert observing.tool_result.is_error is False
    assert "用户已回答" in observing.tool_result.content
    assert "PDF" in observing.tool_result.content
    # LLM 的 tool message 也收到同样内容
    assert events[-1].state == AgentState.DONE


async def test_run_loop_ask_user_custom_text_is_carried():
    """custom 自由文本进入工具结果。"""
    # Arrange
    gate = init_question_gate()
    agent = _agent_with_ask_tool([_ask_call()])

    async def responder():
        await asyncio.sleep(0.05)
        pending = gate.pending()
        gate.answer(pending[0].request_id, answers=[], custom="用 HTML 就好")

    # Act
    task = asyncio.create_task(responder())
    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}]):
        events.append(evt)
    await task

    # Assert
    observing = next(e for e in events if e.state == AgentState.OBSERVING)
    assert observing.tool_result.is_error is False
    assert "用 HTML 就好" in observing.tool_result.content
    assert events[-1].state == AgentState.DONE


async def test_run_loop_ask_user_timeout_yields_graceful_default_and_done():
    """无人应答 → 软结果"用户未回答"（非错误），循环不挂死，到 DONE。"""
    # Arrange
    init_question_gate()
    agent = _agent_with_ask_tool([_ask_call()])
    agent.question_timeout = 0.05  # 缩短超时加速测试

    # Act
    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}]):
        events.append(evt)

    # Assert
    assert AgentState.ASK_USER_QUESTION in [e.state for e in events]
    observing = next(e for e in events if e.state == AgentState.OBSERVING)
    assert observing.tool_result.is_error is False  # 软结果不是错误
    assert observing.tool_result.content == UNANSWERED_RESULT_TEXT
    assert events[-1].state == AgentState.DONE
    assert [e for e in events if e.state == AgentState.FAILED] == []


async def test_run_loop_ask_user_without_gate_does_not_hang():
    """gate 未初始化 → 按无人应答处理（不挂起），循环继续。"""
    # Arrange
    reset_question_gate()
    assert get_question_gate() is None
    agent = _agent_with_ask_tool([_ask_call()])

    # Act
    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}]):
        events.append(evt)

    # Assert
    observing = next(e for e in events if e.state == AgentState.OBSERVING)
    assert observing.tool_result.content == UNANSWERED_RESULT_TEXT
    assert events[-1].state == AgentState.DONE


async def test_run_loop_ask_user_invalid_params_yields_error_without_event():
    """参数非法（options 只有 1 项）→ 错误 ToolResult，不发提问事件。"""
    # Arrange
    init_question_gate()
    bad_call = _ask_call(options=[{"label": "只有一个"}])
    agent = _agent_with_ask_tool([bad_call])

    # Act
    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}]):
        events.append(evt)

    # Assert
    assert AgentState.ASK_USER_QUESTION not in [e.state for e in events]
    observing = next(e for e in events if e.state == AgentState.OBSERVING)
    assert observing.tool_result.is_error is True
    assert "参数错误" in observing.tool_result.content
    assert "2-4" in observing.tool_result.content
    assert events[-1].state == AgentState.DONE


async def test_run_loop_ask_user_bypasses_permission_enforcer():
    """ask_user_question 不过权限执行器 —— prompt 模式也不产生审批事件。"""
    # Arrange
    from backend.data.settings_repo import SettingsRepository
    from backend.tools.bash_validation import validate_bash
    from backend.tools.permissions import PermissionEnforcer, PermissionMode

    SettingsRepository().set("permission_mode", "prompt")
    gate = init_question_gate()
    agent = _agent_with_ask_tool([_ask_call()])
    agent.permission_enforcer = PermissionEnforcer(
        mode=PermissionMode.PROMPT, rules=[], bash_validator=validate_bash
    )

    async def responder():
        await asyncio.sleep(0.05)
        pending = gate.pending()
        assert len(pending) == 1
        gate.answer(pending[0].request_id, answers=["Markdown"])

    # Act
    task = asyncio.create_task(responder())
    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}]):
        events.append(evt)
    await task

    # Assert —— 只有提问事件，没有审批事件
    states = [e.state for e in events]
    assert AgentState.PERMISSION_REQUEST not in states
    assert AgentState.ASK_USER_QUESTION in states
    assert events[-1].state == AgentState.DONE


async def test_run_loop_consecutive_unanswered_cap_stops_asking():
    """审查加固: 连续 3 次未应答后第 4 次提问直接拒绝（防 LLM 循环骚扰用户）。"""
    # Arrange: LLM 连续请求提问 4 次，每次都不应答（超时）
    init_question_gate()
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        side_effect=[
            _make_response(content="", tool_calls=[_ask_call(call_id=f"call_{i}")])
            for i in range(4)
        ]
        + [_make_response(content="直接推进任务")]
    )
    agent.question_timeout = 0.05  # 缩短超时加速测试

    # Act
    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}]):
        events.append(evt)

    # Assert: 前 3 次正常发问，第 4 次被上限拦截（错误结果且无提问事件）
    ask_events = [e for e in events if e.state == AgentState.ASK_USER_QUESTION]
    assert len(ask_events) == 3
    observings = [e for e in events if e.state == AgentState.OBSERVING]
    assert len(observings) == 4
    assert observings[-1].tool_result.is_error is True
    assert "停止提问" in observings[-1].tool_result.content
    # 软结果仍允许循环体面收尾
    assert events[-1].state == AgentState.DONE
