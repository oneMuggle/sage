"""
Orchestrator 并行执行测试（阶段 3）

验证:
1. _execute_multi_step 用 asyncio.gather 并行执行子任务
2. 并行执行时间 < 串行（至少快 30%）
3. 结果顺序与输入顺序一致
4. 单个子任务失败不影响其他（错误隔离）
"""

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from backend.core.legacy.orchestrator import AgentOrchestrator

pytestmark = pytest.mark.unit


@pytest.mark.asyncio()
async def test_execute_multi_step_runs_subtasks_in_parallel():
    """多步骤任务的子任务应并行执行 (总时间 ≈ 最慢子任务, 而非累加)。"""
    orchestrator = AgentOrchestrator()

    # Mock _decompose_task 返回 3 个子任务
    orchestrator._decompose_task = AsyncMock(
        return_value=[
            {"intent": "general", "description": "子任务 1"},
            {"intent": "general", "description": "子任务 2"},
            {"intent": "general", "description": "子任务 3"},
        ]
    )

    # Mock _aggregate_results 直接返回拼接结果
    orchestrator._aggregate_results = AsyncMock(side_effect=lambda msg, res: "聚合结果")

    # Mock _execute_agent_task, 每个子任务耗时 0.3 秒
    async def slow_execute(session_id, agent_id, message, history=None):
        await asyncio.sleep(0.3)
        return {"agent_id": agent_id, "response": f"响应: {message}", "task_id": "t1"}

    orchestrator._execute_agent_task = AsyncMock(side_effect=slow_execute)

    # 跑多步骤任务
    start = time.time()
    await orchestrator._execute_multi_step("sess-1", "复杂任务", None)
    elapsed = time.time() - start

    # 关键断言: 并行执行, 总时间应 ≈ 0.3 秒 (不是 0.9 秒)
    # 容忍一定 overhead, 但必须 < 0.6 秒 (串行会 > 0.9 秒)
    assert elapsed < 0.6, f"并行执行时间 {elapsed:.2f}s 太长, 可能没并行"

    # 验证 3 个子任务都被执行
    assert orchestrator._execute_agent_task.call_count == 3

    # 验证聚合被调用
    assert orchestrator._aggregate_results.called


@pytest.mark.asyncio()
async def test_execute_multi_step_preserves_result_order():
    """并行执行后, 结果顺序应与输入子任务顺序一致。"""
    orchestrator = AgentOrchestrator()

    orchestrator._decompose_task = AsyncMock(
        return_value=[
            {"intent": "general", "description": "A"},
            {"intent": "general", "description": "B"},
            {"intent": "general", "description": "C"},
        ]
    )

    delays = {"A": 0.2, "B": 0.05, "C": 0.1}

    async def variable_execute(session_id, agent_id, message, history=None):
        await asyncio.sleep(delays.get(message, 0.1))
        return {"agent_id": agent_id, "response": f"响应-{message}", "task_id": "t"}

    orchestrator._execute_agent_task = AsyncMock(side_effect=variable_execute)

    captured_results = {}

    async def capture_aggregate(msg, results):
        captured_results["results"] = results
        return "聚合"

    orchestrator._aggregate_results = AsyncMock(side_effect=capture_aggregate)

    await orchestrator._execute_multi_step("sess-1", "复杂任务", None)

    # 关键断言: 结果顺序是 A, B, C (不是 B, C, A — 虽然 B 最快完成)
    results = captured_results["results"]
    assert len(results) == 3
    assert results[0]["subtask"]["description"] == "A"
    assert results[1]["subtask"]["description"] == "B"
    assert results[2]["subtask"]["description"] == "C"


@pytest.mark.asyncio()
async def test_execute_multi_step_isolates_subtask_failures():
    """单个子任务失败不影响其他子任务 (错误隔离)。"""
    orchestrator = AgentOrchestrator()

    orchestrator._decompose_task = AsyncMock(
        return_value=[
            {"intent": "general", "description": "正常任务"},
            {"intent": "general", "description": "会失败的任务"},
            {"intent": "general", "description": "另一个正常任务"},
        ]
    )

    call_count = {"n": 0}

    async def flaky_execute(session_id, agent_id, message, history=None):
        call_count["n"] += 1
        if "失败" in message:
            raise RuntimeError("子任务内部爆炸")
        return {"agent_id": agent_id, "response": f"OK: {message}", "task_id": "t"}

    orchestrator._execute_agent_task = AsyncMock(side_effect=flaky_execute)

    captured_results = {}

    async def capture_aggregate(msg, results):
        captured_results["results"] = results
        return "聚合"

    orchestrator._aggregate_results = AsyncMock(side_effect=capture_aggregate)

    await orchestrator._execute_multi_step("sess-1", "混合任务", None)

    # 3 个子任务都被执行
    assert call_count["n"] == 3

    # 结果包含 3 个条目 (包括失败的那个)
    results = captured_results["results"]
    assert len(results) == 3

    # 失败的子任务结果应标记错误
    failed_result = results[1]
    assert "error" in failed_result["result"] or "爆炸" in failed_result["result"].get(
        "response", ""
    )

    # 正常的子任务结果不受影响
    assert "OK: 正常任务" in results[0]["result"]["response"]
    assert "OK: 另一个正常任务" in results[2]["result"]["response"]


@pytest.mark.asyncio()
async def test_execute_multi_step_single_subtask_still_works():
    """单子任务的多步骤任务也能正常工作 (边界情况)。"""
    orchestrator = AgentOrchestrator()

    orchestrator._decompose_task = AsyncMock(
        return_value=[{"intent": "general", "description": "唯一任务"}]
    )

    async def single_execute(session_id, agent_id, message, history=None):
        return {"agent_id": agent_id, "response": "唯一响应", "task_id": "t"}

    orchestrator._execute_agent_task = AsyncMock(side_effect=single_execute)
    orchestrator._aggregate_results = AsyncMock(return_value="聚合")

    await orchestrator._execute_multi_step("sess-1", "单任务", None)

    assert orchestrator._execute_agent_task.call_count == 1
    assert orchestrator._aggregate_results.called


@pytest.mark.asyncio()
async def test_execute_multi_step_empty_subtasks_returns_immediately():
    """空子任务列表应直接返回 (不挂起)。"""
    orchestrator = AgentOrchestrator()

    orchestrator._decompose_task = AsyncMock(return_value=[])
    orchestrator._aggregate_results = AsyncMock(return_value="空聚合")
    orchestrator._execute_agent_task = AsyncMock()  # 不应该被调用

    await orchestrator._execute_multi_step("sess-1", "无任务", None)

    assert orchestrator._execute_agent_task.call_count == 0
    assert orchestrator._aggregate_results.called
