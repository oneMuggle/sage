"""B2 (对话阅读体验第二轮): finish_reason 透传与落库。

覆盖:
- AgentEvent: finish_reason 序列化 / 缺省不输出 / 非 str 归一为 None
- run_loop: 终稿 DONE 事件从 LLM 响应带出 finish_reason
- 仓储: save → get_by_session → to_dict 往返; fork 复制截断标记
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.legacy.agent import SageAgent
from backend.core.legacy.agent_state import AgentEvent, AgentState
from backend.core.legacy.llm_client import LLMResponse

pytestmark = pytest.mark.unit


def test_agent_event_serializes_finish_reason():
    evt = AgentEvent(state=AgentState.DONE, content="x", finish_reason="length")
    assert evt.to_dict()["finish_reason"] == "length"


def test_agent_event_omits_missing_finish_reason():
    assert "finish_reason" not in AgentEvent(state=AgentState.DONE, content="x").to_dict()


def test_agent_event_drops_non_string_finish_reason():
    evt = AgentEvent(state=AgentState.DONE, content="x", finish_reason=MagicMock())
    assert evt.finish_reason is None
    assert "finish_reason" not in evt.to_dict()


@pytest.mark.asyncio()
async def test_run_loop_done_carries_finish_reason():
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        return_value=LLMResponse(content="被截断的回答", tool_calls=[], finish_reason="length")
    )
    events = [evt async for evt in agent.run_loop([{"role": "user", "content": "hi"}])]

    done = next(e for e in events if e.state == AgentState.DONE)
    assert done.content == "被截断的回答"
    assert done.finish_reason == "length"
    assert done.to_dict()["finish_reason"] == "length"


def test_message_finish_reason_roundtrip(setup_test_db):
    from backend.data.session_repo import Message, MessageRepository, SessionRepository

    session = SessionRepository().create(title="b2")
    repo = MessageRepository()
    repo.save(Message(id="u-1", session_id=session.id, role="user", content="hi", created_at=1))
    repo.save(
        Message(
            id="a-1",
            session_id=session.id,
            role="assistant",
            content="写到一半",
            created_at=2,
            finish_reason="length",
        )
    )

    rows = {m.id: m for m in repo.get_by_session(session.id)}
    assert rows["a-1"].finish_reason == "length"
    assert rows["a-1"].to_dict()["finish_reason"] == "length"
    assert rows["u-1"].to_dict()["finish_reason"] is None


def test_message_from_row_without_finish_reason_column():
    from backend.data.session_repo import Message

    row = {
        "id": "m",
        "session_id": "s",
        "role": "assistant",
        "content": "c",
        "created_at": 1,
        "model": None,
        "provider": None,
        "tool_calls": None,
        "tool_call_id": None,
        "reasoning_content": None,
    }
    assert Message.from_row(row).finish_reason is None


def test_fork_copies_finish_reason(setup_test_db):
    from backend.data.session_repo import (
        Message,
        MessageRepository,
        SessionRepository,
        fork_session,
    )

    session_repo = SessionRepository()
    message_repo = MessageRepository()
    source = session_repo.create(title="b2-fork")
    message_repo.save(
        Message(id="u-2", session_id=source.id, role="user", content="q", created_at=1)
    )
    message_repo.save(
        Message(
            id="a-2",
            session_id=source.id,
            role="assistant",
            content="截断的回答",
            created_at=2,
            finish_reason="length",
        )
    )

    forked = fork_session(session_repo, message_repo, source.id)

    copied = [m for m in message_repo.get_by_session(forked.id) if m.role == "assistant"]
    assert [m.finish_reason for m in copied] == ["length"]
