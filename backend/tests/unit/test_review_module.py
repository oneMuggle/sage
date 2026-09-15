"""Wave 3 B1 — run_review 模块化：验证环逻辑与 ChatDispatcher 解耦。"""
from unittest.mock import MagicMock

import pytest

from backend.orchestration.review import parse_assertions, run_review


def test_parse_assertions_module_function():
    """parse_assertions 从 dispatcher 搬出，行为不变。"""
    raw = "[FACT] 事实一 (confidence: 0.9)\n[GARBAGE] 无效行\n[NEGATIVE_EVIDENCE] 反例 (confidence: 0.8)"
    assertions = parse_assertions(raw)
    assert len(assertions) == 2
    assert assertions[0].type.value == "fact"
    assert assertions[1].confidence == 0.8


@pytest.mark.asyncio()
async def test_run_review_success_path():
    """reviewer 成功 → verdict/block/assertion_count；emit 回调被调。"""
    emitted = []

    async def fake_run_lane(executor, lane, agent_id):
        return {"status": "succeeded", "result": {"output": "[FACT] 复核通过 (confidence: 0.9)"}}

    import backend.orchestration.review as review_mod

    orig = review_mod.run_lane_with_retry
    review_mod.run_lane_with_retry = fake_run_lane
    try:
        outcome = await run_review(
            run_id="r1",
            aggregated="聚合内容",
            task_registry=MagicMock(),
            lane_registry=MagicMock(),
            event_recorder=MagicMock(),
            llm_config={"model": "x"},
            emit_review=lambda *a: emitted.append(a),
        )
    finally:
        review_mod.run_lane_with_retry = orig
    assert outcome["verdict"] == "pass"
    assert outcome["assertion_count"] == 1
    assert "复核结果" in outcome["block"]
    assert emitted  # emit_review 被调用
