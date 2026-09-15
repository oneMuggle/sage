"""/chat/stream 集成测试: M6 SAGE.md/CLAUDE.md 项目上下文注入。

已绑定 workspace 的会话 → system prompt 含 "项目指令" 块;
未绑定 → 不注入。mock SageAgent.run_loop 捕获实际 messages。
"""

from __future__ import annotations

from typing import List
from unittest.mock import patch

import pytest

from backend.chat.project_context import RENDER_HEADER
from backend.core.legacy.agent_state import AgentEvent, AgentState
from backend.data.database import get_database
from backend.office.session_workspace import bind_session_workspace

pytestmark = pytest.mark.integration

CHAT_STREAM_PATH = "/api/v1/chat/stream"
SESSION_BOUND = "m6-ctx-bound"
SESSION_UNBOUND = "m6-ctx-unbound"


@pytest.fixture()
def captured_run_loop_messages():
    calls: List[List[dict]] = []

    async def mock_run_loop(messages, **kwargs):
        calls.append([dict(message) for message in messages])
        yield AgentEvent(state=AgentState.THINKING, iteration=0)

    with patch("backend.api.legacy_routes.SageAgent") as mock_agent:
        mock_agent.return_value.run_loop = mock_run_loop
        yield calls


def _ensure_session(session_id: str) -> None:
    conn = get_database().get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (session_id, "M6 ctx test", 1, 1),
    )
    conn.commit()


async def _chat_once(client, captured_messages, session_id: str) -> List[dict]:
    create_response = await client.post(
        CHAT_STREAM_PATH,
        json={"session_id": session_id, "message": "你好"},
    )
    assert create_response.status_code == 200, create_response.text
    stream_id = create_response.json()["streamId"]
    attach_response = await client.get(f"{CHAT_STREAM_PATH}/{stream_id}")
    assert attach_response.status_code == 200, attach_response.text
    assert len(captured_messages) == 1
    return captured_messages[0]


def _system_content(messages: List[dict]) -> str:
    return " ".join(
        m.get("content") or "" for m in messages if m.get("role") == "system"
    )


@pytest.mark.asyncio()
async def test_bound_workspace_injects_project_context(
    client, captured_run_loop_messages, tmp_path
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "SAGE.md").write_text("始终用中文回答测试标记 M6CTX", encoding="utf-8")

    _ensure_session(SESSION_BOUND)
    conn = get_database().get_connection()
    bind_session_workspace(conn, SESSION_BOUND, str(workspace))

    messages = await _chat_once(client, captured_run_loop_messages, SESSION_BOUND)

    system_text = _system_content(messages)
    assert RENDER_HEADER in system_text
    assert "始终用中文回答测试标记 M6CTX" in system_text
    assert str(workspace) in system_text


@pytest.mark.asyncio()
async def test_unbound_session_gets_no_injection(client, captured_run_loop_messages):
    messages = await _chat_once(client, captured_run_loop_messages, SESSION_UNBOUND)

    system_text = _system_content(messages)
    assert RENDER_HEADER not in system_text
    assert system_text, "基础 system prompt 仍然存在"
