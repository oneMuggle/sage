"""
PR-7 / PR-7b: /chat/stream 端点持久化回归测试

回归 Bug: "对话内容没有保存,之前的对话记录都是空对话"。

修复前: ``agent.run_loop()`` 自身不写库,producer 也不落盘。
         /chat/stream 走完后 SQLite messages 表永远空,侧栏历史显示
         message_count=0 + last_message_at=NULL。

修复后: producer 在 run_loop 前后分别落 user / assistant 消息 + 更新
         session metadata (last_message_at + message_count += 2)。
         落盘失败不破坏流 (try/except 隔离)。

覆盖 4 个关键不变性:
  1. 一次成功 chat 后, messages 表有 user+assistant 两行
  2. session.last_message_at 被更新, message_count = 2
  3. persistence 抛错时, 流仍能正常完成 (不强中断)
  4. reasoning 事件随 assistant 行落库 (PR-7b)

历史注记 (R91, 2026-09-20): 本文件曾因 ``POST /api/v1/sessions`` 依赖
SessionService DI 未装配而被 ``skipif(True)`` 整体跳过多年。现改用
``SessionRepository().create()`` 直建会话绕开 DI,全套复活（harness 与
test_sources_stream_persist.py（R84）同源验证）。
"""

from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import patch

import pytest

from backend.core.legacy.agent_state import AgentEvent, AgentState
from backend.data.session_repo import MessageRepository, SessionRepository
from backend.main import app

pytestmark = [pytest.mark.integration]

CHAT_STREAM_PATH = "/api/v1/chat/stream"


async def _run_stream_and_wait(client, session_id: str, message: str, **payload_extra) -> None:
    """发起流并 attach 消费,等待后台 producer 收尾（落盘 + 入队 SENTINEL）。"""
    create_stream = await client.post(
        CHAT_STREAM_PATH,
        json={"session_id": session_id, "message": message, **payload_extra},
    )
    assert create_stream.status_code == 200, create_stream.text
    stream_id = create_stream.json()["streamId"]

    attach = await client.get(f"{CHAT_STREAM_PATH}/{stream_id}")
    assert attach.status_code == 200

    entry = app.state.streams.get(stream_id)
    if entry and entry.task:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await entry.task


@pytest.mark.asyncio()
async def test_streaming_chat_persists_user_and_assistant_messages(client):
    """一次成功 chat 后,messages 表里应该有 user + assistant 两行。"""
    session = SessionRepository().create(title="PR-7 回归")

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(
            state=AgentState.DONE,
            iteration=0,
            content="这是 assistant 真实回答",
        )

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = mock_run_loop
        MockAgent.return_value.memory_manager = None

        await _run_stream_and_wait(client, session.id, "PR-7 回归消息")

    persisted = MessageRepository().get_by_session(session.id)
    assert len(persisted) == 2, f"expected 2 messages, got {len(persisted)}: {persisted}"

    user_msg = next((m for m in persisted if m.role == "user"), None)
    asst_msg = next((m for m in persisted if m.role == "assistant"), None)
    assert user_msg is not None, "user message not persisted"
    assert user_msg.content == "PR-7 回归消息"
    assert asst_msg is not None, "assistant message not persisted"
    assert asst_msg.content == "这是 assistant 真实回答"


@pytest.mark.asyncio()
async def test_streaming_chat_updates_session_metadata(client):
    """chat 完成后 session.last_message_at 应当被更新, message_count 应为 2。"""
    session = SessionRepository().create(title="PR-7 session update")

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        yield AgentEvent(state=AgentState.DONE, iteration=0, content="ok")

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = mock_run_loop
        MockAgent.return_value.memory_manager = None

        await _run_stream_and_wait(client, session.id, "hi")

    sess_repo = SessionRepository()
    sess = sess_repo.get(session.id)
    assert sess is not None
    # 修复前: message_count=0, last_message_at=NULL → 侧栏历史显示"空对话"
    assert sess.message_count == 2, f"message_count={sess.message_count}, expected 2"
    assert (
        sess.last_message_at is not None
    ), f"last_message_at={sess.last_message_at}, expected non-null ms timestamp"
    assert (
        sess.last_message_at > 0
    ), f"last_message_at={sess.last_message_at}, expected positive ms timestamp"


@pytest.mark.asyncio()
async def test_message_save_failure_does_not_break_stream(client):
    """持久化抛错时,流应该正常完成 (try/except 隔离),不 500。"""
    session = SessionRepository().create(title="PR-7 failure isolation")

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        yield AgentEvent(state=AgentState.DONE, iteration=0, content="done")

    # R91 win7 适配: 括号化 with (a as x, b as y) 是 Py3.9+ 语法（py38 兼容
    # 检查器会拦）；ExitStack 兼容 py3.8 且不触发 SIM117。
    with contextlib.ExitStack() as stack:
        MockAgent = stack.enter_context(patch("backend.api.legacy_routes.SageAgent"))
        MockMsgRepo = stack.enter_context(
            patch("backend.api.legacy_routes.MessageRepository")
        )
        MockAgent.return_value.run_loop = mock_run_loop
        MockAgent.return_value.memory_manager = None
        MockMsgRepo.return_value.save.side_effect = RuntimeError("simulated db down")

        create_stream = await client.post(
            CHAT_STREAM_PATH,
            json={"session_id": session.id, "message": "this should still stream"},
        )
        assert create_stream.status_code == 200
        stream_id = create_stream.json()["streamId"]

        attach = await client.get(f"{CHAT_STREAM_PATH}/{stream_id}")
        assert attach.status_code == 200
        # attach 文本应至少包含 'done' 事件 (流没被持久化错误打断)
        assert '"state": "done"' in attach.text or '"state":"done"' in attach.text
        # 不应把内部错误细节抛给客户端
        assert "RuntimeError" not in attach.text

        entry = app.state.streams.get(stream_id)
        if entry and entry.task:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await entry.task


@pytest.mark.asyncio()
async def test_streaming_chat_persists_reasoning_content(client):
    """一次带 reasoning 的 chat 后,assistant 消息的 reasoning_content 被写入 DB。"""
    session = SessionRepository().create(title="PR-7b reasoning")

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(
            state=AgentState.REASONING,
            iteration=0,
            reasoning="这是 LLM 的思考过程,会被持久化到 DB",
        )
        yield AgentEvent(
            state=AgentState.DONE,
            iteration=0,
            content="这是 assistant 回答",
        )

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = mock_run_loop
        MockAgent.return_value.memory_manager = None

        await _run_stream_and_wait(
            client,
            session.id,
            "PR-7b 回归消息",
            api_key="sk-test",
            api_url="https://example.com/v1",
            model="gpt-4",
        )

    persisted = MessageRepository().get_by_session(session.id)
    asst_msg = next((m for m in persisted if m.role == "assistant"), None)
    assert asst_msg is not None, "assistant message not persisted"
    assert (
        asst_msg.reasoning_content == "这是 LLM 的思考过程,会被持久化到 DB"
    ), f"reasoning_content not persisted, got {asst_msg.reasoning_content!r}"
    assert asst_msg.content == "这是 assistant 回答"


@pytest.mark.asyncio()
async def test_streaming_chat_without_reasoning_has_null_reasoning_content(client):
    """不带 reasoning 的 chat,assistant 消息的 reasoning_content 应该是 None。"""
    session = SessionRepository().create(title="PR-7b no reasoning")

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(
            state=AgentState.DONE,
            iteration=0,
            content="普通回答,无思考",
        )

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = mock_run_loop
        MockAgent.return_value.memory_manager = None

        await _run_stream_and_wait(client, session.id, "PR-7b 无思考消息")

    persisted = MessageRepository().get_by_session(session.id)
    asst_msg = next((m for m in persisted if m.role == "assistant"), None)
    assert asst_msg is not None
    assert (
        asst_msg.reasoning_content is None
    ), f"reasoning_content should be None when no reasoning event, got {asst_msg.reasoning_content!r}"
