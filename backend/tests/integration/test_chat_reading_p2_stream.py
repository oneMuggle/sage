# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""/chat/stream 对话阅读体验第二轮：C1 生成统计落库、C2 原位重新生成与版本切换。

harness 与 test_chat_stream_persist.py 相同：patch ``legacy_routes.SageAgent``，
mock run_loop 同时捕获发给 LLM 的 messages，断言历史里没有重复的 user 消息、
也没有旧回答。
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from backend.core.errors import LLMError, LLMErrorType
from backend.core.legacy.agent_state import AgentEvent, AgentState
from backend.data.session_repo import Message, MessageRepository, SessionRepository
from backend.main import app

pytestmark = [pytest.mark.integration]

CHAT_STREAM_PATH = "/api/v1/chat/stream"


async def _run_stream(client, session_id: str, message: str, **payload_extra):
    response = await client.post(
        CHAT_STREAM_PATH,
        json={"session_id": session_id, "message": message, **payload_extra},
    )
    if response.status_code != 200:
        return response
    stream_id = response.json()["streamId"]
    attach = await client.get(f"{CHAT_STREAM_PATH}/{stream_id}")
    assert attach.status_code == 200
    entry = app.state.streams.get(stream_id)
    if entry and entry.task:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await entry.task
    return response


def _agent_answering(answer: str, captured: List[List[Dict[str, Any]]], **done_fields):
    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        captured.append(list(messages))
        yield AgentEvent(state=AgentState.DONE, iteration=0, content=answer, **done_fields)

    return mock_run_loop


def _persisted(session_id: str):
    return MessageRepository().get_by_session(session_id)


@pytest.mark.asyncio()
async def test_final_answer_persists_generation_stats(client):
    session = SessionRepository().create(title="C1")
    stats = {"output_tokens": 30, "first_token_ms": 250, "latency_ms": 1500}

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = _agent_answering("答", [], generation_stats=stats)
        MockAgent.return_value.memory_manager = None
        await _run_stream(client, session.id, "问")

    answer = next(m for m in _persisted(session.id) if m.role == "assistant")
    assert answer.to_dict()["generation_stats"] == stats


@pytest.mark.asyncio()
async def test_regenerate_in_place_replaces_the_answer_and_keeps_a_version(client):
    session = SessionRepository().create(title="C2")
    captured: List[List[Dict[str, Any]]] = []

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.memory_manager = None
        MockAgent.return_value.run_loop = _agent_answering("第一版", captured)
        await _run_stream(client, session.id, "同一个问题")
        user = next(m for m in _persisted(session.id) if m.role == "user")

        MockAgent.return_value.run_loop = _agent_answering("第二版", captured)
        response = await _run_stream(
            client, session.id, "同一个问题", regenerate_of=user.id
        )
    assert response.status_code == 200

    # 发给 LLM 的历史: user 消息只出现一次, 不含旧回答
    regen_messages = captured[-1]
    assert sum(1 for m in regen_messages if m.get("content") == "同一个问题") == 1
    assert all("第一版" not in str(m.get("content")) for m in regen_messages)

    persisted = _persisted(session.id)
    assert [(m.role, m.content) for m in persisted] == [
        ("user", "同一个问题"),
        ("assistant", "第二版"),
    ]
    assert SessionRepository().get(session.id).message_count == 2

    listing = (await client.get(f"/api/v1/sessions/{session.id}/answer-versions")).json()
    assert listing["total"] == 2
    assert listing["current_index"] == 2

    archived_id = listing["versions"][0]["id"]
    activated = await client.post(
        f"/api/v1/sessions/{session.id}/answer-versions/{archived_id}/activate"
    )
    assert activated.status_code == 200
    assert activated.json() == {"ok": True, "restored": 1}
    assert [(m.role, m.content) for m in _persisted(session.id)] == [
        ("user", "同一个问题"),
        ("assistant", "第一版"),
    ]
    listing = (await client.get(f"/api/v1/sessions/{session.id}/answer-versions")).json()
    assert listing["current_index"] == 1


@pytest.mark.asyncio()
async def test_failed_regenerate_keeps_the_previous_answer(client):
    session = SessionRepository().create(title="C2-failure")

    async def failing_run_loop(messages, max_iterations=5, **kwargs):
        raise LLMError(LLMErrorType.NETWORK, "endpoint down")
        yield  # pragma: no cover — 让函数成为异步生成器

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.memory_manager = None
        MockAgent.return_value.run_loop = _agent_answering("原回答", [])
        await _run_stream(client, session.id, "问")
        user = next(m for m in _persisted(session.id) if m.role == "user")

        MockAgent.return_value.run_loop = failing_run_loop
        await _run_stream(client, session.id, "问", regenerate_of=user.id)

    assert [(m.role, m.content) for m in _persisted(session.id)] == [
        ("user", "问"),
        ("assistant", "原回答"),
    ]
    listing = (await client.get(f"/api/v1/sessions/{session.id}/answer-versions")).json()
    assert listing["total"] == 1


@pytest.mark.asyncio()
async def test_regenerate_is_rejected_for_earlier_turns(client):
    session = SessionRepository().create(title="C2-earlier")
    repo = MessageRepository()
    for i, (role, content) in enumerate(
        [("user", "一"), ("assistant", "答一"), ("user", "二"), ("assistant", "答二")]
    ):
        repo.save(
            Message(id=f"m{i}", session_id=session.id, role=role, content=content, created_at=i + 1)
        )

    response = await client.post(
        CHAT_STREAM_PATH,
        json={"session_id": session.id, "message": "一", "regenerate_of": "m0"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["type"] == "anchor_not_last"


@pytest.mark.asyncio()
async def test_activating_an_unknown_version_returns_404(client):
    session = SessionRepository().create(title="C2-404")

    response = await client.post(
        f"/api/v1/sessions/{session.id}/answer-versions/ver-missing/activate"
    )

    assert response.status_code == 404
    assert response.json()["detail"]["type"] == "version_not_found"
