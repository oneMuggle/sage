"""legacy_routes /chat/stream STEP_DONE 持久化集成测试 (2026-09 step-by-step)

验证当 agent.run_loop 产出 STEP_DONE 事件时,legacy_routes producer 把
每个迭代边界的内容快照成一行 assistant 消息,最终 DONE 也写一行,使得
N 步 run 产生 N+1 条 assistant 行。同时验证 message_count 增量 = N+2。

测试路径:
  - 单步 run (无 STEP_DONE):1 user + 1 final = 2 messages
  - 2 步 run (1 STEP_DONE + 1 final):1 user + 1 step + 1 final = 3 messages
  - 3 步 run (2 STEP_DONE + 1 final):1 user + 2 steps + 1 final = 4 messages
  - STEP_DONE 事件被 NDJSON 队列转发,前端可 snapshot 气泡

Plan quote (glowing-cooking-gadget.md §Verification):
    "backend/tests/test_legacy_routes_step_persistence.py:断言 N 步 run 产生 N+1 条 assistant 行,
    message_count += N+1"
"""

from __future__ import annotations

import json
from typing import List
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.core.legacy.agent_state import (
    AgentEvent,
    AgentState,
    ToolCallRequest,
    ToolCallResult,
)
from backend.main import app

pytestmark = pytest.mark.integration

CHAT_STREAM_PATH = "/api/v1/chat/stream"


def _parse_ndjson(text: str) -> List[dict]:
    return [json.loads(line) for line in text.split("\n") if line.strip()]


def _ensure_stream_registry():
    from backend.api.chat_stream_registry import StreamRegistry

    if not hasattr(app.state, "streams") or app.state.streams is None:
        app.state.streams = StreamRegistry()


@pytest.mark.asyncio()
async def test_single_step_run_writes_one_user_and_one_final_assistant():
    """单步纯文本回答:无 STEP_DONE 事件 → 1 user + 1 final = 2 messages。

    这是基线测试,确认 step-by-step 改动未破坏旧单步路径。
    """
    _ensure_stream_registry()
    from backend.data.database import get_database
    from backend.data.session_repo import SessionRepository

    repo = SessionRepository()
    session = repo.create(title="单步基线")
    session_id = session.id

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(state=AgentState.DONE, iteration=0, content="最终回答")

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = mock_run_loop

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-Sage-Local-Authorization": "Bearer test-local-auth-token"},
        ) as ac:
            create_resp = await ac.post(
                CHAT_STREAM_PATH,
                json={"session_id": session_id, "message": "hi"},
            )
            assert create_resp.status_code == 200
            stream_id = create_resp.json()["streamId"]

            attach_resp = await ac.get(f"{CHAT_STREAM_PATH}/{stream_id}")
            assert attach_resp.status_code == 200

    # 验证 DB
    db = get_database()
    cursor = db.get_connection().cursor()
    cursor.execute(
        "SELECT role, step_index FROM messages WHERE session_id = ? ORDER BY created_at, rowid",
        (session_id,),
    )
    rows = cursor.fetchall()
    assert len(rows) == 2, f"expected 2 messages, got {len(rows)}: {rows}"
    assert rows[0]["role"] == "user"
    assert rows[1]["role"] == "assistant"
    # 单步 run: final 行 step_index == done_event.iteration == 0
    assert rows[1]["step_index"] == 0

    # message_count == 2
    updated = repo.get(session_id)
    assert updated is not None
    assert updated.message_count == 2


@pytest.mark.asyncio()
async def test_two_step_run_writes_one_step_and_one_final_assistant():
    """2 步 run (1 STEP_DONE + 1 final): 1 user + 1 step + 1 final = 3 messages。

    验证:
      1. assistant 行数 = 1 (step_index=0) + 1 (final, step_index=1)
      2. 每条 assistant 行 step_index 对齐
      3. 中间 step 行 tool_calls 非空 (工具调用在该步累积)
      4. message_count == 3
    """
    _ensure_stream_registry()
    from backend.data.database import get_database
    from backend.data.session_repo import SessionRepository

    repo = SessionRepository()
    session = repo.create(title="2 步 run")
    session_id = session.id

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        # Step 0: 第一次工具调用
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(
            state=AgentState.ACTING,
            iteration=0,
            tool_call=ToolCallRequest(
                id="call_a",
                name="calculator",
                arguments={"expression": "1+1"},
            ),
        )
        yield AgentEvent(
            state=AgentState.OBSERVING,
            iteration=0,
            tool_result=ToolCallResult(tool_call_id="call_a", content="2"),
        )
        # 迭代边界 → STEP_DONE (step_index=0)
        yield AgentEvent(
            state=AgentState.STEP_DONE,
            iteration=0,
            step_index=0,
        )
        # Step 1 (final): 纯文本回答
        yield AgentEvent(
            state=AgentState.THINKING,
            iteration=1,
            reasoning="最终 reasoning",
        )
        yield AgentEvent(
            state=AgentState.DONE,
            iteration=1,
            content="最终答案",
        )

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = mock_run_loop

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-Sage-Local-Authorization": "Bearer test-local-auth-token"},
        ) as ac:
            create_resp = await ac.post(
                CHAT_STREAM_PATH,
                json={"session_id": session_id, "message": "1+1 等于几"},
            )
            assert create_resp.status_code == 200
            stream_id = create_resp.json()["streamId"]

            attach_resp = await ac.get(f"{CHAT_STREAM_PATH}/{stream_id}")
            assert attach_resp.status_code == 200

            # 确保 STEP_DONE 事件被 NDJSON 队列转发
            events = _parse_ndjson(attach_resp.text)
            step_done_events = [e for e in events if e["state"] == "step_done"]
            assert len(step_done_events) == 1
            assert step_done_events[0]["step_index"] == 0

    # 验证 DB
    db = get_database()
    cursor = db.get_connection().cursor()
    cursor.execute(
        "SELECT role, step_index, tool_calls, content FROM messages "
        "WHERE session_id = ? ORDER BY created_at, rowid",
        (session_id,),
    )
    rows = cursor.fetchall()
    assert len(rows) == 3, f"expected 3 messages, got {len(rows)}: {rows}"

    # 第 1 行:user
    assert rows[0]["role"] == "user"

    # 第 2 行:中间 step (step_index=0, 工具调用)
    assert rows[1]["role"] == "assistant"
    assert rows[1]["step_index"] == 0
    # 中间 step 应有 tool_calls 非空 (ACTING + OBSERVING 累积)
    assert rows[1]["tool_calls"] is not None
    tool_calls_data = json.loads(rows[1]["tool_calls"])
    assert len(tool_calls_data) >= 1
    assert tool_calls_data[0]["name"] == "calculator"

    # 第 3 行:final (step_index=1, 无 tool_calls)
    assert rows[2]["role"] == "assistant"
    assert rows[2]["step_index"] == 1
    assert rows[2]["content"] == "最终答案"
    assert rows[2]["tool_calls"] is None

    # message_count == 3
    updated = repo.get(session_id)
    assert updated is not None
    assert updated.message_count == 3


@pytest.mark.asyncio()
async def test_three_step_run_writes_two_steps_and_one_final_assistant():
    """3 步 run (2 STEP_DONE + 1 final): 1 user + 2 steps + 1 final = 4 messages。

    验证 N 步 run 的通用逻辑:N 步 → N+1 条 assistant 行。
    """
    _ensure_stream_registry()
    from backend.data.database import get_database
    from backend.data.session_repo import SessionRepository

    repo = SessionRepository()
    session = repo.create(title="3 步 run")
    session_id = session.id

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        # Step 0: 工具调用
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(
            state=AgentState.ACTING,
            iteration=0,
            tool_call=ToolCallRequest(id="call_1", name="bash", arguments={"cmd": "ls"}),
        )
        yield AgentEvent(
            state=AgentState.OBSERVING,
            iteration=0,
            tool_result=ToolCallResult(tool_call_id="call_1", content="file.txt"),
        )
        yield AgentEvent(state=AgentState.STEP_DONE, iteration=0, step_index=0)

        # Step 1: 另一个工具调用
        yield AgentEvent(state=AgentState.THINKING, iteration=1)
        yield AgentEvent(
            state=AgentState.ACTING,
            iteration=1,
            tool_call=ToolCallRequest(
                id="call_2", name="read", arguments={"path": "file.txt"}
            ),
        )
        yield AgentEvent(
            state=AgentState.OBSERVING,
            iteration=1,
            tool_result=ToolCallResult(tool_call_id="call_2", content="hello"),
        )
        yield AgentEvent(state=AgentState.STEP_DONE, iteration=1, step_index=1)

        # Step 2 (final): 纯文本
        yield AgentEvent(state=AgentState.THINKING, iteration=2)
        yield AgentEvent(state=AgentState.DONE, iteration=2, content="最终总结")

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = mock_run_loop

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-Sage-Local-Authorization": "Bearer test-local-auth-token"},
        ) as ac:
            create_resp = await ac.post(
                CHAT_STREAM_PATH,
                json={"session_id": session_id, "message": "多步任务"},
            )
            assert create_resp.status_code == 200
            stream_id = create_resp.json()["streamId"]

            attach_resp = await ac.get(f"{CHAT_STREAM_PATH}/{stream_id}")
            assert attach_resp.status_code == 200

            events = _parse_ndjson(attach_resp.text)
            step_done_events = [e for e in events if e["state"] == "step_done"]
            assert len(step_done_events) == 2
            assert [e["step_index"] for e in step_done_events] == [0, 1]

    # 验证 DB
    db = get_database()
    cursor = db.get_connection().cursor()
    cursor.execute(
        "SELECT role, step_index FROM messages WHERE session_id = ? "
        "ORDER BY created_at, rowid",
        (session_id,),
    )
    rows = cursor.fetchall()
    assert len(rows) == 4, f"expected 4 messages, got {len(rows)}: {rows}"

    # 1 user + 3 assistant
    assert rows[0]["role"] == "user"
    assert rows[1]["role"] == "assistant"
    assert rows[2]["role"] == "assistant"
    assert rows[3]["role"] == "assistant"

    # step_index 集合 = {0, 1, 2} (N+1 个 assistant 行覆盖 0..N)
    assistant_step_indices = {r["step_index"] for r in rows if r["role"] == "assistant"}
    assert assistant_step_indices == {0, 1, 2}

    # message_count == 4
    updated = repo.get(session_id)
    assert updated is not None
    assert updated.message_count == 4


@pytest.mark.asyncio()
async def test_step_done_events_are_forwarded_to_ndjson_queue():
    """STEP_DONE 事件必须被 legacy_routes 推入 NDJSON 队列,前端据此 snapshot 气泡。"""
    _ensure_stream_registry()
    from backend.data.session_repo import SessionRepository

    repo = SessionRepository()
    session = repo.create(title="NDJSON 转发")
    session_id = session.id

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(
            state=AgentState.ACTING,
            iteration=0,
            tool_call=ToolCallRequest(id="c1", name="x", arguments={}),
        )
        yield AgentEvent(
            state=AgentState.OBSERVING,
            iteration=0,
            tool_result=ToolCallResult(tool_call_id="c1", content="ok"),
        )
        yield AgentEvent(state=AgentState.STEP_DONE, iteration=0, step_index=0)
        yield AgentEvent(state=AgentState.DONE, iteration=1, content="done")

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = mock_run_loop

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-Sage-Local-Authorization": "Bearer test-local-auth-token"},
        ) as ac:
            create_resp = await ac.post(
                CHAT_STREAM_PATH,
                json={"session_id": session_id, "message": "hi"},
            )
            stream_id = create_resp.json()["streamId"]
            attach_resp = await ac.get(f"{CHAT_STREAM_PATH}/{stream_id}")

    events = _parse_ndjson(attach_resp.text)
    states = [e["state"] for e in events]

    # STEP_DONE 必须出现在 OBSERVING 之后、DONE 之前
    assert "step_done" in states
    observing_idx = states.index("observing")
    step_done_idx = states.index("step_done")
    assert step_done_idx > observing_idx
    # done 事件也在 step_done 之后 (可能先有 content_delta)
    done_idx = len(states) - 1 - states[::-1].index("done")
    assert step_done_idx < done_idx

    # STEP_DONE 事件必须携带 step_index 字段
    step_done_event = next(e for e in events if e["state"] == "step_done")
    assert "step_index" in step_done_event
    assert step_done_event["step_index"] == 0
