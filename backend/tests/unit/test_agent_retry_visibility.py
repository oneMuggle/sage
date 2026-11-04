"""非流式路径重试事件可见性回归测试（2026-10-30）。

背景：agent.run_loop 的非流式分支把 retry 回调暂存在 pending_retries，
只有 chat() 正常返回后才补发；重试耗尽抛异常时补发代码不执行，
前端完全看不到"重试中"。本用例锁定"失败前也要补发"。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.errors import LLMError, LLMErrorType
from backend.core.legacy.agent import SageAgent
from backend.core.legacy.agent_state import AgentState
from backend.core.legacy.llm_client import RetryEvent

pytestmark = pytest.mark.unit


@pytest.mark.asyncio()
async def test_non_stream_retry_events_emitted_before_failure():
    agent = SageAgent()
    # MagicMock 未声明的 stream_unsupported 为真值 → _should_stream 返回 False，
    # 强制走非流式 chat() 分支（与 test_agent_run_loop.py 既有做法一致）。
    agent.llm_client = MagicMock()
    retry_event = RetryEvent(
        attempt=1,
        max_attempts=3,
        error_type="server_error",
        error_message="LLM 服务端错误 (HTTP 504)",
        delay=2.0,
        elapsed_s=61.0,
        attempt_timeout_s=86.0,
        budget_total_s=180.0,
        budget_remaining_s=140.0,
    )

    async def _chat(messages, tools=None, tool_choice=None, retry_callback=None):
        if retry_callback is not None:
            retry_callback(retry_event)
        raise LLMError(
            LLMErrorType.SERVER_ERROR, "LLM 服务端错误 (HTTP 504)", status_code=504
        )

    agent.llm_client.chat = AsyncMock(side_effect=_chat)

    events = []

    async def _consume() -> None:
        async for evt in agent.run_loop(
            [{"role": "user", "content": "hi"}], max_iterations=1
        ):
            events.append(evt)

    with pytest.raises(LLMError):
        await _consume()

    retry_events = [e for e in events if e.state == AgentState.RETRY]
    assert len(retry_events) == 1
    info = retry_events[0].retry_info
    assert info["attempt"] == 1
    assert info["max_attempts"] == 3
    assert info["error_type"] == "server_error"
    # 2026-11-02: 非流式回退路径曾漏掉预算字段，导致 RetryBanner 不显示剩余预算。
    assert info["budget_total_s"] == 180.0
    assert info["budget_remaining_s"] == 140.0
    # 2026-11-03: 计时协议字段 —— 前端据此显示"已等 61s / 单次上限 86s"。
    assert info["phase"] == "backoff"
    assert info["elapsed_s"] == 61.0
    assert info["attempt_timeout_s"] == 86.0


def test_retry_started_info_merges_last_error_and_switches_phase():
    """retry_attempt_started 沿用上一次失败原因，phase 切换为 in_flight。"""
    from backend.core.legacy.agent import _retry_started_info_from_event
    from backend.core.legacy.llm_client import RetryAttemptStartedEvent

    last = {
        "attempt": 1,
        "max_attempts": 3,
        "error_type": "timeout",
        "error_message": "LLM 代理超时",
        "delay": 2.0,
        "phase": "backoff",
        "elapsed_s": 61.0,
        "attempt_timeout_s": 86.0,
        "budget_total_s": 180.0,
        "budget_remaining_s": 117.0,
    }
    started = RetryAttemptStartedEvent(
        attempt=2,
        elapsed_s=63.0,
        attempt_timeout_s=86.0,
        budget_remaining_s=115.0,
    )

    info = _retry_started_info_from_event(started, last)

    assert info["attempt"] == 2
    assert info["phase"] == "in_flight"
    assert info["delay"] == 0.0
    assert info["elapsed_s"] == 63.0
    assert info["attempt_timeout_s"] == 86.0
    assert info["budget_remaining_s"] == 115.0
    # 错误原因保留自上一次失败
    assert info["error_type"] == "timeout"
    assert info["error_message"] == "LLM 代理超时"
