"""Wave 3 B2 — API lane 真实执行：wait=true 同步终态 + review；wait=false 后台。"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio()
async def test_execute_plan_lanes_parallel_terminal_states(tmp_path, monkeypatch):
    """_execute_plan_lanes：全部 lane 终态落库 + 聚合后跑 review。"""
    # _execute_plan_lanes 内部经 get_database().db_path 派生 scratch 根 + 读
    # orch_settings —— SAGE_DB_PATH 指到 tmp 隔离，避免写真实 data 目录。
    monkeypatch.setenv("SAGE_DB_PATH", str(tmp_path / "b2.db"))
    from backend.data import database as db_mod
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()

    from backend.api.orchestration_router import _execute_plan_lanes
    from backend.orchestration.orch_settings import OrchSettings

    lane_registry = MagicMock()
    task_registry = MagicMock()
    event_recorder = MagicMock()
    lane_registry.list_all_lanes.return_value = []

    async def fake_run_lane(executor, lane, agent_id):
        return {"status": "succeeded", "result": {"output": f"out-{lane.lane_id}"}}

    # patch 目标 = _execute_plan_lanes 内部 lazy-import 的真实模块
    #（backend.api.orchestration_router.run_review 是无效目标）。
    with patch("backend.orchestration.subagent_runner.run_lane_with_retry", fake_run_lane), \
         patch("backend.orchestration.orch_settings.load_orch_settings", return_value=OrchSettings()), \
         patch("backend.orchestration.review.run_review", AsyncMock(return_value={"verdict": "pass", "block": "", "assertion_count": 1})):
        lanes = [
            MagicMock(lane_id="l1", task_id="task-1", agent_id="researcher", metadata={}, status=MagicMock()),
            MagicMock(lane_id="l2", task_id="task-2", agent_id="writer", metadata={}, status=MagicMock()),
        ]
        review = await _execute_plan_lanes(
            plan=MagicMock(team_id="team-1"),
            lanes=lanes,
            lane_registry=lane_registry,
            task_registry=task_registry,
            event_recorder=event_recorder,
            llm_config={"model": "x"},
        )
    # 每个 lane 都 mark_running + mark_completed
    assert task_registry.mark_running.call_count == 2
    assert task_registry.mark_completed.call_count == 2
    assert lane_registry.mark_completed.call_count == 2
    # 聚合后跑了 review（非 None = run_review 被调用过）
    assert review == {"verdict": "pass", "block": "", "assertion_count": 1}


@pytest.mark.asyncio()
async def test_create_lanes_router_exposes_wait_query():
    """路由层：/lanes POST 存在，且 handler 接受 wait query。

    不用 str(r.dependant.query_params)（FastAPI 内部结构随版本漂移）——
    用 inspect.signature 看端点签名最稳。
    """
    from inspect import signature

    from backend.api.orchestration_router import build_router

    router = build_router()
    # 注意：APIRoute.path 含 router prefix（"/orchestration"），因此完整路径
    # 是 "/orchestration/lanes" 而非 "/lanes"（brief 原文写成 "/lanes" 会恒空）。
    lanes_post = [
        r for r in router.routes
        if getattr(r, "path", None) == "/orchestration/lanes"
        and "POST" in (getattr(r, "methods", None) or set())
    ]
    assert len(lanes_post) == 1
    assert "wait" in signature(lanes_post[0].endpoint).parameters
