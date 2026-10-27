"""/chat/stream 编排确认窗口集成测试 —— 计划可见性与修订生效。

2026-10-27 从 test_chat_orchestration_stream.py 拆出：该文件已超 800 行
架构门禁上限，而本组测试与「确认窗口 / 计划回读」语义内聚，自成一类。

覆盖：
- task_plan 事件携带 planning reasoning（前端 PlanCard「规划思路」）
- 确认窗口内 update_plan 的修订必须进入 conductor 的 system prompt
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import patch

import httpx
import pytest
from httpx import ASGITransport

from backend.main import app
from backend.tests.integration.test_chat_orchestration_stream import (
    CHAT_STREAM_PATH,
    _mock_plan,
    _stream_events,
)


def _patch_agent(captured_messages: list):
    """构造 SageAgent mock；conductor 的 run_loop 收到的 messages 被捕获。"""

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        from backend.core.legacy.agent_state import AgentEvent, AgentState

        captured_messages.extend(messages)
        yield AgentEvent(state=AgentState.DONE, iteration=0, content="已完成")

    mock_agent = patch("backend.api.legacy_routes.SageAgent")
    instance = mock_agent.start().return_value
    instance.run_loop = mock_run_loop
    instance.tool_registry = type("TR", (), {"register": lambda self, tool: None})()
    instance.profile = {"tools": ["list_dir"]}
    return mock_agent


async def _wait_for_pending_run(session_id: str, timeout: float = 15.0):
    """轮询 orch_runs，直到 producer 落库一条未派发的 run（确认窗口已开）。"""
    from backend.data.orch_run_repo import OrchRunRepository

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for run in OrchRunRepository().list_by_session(session_id):
            if run.dispatched_at is None:
                return run
        await asyncio.sleep(0.02)
    raise AssertionError(f"producer 未在 {timeout}s 内落库 orch_run（session={session_id}）")


@pytest.mark.asyncio()
async def test_task_plan_event_includes_reasoning():
    """规划思路随 task_plan 下发 —— 前端 PlanCard 折叠展示（问题 1）。"""
    mock_agent = _patch_agent([])
    try:
        with patch("backend.orchestration.planner.Planner") as MockPlanner:
            MockPlanner.return_value.decompose_request = _mock_plan()
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                events = await _stream_events(
                    ac,
                    {
                        "session_id": "s",
                        "message": "先搜集资料再整理学习资料",
                        "orchestration_mode": "force_multi",
                    },
                )
    finally:
        mock_agent.stop()

    plan_event = next(e for e in events if e["state"] == "task_plan")
    # _mock_plan 的 reasoning = "test"
    assert plan_event["reasoning"] == "test"


@pytest.mark.asyncio()
async def test_plan_edit_during_confirm_window_reaches_conductor(monkeypatch):
    """P0 回归：确认窗口内的计划编辑必须进入 conductor 的 system prompt。

    修复前 system_content 在确认门控**之前**构造完毕，用户在 PlanCard 的
    编辑 / 自然语言修订只写库、不生效。修复后门控醒来回读 DB 计划。

    注：``ASGITransport`` 会缓冲整个响应体，无法在 NDJSON 流中途发起请求，
    故用「建流 → 轮询 DB 等 run 落库 → 改计划 → confirm → 再 attach 读流」
    还原同一时序。
    """
    monkeypatch.setenv("SAGE_ORCH_CONFIRM_TIMEOUT", "30")
    session_id = "s-plan-edit-window"
    captured_messages: list = []
    mock_agent = _patch_agent(captured_messages)
    try:
        with patch("backend.orchestration.planner.Planner") as MockPlanner:
            MockPlanner.return_value.decompose_request = _mock_plan()
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                create = await ac.post(
                    CHAT_STREAM_PATH,
                    json={
                        "session_id": session_id,
                        "message": "先搜集资料再整理学习资料",
                        "orchestration_mode": "force_multi",
                    },
                )
                assert create.status_code == 200, create.text
                stream_id = create.json()["streamId"]

                run = await _wait_for_pending_run(session_id)
                upd = await ac.post(
                    f"/api/v1/orch/runs/{run.run_id}/plan",
                    json={
                        "plan": [
                            {
                                "task_id": "t1",
                                "agent_id": "researcher",
                                "goal": "改写后的调研步骤",
                            },
                            {
                                "task_id": "t2",
                                "agent_id": "writer",
                                "goal": "改写后的写作步骤",
                            },
                        ],
                        "reasoning": "用户要求改写目标",
                    },
                )
                assert upd.status_code == 200, upd.text
                conf = await ac.post(f"/api/v1/orch/runs/{run.run_id}/confirm")
                assert conf.status_code == 200, conf.text

                attach = await ac.get(f"{CHAT_STREAM_PATH}/{stream_id}")
                assert attach.status_code == 200
                events = [
                    json.loads(line)
                    for line in attach.text.splitlines()
                    if line.strip()
                ]
    finally:
        mock_agent.stop()

    assert any(e["state"] == "task_plan" for e in events)
    assert captured_messages, "conductor 必须收到 messages"
    system_content = captured_messages[0]["content"]
    assert "改写后的调研步骤" in system_content, (
        "确认后回读 DB 计划：修订后的 goal 必须进入 system prompt"
    )
    assert "改写后的写作步骤" in system_content
    assert "目标：researcher" not in system_content, (
        "旧计划不应再出现在 system prompt 中"
    )
