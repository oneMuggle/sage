"""
AgentOrchestrator 多步调度与拆解/聚合测试 (PG1.2)

覆盖 `core/orchestrator.py` 的"scheduling"子集(实际是 multi-step orchestration):
  - _decompose_task: LLM 拆解成功、LLM 失败 fallback、JSON 解析异常
  - _execute_multi_step: 多个子任务分发 + 聚合
  - _aggregate_results: LLM 聚合、LLM 失败 fallback 拼接

外部依赖同 dispatch 测试:
  - LLMClient.chat() 用 MagicMock+AsyncMock 模拟
  - BlackboardRepo 走真实 SQLite
  - get_agent() 走真实 agents.profiles
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.llm_client import LLMResponse
from backend.core.orchestrator import AgentOrchestrator

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_response(content: str = "") -> LLMResponse:
    return LLMResponse(content=content, tool_calls=[])


def _orch_with_llm(llm_mock: MagicMock) -> AgentOrchestrator:
    orch = AgentOrchestrator()
    orch.llm_client = llm_mock
    return orch


# ---------------------------------------------------------------------------
# Task 1.2.2.8 — _decompose_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_decompose_task_with_llm_returns_parsed_subtasks():
    """有 LLM 时,成功解析 JSON 数组返回子任务列表。"""
    llm = MagicMock()
    llm.chat = AsyncMock(
        return_value=_make_response(
            content='[{"intent": "research", "description": "search X"}, '
            '{"intent": "coding", "description": "code Y"}]'
        )
    )
    orch = _orch_with_llm(llm)

    subtasks = await orch._decompose_task("research X and code Y")

    assert len(subtasks) == 2
    assert subtasks[0]["intent"] == "research"
    assert subtasks[0]["description"] == "search X"
    assert subtasks[1]["intent"] == "coding"
    assert llm.chat.await_count == 1


@pytest.mark.asyncio()
async def test_decompose_task_fallback_to_single_general_when_llm_fails():
    """LLM 抛异常 → fallback 到 [{"intent": "general", "description": message}]。"""
    llm = MagicMock()
    llm.chat = AsyncMock(side_effect=RuntimeError("parse boom"))
    orch = _orch_with_llm(llm)

    subtasks = await orch._decompose_task("complex task")

    assert subtasks == [{"intent": "general", "description": "complex task"}]


@pytest.mark.asyncio()
async def test_decompose_task_fallback_when_invalid_json():
    """LLM 返回非 JSON → JSON 解析异常 → fallback。"""
    llm = MagicMock()
    llm.chat = AsyncMock(return_value=_make_response(content="not valid json at all"))
    orch = _orch_with_llm(llm)

    subtasks = await orch._decompose_task("task")

    assert subtasks == [{"intent": "general", "description": "task"}]


@pytest.mark.asyncio()
async def test_decompose_task_fallback_when_llm_returns_empty_list():
    """LLM 返回空列表 → 走 fallback(因为 len(subtasks) > 0 失败)。"""
    llm = MagicMock()
    llm.chat = AsyncMock(return_value=_make_response(content="[]"))
    orch = _orch_with_llm(llm)

    subtasks = await orch._decompose_task("task")

    assert subtasks == [{"intent": "general", "description": "task"}]


@pytest.mark.asyncio()
async def test_decompose_task_fallback_when_llm_returns_non_list():
    """LLM 返回非 list 类型 → fallback。"""
    llm = MagicMock()
    llm.chat = AsyncMock(return_value=_make_response(content='{"intent": "research"}'))
    orch = _orch_with_llm(llm)

    subtasks = await orch._decompose_task("task")

    assert subtasks == [{"intent": "general", "description": "task"}]


@pytest.mark.asyncio()
async def test_decompose_task_without_llm_returns_single_general():
    """无 llm_client → 直接 fallback 到单子任务。"""
    orch = AgentOrchestrator()
    subtasks = await orch._decompose_task("complex multi step task")
    assert subtasks == [{"intent": "general", "description": "complex multi step task"}]


# ---------------------------------------------------------------------------
# Task 1.2.2.9 — _aggregate_results
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_aggregate_results_with_llm_returns_llm_content():
    """有 LLM 时,聚合 prompt 调 LLM 返回整合结果。"""
    llm = MagicMock()
    llm.chat = AsyncMock(return_value=_make_response(content="合并后的答案"))
    orch = _orch_with_llm(llm)

    results = [
        {
            "subtask": {"description": "step1", "intent": "research"},
            "result": {"response": "find A"},
        },
        {
            "subtask": {"description": "step2", "intent": "coding"},
            "result": {"response": "write B"},
        },
    ]

    final = await orch._aggregate_results("原问题", results)

    assert final == "合并后的答案"
    assert llm.chat.await_count == 1
    # 验证 prompt 中包含原问题和两个子任务结果
    call_args = llm.chat.await_args
    messages = call_args.args[0]
    user_prompt = messages[-1]["content"]
    assert "原问题" in user_prompt
    assert "find A" in user_prompt
    assert "write B" in user_prompt


@pytest.mark.asyncio()
async def test_aggregate_results_llm_failure_falls_back_to_concat():
    """LLM 抛异常 → fallback 拼接各子任务结果。"""
    llm = MagicMock()
    llm.chat = AsyncMock(side_effect=RuntimeError("agg boom"))
    orch = _orch_with_llm(llm)

    results = [
        {
            "subtask": {"description": "step1", "intent": "research"},
            "result": {"response": "find A"},
        },
        {
            "subtask": {"description": "step2", "intent": "coding"},
            "result": {"response": "write B"},
        },
    ]

    final = await orch._aggregate_results("原问题", results)

    assert "【子任务 1】" in final
    assert "find A" in final
    assert "【子任务 2】" in final
    assert "write B" in final


@pytest.mark.asyncio()
async def test_aggregate_results_without_llm_concatenates():
    """无 llm_client → 直接拼接(走 fallback 路径)。"""
    orch = AgentOrchestrator()
    results = [
        {"subtask": {"description": "s"}, "result": {"response": "r1"}},
    ]
    final = await orch._aggregate_results("q", results)
    assert "r1" in final
    assert "【子任务 1】" in final


@pytest.mark.asyncio()
async def test_aggregate_results_handles_missing_subtask_description():
    """子任务缺 description 字段时,聚合不应崩。"""
    llm = MagicMock()
    llm.chat = AsyncMock(return_value=_make_response(content="ok"))
    orch = _orch_with_llm(llm)
    results = [
        {"subtask": {"intent": "general"}, "result": {"response": "r1"}},
    ]
    final = await orch._aggregate_results("q", results)
    assert final == "ok"


# ---------------------------------------------------------------------------
# Task 1.2.2.10 — _execute_multi_step 端到端
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_execute_multi_step_dispatches_each_subtask_and_aggregates():
    """多步端到端:decompose → 多个 _execute_agent_task → aggregate。"""
    llm = MagicMock()
    # 1) decompose 返回 2 个子任务
    # 2-3) 每个子任务调 _run_agent_llm
    # 4) aggregate 调 LLM
    llm.chat = AsyncMock(
        side_effect=[
            _make_response(
                content='[{"intent": "research", "description": "search A"}, '
                '{"intent": "coding", "description": "code B"}]'
            ),
            _make_response(content="A-result"),
            _make_response(content="B-result"),
            _make_response(content="merged final"),
        ]
    )
    orch = _orch_with_llm(llm)

    result = await orch._execute_multi_step("sess-MS1", "do A and B", history=None)

    assert result["agent_id"] == "multi_step"
    assert result["response"] == "merged final"
    assert len(result["subtasks"]) == 2
    # 第一个子任务 → researcher
    assert result["subtasks"][0]["result"]["agent_id"] == "researcher"
    # 第二个子任务 → coder
    assert result["subtasks"][1]["result"]["agent_id"] == "coder"
    # 黑板应记录所有 task + result
    # task 用 target_agent=agent_id 发布 → 按 agent_id 订阅
    researcher_tasks = orch.blackboard.subscribe(
        agent_name="researcher", session_id="sess-MS1", message_type="task", limit=5
    )
    coder_tasks = orch.blackboard.subscribe(
        agent_name="coder", session_id="sess-MS1", message_type="task", limit=5
    )
    assert len(researcher_tasks) == 1
    assert len(coder_tasks) == 1
    # result 用 target_agent=orchestrator 发布 → 订阅 orchestrator
    orch_results = orch.blackboard.subscribe(
        agent_name="orchestrator", session_id="sess-MS1", message_type="result", limit=10
    )
    assert len(orch_results) == 2


@pytest.mark.asyncio()
async def test_execute_multi_step_without_llm_uses_single_general_subtask():
    """无 llm_client:decompose 退化到单子任务 general,aggregate 直接拼接。"""
    orch = AgentOrchestrator()
    result = await orch._execute_multi_step("sess-MS2", "multi-step query")
    assert result["agent_id"] == "multi_step"
    assert len(result["subtasks"]) == 1
    # 子任务 agent 是 primary(GENERAL)
    assert result["subtasks"][0]["result"]["agent_id"] == "primary"
    # 聚合拼接包含子任务响应
    assert "【子任务 1】" in result["response"]


@pytest.mark.asyncio()
async def test_execute_multi_step_decompose_failure_proceeds_with_general():
    """decompose 失败时,仍能跑通:用单 general 子任务走完。"""
    llm = MagicMock()
    # decompose 失败 → 走 fallback → 单子任务
    # _run_agent_llm 一次
    # aggregate 一次
    llm.chat = AsyncMock(
        side_effect=[
            RuntimeError("decompose boom"),  # decompose
            _make_response(content="subtask reply"),  # _run_agent_llm
            _make_response(content="aggregated"),  # aggregate
        ]
    )
    orch = _orch_with_llm(llm)

    result = await orch._execute_multi_step("sess-MS3", "complex task")

    assert result["agent_id"] == "multi_step"
    assert len(result["subtasks"]) == 1
    # 仍能拿到 final response
    assert "response" in result


@pytest.mark.asyncio()
async def test_execute_multi_step_subtask_routes_by_intent():
    """子任务的 intent 字段决定派发到哪个 agent。"""
    llm = MagicMock()
    llm.chat = AsyncMock(
        side_effect=[
            _make_response(
                content='[{"intent": "memory", "description": "remember X"}, '
                '{"intent": "general", "description": "reply Y"}]'
            ),
            _make_response(content="M"),
            _make_response(content="G"),
            _make_response(content="done"),
        ]
    )
    orch = _orch_with_llm(llm)

    result = await orch._execute_multi_step("sess-MS4", "remember and reply")

    assert result["subtasks"][0]["result"]["agent_id"] == "memory_manager"
    assert result["subtasks"][1]["result"]["agent_id"] == "primary"
