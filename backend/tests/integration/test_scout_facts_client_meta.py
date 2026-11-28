"""事实侦察清单落库集成测试（2026-11-27）。

lite scout 产出的结构化事实清单须落到 ``messages.client_meta.scout_facts``，
供会话气泡回显；同时该键必须从 planner context 里摘除 —— 否则会被
``Planner._build_decomposition_prompt`` 原样 JSON-dump 进 LLM prompt。

覆盖：
  1. 单步 run（无 STEP_DONE）挂终稿 assistant 行
  2. 多步 run（有 STEP_DONE）挂首条 step 行
  3. ``scout_facts_detail`` 不进 planner context
"""

from __future__ import annotations

import contextlib
import json
from unittest.mock import patch

import httpx
import pytest
from httpx import ASGITransport

from backend.main import app

pytestmark = pytest.mark.integration

CHAT_STREAM_PATH = "/api/v1/chat/stream"

#: lite scout 的结构化产出（与 backend.orchestration.scout_facts.to_detail 同形）
SCOUT_DETAIL = {
    "facts": [
        {"text": "事实甲在这里", "source": "文档 A"},
        {"text": "事实乙在这里", "source": ""},
    ],
    "fact_count": 2,
    "truncated": False,
}


def _mock_plan():
    """1-task 的 fake Plan（绕过真实 Planner LLM 调用）。"""

    async def _decompose(message, context=None, progress=None):
        from backend.orchestration.models import Task

        return type(
            "Plan",
            (),
            {
                "plan_id": "p1",
                "team_id": "team1",
                "tasks": [
                    Task(
                        task_id="t1",
                        name="任务 1",
                        description="目标：整理侦察事实",
                        parameters={"agent_hint": "researcher"},
                    )
                ],
                "original_request": message,
                "reasoning": "test",
            },
        )()

    return _decompose


async def _stream_events(ac: httpx.AsyncClient, payload: dict) -> list:
    create_resp = await ac.post(CHAT_STREAM_PATH, json=payload)
    assert create_resp.status_code == 200, create_resp.text
    stream_id = create_resp.json()["streamId"]
    attach_resp = await ac.get(f"{CHAT_STREAM_PATH}/{stream_id}")
    assert attach_resp.status_code == 200
    return [
        json.loads(line)
        for line in attach_resp.text.splitlines()
        if line.strip()
    ]


def _assistant_rows(session_id: str) -> list:
    from backend.data.database import get_database

    cursor = get_database().get_connection().cursor()
    cursor.execute(
        "SELECT id, step_index, client_meta FROM messages "
        "WHERE session_id = ? AND role = 'assistant' ORDER BY created_at, rowid",
        (session_id,),
    )
    return cursor.fetchall()


@contextlib.contextmanager
def _mock_agent(run_loop):
    """替换 SageAgent —— 返回的实例带假 run_loop 与可注册工具的 tool_registry。"""
    with patch("backend.api.legacy_routes.SageAgent") as mock_agent:
        instance = mock_agent.return_value
        instance.run_loop = run_loop
        instance.tool_registry = type(
            "TR", (), {"register": lambda self, tool: None}
        )()
        instance.profile = {"tools": ["list_dir"]}
        yield mock_agent


@pytest.mark.asyncio()
async def test_scout_facts_persist_on_first_assistant_row():
    """单步 run（无 STEP_DONE）→ 事实清单挂终稿 assistant 行的 client_meta。"""
    from backend.data.session_repo import SessionRepository

    repo = SessionRepository()
    session = repo.create(title="事实清单落库")
    session_id = session.id

    async def fake_preflight(message, emit=None, session_id=None):
        return {
            "clarifications": [],
            "scout_facts": "- 事实甲在这里（来源：文档 A）\n- 事实乙在这里",
            "scout_facts_detail": dict(SCOUT_DETAIL),
        }

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        from backend.core.legacy.agent_state import AgentEvent, AgentState

        yield AgentEvent(state=AgentState.DONE, iteration=0, content="侦察完成")

    with _mock_agent(mock_run_loop):  # noqa: SIM117 — py38 不支持括号多上下文 with
        with patch("backend.orchestration.planner.Planner") as mock_planner:
            mock_planner.return_value.decompose_request = _mock_plan()
            with patch(
                "backend.orchestration.plan_preflight.run_plan_preflight",
                fake_preflight,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as ac:
                    await _stream_events(
                        ac,
                        {
                            "session_id": session_id,
                            "message": "整理一下侦察到的事实",
                            "orchestration_mode": "force_multi",
                        },
                    )

    rows = _assistant_rows(session_id)
    assert rows, "应至少落一条 assistant 行"
    first = rows[0]
    assert first["client_meta"], "首条 assistant 行应挂 client_meta"
    payload = json.loads(first["client_meta"])
    assert payload["scout_facts"]["fact_count"] == 2
    assert payload["scout_facts"]["facts"] == SCOUT_DETAIL["facts"]
    # 只挂一条 —— 后续 assistant 行的 client_meta 必须为空（首写语义）
    for later in rows[1:]:
        assert not later["client_meta"], "事实清单只挂首条 assistant 行"


@pytest.mark.asyncio()
async def test_scout_facts_attach_to_step_row_when_multi_step():
    """多步 run（有 STEP_DONE）→ 事实清单挂首条 step 行，而非终稿行。"""
    from backend.data.session_repo import SessionRepository

    repo = SessionRepository()
    session = repo.create(title="事实清单落库-多步")
    session_id = session.id

    async def fake_preflight(message, emit=None, session_id=None):
        return {
            "clarifications": [],
            "scout_facts": "- 事实甲在这里（来源：文档 A）",
            "scout_facts_detail": {
                "facts": [{"text": "事实甲在这里", "source": "文档 A"}],
                "fact_count": 1,
                "truncated": False,
            },
        }

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        from backend.core.legacy.agent_state import (
            AgentEvent,
            AgentState,
            ToolCallRequest,
            ToolCallResult,
        )

        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(
            state=AgentState.ACTING,
            iteration=0,
            tool_call=ToolCallRequest(id="c1", name="list_dir", arguments={}),
        )
        yield AgentEvent(
            state=AgentState.OBSERVING,
            iteration=0,
            tool_result=ToolCallResult(tool_call_id="c1", content="ok"),
        )
        yield AgentEvent(state=AgentState.STEP_DONE, iteration=0, step_index=0)
        yield AgentEvent(state=AgentState.DONE, iteration=1, content="完成")

    with _mock_agent(mock_run_loop):  # noqa: SIM117 — py38 不支持括号多上下文 with
        with patch("backend.orchestration.planner.Planner") as mock_planner:
            mock_planner.return_value.decompose_request = _mock_plan()
            with patch(
                "backend.orchestration.plan_preflight.run_plan_preflight",
                fake_preflight,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as ac:
                    await _stream_events(
                        ac,
                        {
                            "session_id": session_id,
                            "message": "整理一下侦察到的事实",
                            "orchestration_mode": "force_multi",
                        },
                    )

    rows = _assistant_rows(session_id)
    assert len(rows) >= 2, f"多步 run 应落多条 assistant 行，实际 {len(rows)}"
    payload = json.loads(rows[0]["client_meta"])
    assert payload["scout_facts"]["fact_count"] == 1
    assert not rows[1]["client_meta"], "终稿行不应重复挂事实清单"


@pytest.mark.asyncio()
async def test_scout_facts_detail_is_stripped_from_planner_context():
    """``scout_facts_detail`` 只走展示链路，不得进 planner prompt 上下文。"""
    from backend.data.session_repo import SessionRepository

    repo = SessionRepository()
    session = repo.create(title="事实清单不入 prompt")
    session_id = session.id

    captured: dict = {}

    async def fake_preflight(message, emit=None, session_id=None):
        return {
            "clarifications": ["澄清结论"],
            "scout_facts": "- 事实甲在这里（来源：文档 A）",
            "scout_facts_detail": dict(SCOUT_DETAIL),
        }

    async def _decompose(message, context=None, progress=None):
        captured["context"] = dict(context or {})
        return await _mock_plan()(message, context)

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        from backend.core.legacy.agent_state import AgentEvent, AgentState

        yield AgentEvent(state=AgentState.DONE, iteration=0, content="完成")

    with _mock_agent(mock_run_loop):  # noqa: SIM117 — py38 不支持括号多上下文 with
        with patch("backend.orchestration.planner.Planner") as mock_planner:
            mock_planner.return_value.decompose_request = _decompose
            with patch(
                "backend.orchestration.plan_preflight.run_plan_preflight",
                fake_preflight,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as ac:
                    await _stream_events(
                        ac,
                        {
                            "session_id": session_id,
                            "message": "整理一下侦察到的事实",
                            "orchestration_mode": "force_multi",
                        },
                    )

    context = captured.get("context") or {}
    assert "scout_facts_detail" not in context, (
        "scout_facts_detail 必须从 planner context 摘除（否则进 LLM prompt）"
    )
    # 原文那份仍保留 —— planner 靠它做拆解
    assert context.get("scout_facts") == "- 事实甲在这里（来源：文档 A）"
    assert context.get("clarifications") == ["澄清结论"]
