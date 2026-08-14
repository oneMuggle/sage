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


@pytest.mark.asyncio()
async def test_execute_plan_lanes_wires_goal_and_scratch_dir_into_task_params(tmp_path, monkeypatch):
    """P0-3 工作区隔离接线：SubagentRunner 收到的 task 必须带 goal + scratch_dir。

    brief 原文只写 task.packet，从不写 task.parameters["goal"] /
    ["scratch_dir"] —— SubagentRunner.__call__ 只读这两个 key（空 user
    message + 拿不到 scratch 根）。用真实 Task（parameters 是真 dict）而非
    MagicMock（MagicMock 的 .parameters 自动生成属性会掩盖缺陷），且**不**
    patch run_lane_with_retry——让真实 LaneExecutor + 真实 run_lane_with_retry
    把 task 一路送到 agent_runner 处截获断言。
    """
    monkeypatch.setenv("SAGE_DB_PATH", str(tmp_path / "b2-wire.db"))
    from backend.data import database as db_mod
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()

    from backend.api.orchestration_router import _execute_plan_lanes
    from backend.orchestration.models import Task
    from backend.orchestration.orch_settings import OrchSettings

    task = Task(task_id="task-1", name="t1", description="真实目标", parameters={})
    task_registry = MagicMock()
    task_registry.get_task.return_value = task
    lane_registry = MagicMock()
    event_recorder = MagicMock()

    captured: dict = {}

    async def fake_agent_runner(task, agent_id):
        # SubagentRunner 契约：goal + scratch_dir 必须已在 task.parameters 里。
        captured["goal"] = task.parameters.get("goal", "")
        captured["scratch_dir"] = task.parameters.get("scratch_dir")
        return {"status": "succeeded", "output": "ok"}

    # 只 patch SubagentRunner（换成记录参数的 fake）；run_lane_with_retry 与
    # LaneExecutor 走真实实现，确保 task 从 run_one 一路流到 agent_runner。
    with patch("backend.orchestration.subagent_runner.SubagentRunner", lambda llm_config: fake_agent_runner), \
         patch("backend.orchestration.orch_settings.load_orch_settings", return_value=OrchSettings()):
        lanes = [
            MagicMock(lane_id="l1", task_id="task-1", agent_id="researcher", metadata={}, status=MagicMock()),
        ]
        await _execute_plan_lanes(
            plan=MagicMock(team_id="team-1"),
            lanes=lanes,
            lane_registry=lane_registry,
            task_registry=task_registry,
            event_recorder=event_recorder,
            llm_config={"model": "x"},
        )
    # 接线后 goal 透传为 task.description；scratch_dir 是含 lane_id 的路径。
    assert captured["goal"] == "真实目标"
    assert captured["scratch_dir"]
    assert "l1" in captured["scratch_dir"]


@pytest.mark.asyncio()
async def test_execute_plan_lanes_failure_evidence_reaches_review(tmp_path, monkeypatch):
    """P2-9 聚合：失败 lane 的错误必须进聚合（task.parameters["error"]）。

    brief 原文用 getattr(task, "error") —— Task 没有 .error 字段，恒 None，
    该分支是死代码，失败证据从不进聚合，run_review 不触发。真实
    TaskRegistry.mark_failed 把错误写进 parameters["error"]，聚合必须读到它。
    """
    monkeypatch.setenv("SAGE_DB_PATH", str(tmp_path / "b2-agg.db"))
    from backend.data import database as db_mod
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()

    from backend.api.orchestration_router import _execute_plan_lanes
    from backend.orchestration.lane_registry import LaneRegistry
    from backend.orchestration.models import Task
    from backend.orchestration.orch_settings import OrchSettings
    from backend.orchestration.task_registry import TaskRegistry

    # 真实注册表：task.mark_failed 把错误写进 parameters["error"]（Task 无 .error 字段）。
    task_registry = TaskRegistry()
    lane_registry = LaneRegistry()
    event_recorder = MagicMock()
    task = task_registry.create_task(
        Task(task_id="task-1", name="t1", description="目标", parameters={})
    )
    lane = lane_registry.create_lane(task.task_id, metadata={})

    async def fake_run_lane(executor, lane, agent_id):
        return {"status": "failed", "error": "boom: LLM 未配置"}

    with patch("backend.orchestration.subagent_runner.run_lane_with_retry", fake_run_lane), \
         patch("backend.orchestration.orch_settings.load_orch_settings", return_value=OrchSettings()), \
         patch(
             "backend.orchestration.review.run_review",
             AsyncMock(return_value={"verdict": "fail", "block": "", "assertion_count": 0}),
         ) as run_review_mock:
        review = await _execute_plan_lanes(
            plan=MagicMock(team_id="team-1"),
            lanes=[lane],
            lane_registry=lane_registry,
            task_registry=task_registry,
            event_recorder=event_recorder,
            llm_config={"model": "x"},
        )
    # 失败证据进聚合 → run_review 被调用 → review 返回 mock 判定。
    assert review == {"verdict": "fail", "block": "", "assertion_count": 0}
    run_review_mock.assert_awaited_once()
