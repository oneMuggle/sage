"""
PR-7: /chat/stream 端点持久化回归测试

回归 Bug: "对话内容没有保存,之前的对话记录都是空对话"。

修复前: ``agent.run_loop()`` 自身不写库,producer 也不落盘。
         /chat/stream 走完后 SQLite messages 表永远空,侧栏历史显示
         message_count=0 + last_message_at=NULL。

修复后: producer 在 run_loop 前后分别落 user / assistant 消息 + 更新
         session metadata (last_message_at + message_count += 2)。
         落盘失败不破坏流 (try/except 隔离)。

这个文件覆盖 3 个关键不变性:
  1. 一次成功 chat 后, messages 表有 user+assistant 两行
  2. session.last_message_at 被更新, message_count = 2
  3. persistence 抛错时, 流仍能正常完成 (不强中断)
"""

import asyncio
import contextlib
from unittest.mock import patch

import pytest

from backend.core.legacy.agent_state import AgentEvent, AgentState
from backend.data.session_repo import MessageRepository, SessionRepository
from backend.main import app

pytestmark = pytest.mark.integration

CHAT_STREAM_PATH = "/api/v1/chat/stream"
SESSIONS_PATH = "/api/v1/sessions"


@pytest.mark.asyncio()
async def test_streaming_chat_persists_user_and_assistant_messages(client):
    """一次成功 chat 后,messages 表里应该有 user + assistant 两行。"""
    # 1. 建一个 session
    create_sess = await client.post(SESSIONS_PATH, json={"title": "PR-7 回归"})
    assert create_sess.status_code == 200, create_sess.text
    session_id = create_sess.json()["id"]

    # 2. mock run_loop 直接 DONE
    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(
            state=AgentState.DONE,
            iteration=0,
            content="这是 assistant 真实回答",
        )

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = mock_run_loop

        # 3. POST /chat/stream 拿 streamId
        create_stream = await client.post(
            CHAT_STREAM_PATH,
            json={"session_id": session_id, "message": "PR-7 回归消息"},
        )
        assert create_stream.status_code == 200, create_stream.text
        stream_id = create_stream.json()["streamId"]

        # 4. attach 消费,等待 producer (后台 task) 落盘
        attach = await client.get(f"{CHAT_STREAM_PATH}/{stream_id}")
        assert attach.status_code == 200
        # 等 producer 跑完 (落盘 + 入队 SENTINEL)
        entry = app.state.streams.get(stream_id)
        if entry and entry.task:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await entry.task

    # 5. 验证 messages 表里 user + assistant 各一行
    msg_repo = MessageRepository()
    persisted = msg_repo.get_by_session(session_id)
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
    create_sess = await client.post(SESSIONS_PATH, json={"title": "PR-7 session update"})
    assert create_sess.status_code == 200
    session_id = create_sess.json()["id"]

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        yield AgentEvent(state=AgentState.DONE, iteration=0, content="ok")

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = mock_run_loop

        create_stream = await client.post(
            CHAT_STREAM_PATH,
            json={"session_id": session_id, "message": "hi"},
        )
        stream_id = create_stream.json()["streamId"]
        await client.get(f"{CHAT_STREAM_PATH}/{stream_id}")

        entry = app.state.streams.get(stream_id)
        if entry and entry.task:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await entry.task

    sess_repo = SessionRepository()
    sess = sess_repo.get(session_id)
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
    create_sess = await client.post(SESSIONS_PATH, json={"title": "PR-7 failure isolation"})
    assert create_sess.status_code == 200
    session_id = create_sess.json()["id"]

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        yield AgentEvent(state=AgentState.DONE, iteration=0, content="done")

    # mock MessageRepository.save 抛 RuntimeError → 走 logger.warning,
    # 流应该正常关闭,客户端 attach 应能拿到所有事件
    with (
        patch("backend.api.legacy_routes.SageAgent") as MockAgent,
        patch("backend.api.legacy_routes.MessageRepository") as MockMsgRepo,
    ):
        MockAgent.return_value.run_loop = mock_run_loop
        MockMsgRepo.return_value.save.side_effect = RuntimeError("simulated db down")

        create_stream = await client.post(
            CHAT_STREAM_PATH,
            json={"session_id": session_id, "message": "this should still stream"},
        )
        assert create_stream.status_code == 200
        stream_id = create_stream.json()["streamId"]

        attach = await client.get(f"{CHAT_STREAM_PATH}/{stream_id}")
        assert attach.status_code == 200
        # attach 文本应至少包含 'done' 事件 (流没被持久化错误打断)
        assert '"state": "done"' in attach.text or '"state":"done"' in attach.text
        # 检查失败 event 也行 (如果有) — 不应抛 500
        assert "RuntimeError" not in attach.text

        entry = app.state.streams.get(stream_id)
        if entry and entry.task:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await entry.task


# =============================================================================
# PR-7b: reasoning_content 持久化
# =============================================================================


@pytest.mark.asyncio()
async def test_streaming_chat_persists_reasoning_content(client):
    """一次带 reasoning 的 chat 后,assistant 消息的 reasoning_content 被写入 DB。"""
    create_sess = await client.post(SESSIONS_PATH, json={"title": "PR-7b reasoning"})
    assert create_sess.status_code == 200, create_sess.text
    session_id = create_sess.json()["id"]

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

        create_stream = await client.post(
            CHAT_STREAM_PATH,
            json={
                "session_id": session_id,
                "message": "PR-7b 回归消息",
                "api_key": "sk-test",
                "api_url": "https://example.com/v1",
                "model": "gpt-4",
            },
        )
        assert create_stream.status_code == 200, create_stream.text
        stream_id = create_stream.json()["streamId"]

        attach = await client.get(f"{CHAT_STREAM_PATH}/{stream_id}")
        assert attach.status_code == 200

        entry = app.state.streams.get(stream_id)
        if entry and entry.task:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await entry.task

    msg_repo = MessageRepository()
    persisted = msg_repo.get_by_session(session_id)
    asst_msg = next((m for m in persisted if m.role == "assistant"), None)
    assert asst_msg is not None, "assistant message not persisted"
    assert (
        asst_msg.reasoning_content == "这是 LLM 的思考过程,会被持久化到 DB"
    ), f"reasoning_content not persisted, got {asst_msg.reasoning_content!r}"
    assert asst_msg.content == "这是 assistant 回答"


@pytest.mark.asyncio()
async def test_streaming_chat_without_reasoning_has_null_reasoning_content(client):
    """不带 reasoning 的 chat,assistant 消息的 reasoning_content 应该是 None。"""
    create_sess = await client.post(SESSIONS_PATH, json={"title": "PR-7b no reasoning"})
    assert create_sess.status_code == 200
    session_id = create_sess.json()["id"]

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(
            state=AgentState.DONE,
            iteration=0,
            content="普通回答,无思考",
        )

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = mock_run_loop

        create_stream = await client.post(
            CHAT_STREAM_PATH,
            json={
                "session_id": session_id,
                "message": "普通消息",
                "api_key": "sk-test",
                "api_url": "https://example.com/v1",
                "model": "gpt-4",
            },
        )
        assert create_stream.status_code == 200
        stream_id = create_stream.json()["streamId"]

        attach = await client.get(f"{CHAT_STREAM_PATH}/{stream_id}")
        assert attach.status_code == 200

        entry = app.state.streams.get(stream_id)
        if entry and entry.task:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await entry.task

    msg_repo = MessageRepository()
    persisted = msg_repo.get_by_session(session_id)
    asst_msg = next((m for m in persisted if m.role == "assistant"), None)
    assert asst_msg is not None
    assert (
        asst_msg.reasoning_content is None
    ), f"reasoning_content should be None when no reasoning event, got {asst_msg.reasoning_content!r}"
