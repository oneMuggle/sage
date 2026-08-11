"""/chat/stream multi-agent 编排集成测试 —— 双失败模式硬约束。

测试 5（复杂任务简单化=0）: force_multi → task_plan 必出 + dispatch 工具必注册
测试 6（简单任务复杂化=0）: single 路径无 task_plan/task_status + 无 dispatch 工具
测试 7: force_single 时复杂消息也不进编排
"""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest
from httpx import ASGITransport

from backend.main import app

CHAT_STREAM_PATH = "/api/v1/chat/stream"


def _mock_plan(agent_hints=("researcher", "writer")):
    """返回 2-task 的 fake Plan（绕过真实 Planner LLM 调用）。

    注: producer 对 ``decompose_request`` 是 ``await``（真实 Planner 为
    async def）, 故 mock 必须是 async 函数。
    """

    async def _decompose(message, context=None):
        from backend.orchestration.models import Task

        return type(
            "Plan",
            (),
            {
                "plan_id": "p1",
                "team_id": "team1",
                "tasks": [
                    Task(
                        task_id=f"t{i + 1}",
                        name=f"任务 {i + 1}",
                        description=f"目标：{hint}",
                        parameters={"agent_hint": hint},
                    )
                    for i, hint in enumerate(agent_hints)
                ],
                "original_request": message,
                "reasoning": "test",
            },
        )()

    return _decompose


async def _stream_events(ac: httpx.AsyncClient, payload: dict) -> list[dict]:
    create_resp = await ac.post(CHAT_STREAM_PATH, json=payload)
    assert create_resp.status_code == 200, create_resp.text
    stream_id = create_resp.json()["streamId"]
    attach_resp = await ac.get(f"{CHAT_STREAM_PATH}/{stream_id}")
    assert attach_resp.status_code == 200
    # attach 返回 NDJSON（每行一个 JSON 对象）——逐行解析为 dict
    return [
        json.loads(line)
        for line in attach_resp.text.splitlines()
        if line.strip()
    ]


@pytest.mark.asyncio()
async def test_multi_mode_emits_task_plan_and_registers_dispatch_tool():
    """复杂任务必进编排：task_plan 事件必出 + dispatch_subagents 工具必注册。"""
    registered_tools: list = []

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        from backend.core.legacy.agent_state import AgentEvent, AgentState

        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(
            state=AgentState.DONE, iteration=0, content="已完成量化交易学习资料整理"
        )

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        instance = MockAgent.return_value
        instance.run_loop = mock_run_loop
        instance.tool_registry = type(
            "TR", (), {"register": lambda self, tool: registered_tools.append(tool.name)}
        )()
        instance.profile = {"tools": ["calculator"]}

        with patch("backend.orchestration.planner.Planner") as MockPlanner:
            MockPlanner.return_value.decompose_request = _mock_plan()

            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                events = await _stream_events(
                    ac,
                    {
                        "session_id": "s",
                        "message": "我需要学习量化交易，先搜集相关资料后整理学习资料和操作指南",
                        "orchestration_mode": "force_multi",
                        "api_key": "sk-test",
                        "api_url": "https://example.com/v1",
                    },
                )

    states = [e["state"] for e in events]
    assert "task_plan" in states, f"task_plan 必出，实际 events={states}"
    plan_event = next(e for e in events if e["state"] == "task_plan")
    assert plan_event["run_id"].startswith("orch-")
    assert len(plan_event["plan"]) == 2
    assert [p["task_id"] for p in plan_event["plan"]] == ["t1", "t2"]
    # 子 agent 跑之前 task_plan 先到（计划先展示）
    assert states.index("task_plan") < states.index("done")

    assert "dispatch_subagents" in registered_tools, (
        "force_multi 必须注册 dispatch 工具（硬约束 1）"
    )


@pytest.mark.asyncio()
async def test_single_mode_has_no_orchestration_events_or_tool():
    """简单任务复杂化=0：single 路径无编排事件 + 无 dispatch 工具。"""
    registered_tools: list = []

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        from backend.core.legacy.agent_state import AgentEvent, AgentState

        yield AgentEvent(state=AgentState.DONE, iteration=0, content="今天晴，22 度")

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        instance = MockAgent.return_value
        instance.run_loop = mock_run_loop
        instance.tool_registry = type(
            "TR", (), {"register": lambda self, tool: registered_tools.append(tool.name)}
        )()
        instance.profile = {"tools": ["calculator"]}

        with patch(
            "backend.api.legacy_routes._classify_orchestration_mode",
            return_value="single",
        ):
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                events = await _stream_events(
                    ac,
                    {
                        "session_id": "s",
                        "message": "今天天气怎么样",
                        "orchestration_mode": "auto",
                    },
                )

    states = [e["state"] for e in events]
    assert "task_plan" not in states, f"single 路径不应有 task_plan: {states}"
    assert "task_status" not in states, f"single 路径不应有 task_status: {states}"
    assert "dispatch_subagents" not in registered_tools, (
        "single 路径必须不注册 dispatch 工具（硬约束 2）"
    )


@pytest.mark.asyncio()
async def test_force_single_skips_orchestration_even_for_complex_message():
    """用户 /single override：复杂消息也不进编排。"""
    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        from backend.core.legacy.agent_state import AgentEvent, AgentState

        yield AgentEvent(state=AgentState.DONE, iteration=0, content="直接回答")

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        instance = MockAgent.return_value
        instance.run_loop = mock_run_loop
        instance.tool_registry = type("TR", (), {"register": lambda self, tool: None})()
        instance.profile = {"tools": ["calculator"]}

        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            events = await _stream_events(
                ac,
                {
                    "session_id": "s",
                    "message": "我需要学习量化交易，先搜集相关资料后整理学习资料",
                    "orchestration_mode": "force_single",
                },
            )

    states = [e["state"] for e in events]
    assert "task_plan" not in states
    assert "task_status" not in states


@pytest.mark.asyncio()
async def test_multi_degrades_to_single_when_plan_has_one_task():
    """Planner 降级为单任务（LLM 没拆开）→ 视为没开编排，无 task_plan。"""
    registered_tools: list = []

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        from backend.core.legacy.agent_state import AgentEvent, AgentState

        yield AgentEvent(state=AgentState.DONE, iteration=0, content="单任务输出")

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        instance = MockAgent.return_value
        instance.run_loop = mock_run_loop
        instance.tool_registry = type(
            "TR", (), {"register": lambda self, tool: registered_tools.append(tool.name)}
        )()
        instance.profile = {"tools": ["calculator"]}

        with patch("backend.orchestration.planner.Planner") as MockPlanner:
            MockPlanner.return_value.decompose_request = _mock_plan(
                agent_hints=("researcher",)
            )

            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                events = await _stream_events(
                    ac,
                    {
                        "session_id": "s",
                        "message": "我有个问题",
                        "orchestration_mode": "force_multi",
                    },
                )

    states = [e["state"] for e in events]
    assert "task_plan" not in states
    assert "dispatch_subagents" not in registered_tools
