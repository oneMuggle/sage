"""``review`` — P0-2 验证环（Wave 3 B1 提取）。

ChatDispatcher._run_review 与 API lane（B2）共用：对聚合结果跑 reviewer
子 agent，产出 ReviewReport + verdict/assertion_count/block。不改变
ChatDispatcher 原有行为（reviewer 失败 → 由调用方捕获降级）。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional

from backend.orchestration.executor import LaneExecutor
from backend.orchestration.models import Lane, Task
from backend.orchestration.report_schema import Assertion, AssertionType
from backend.orchestration.subagent_runner import SubagentRunner, run_lane_with_retry

logger = logging.getLogger(__name__)


def parse_assertions(raw: str) -> List[Assertion]:
    """解析 reviewer 输出的 assertion 行 → ``list[Assertion]``（见原 dispatcher 文档）。"""
    pattern = re.compile(
        r"^\[(FACT|HYPOTHESIS|NEGATIVE_EVIDENCE)\]\s*(.+?)"
        r"(?:\s*\(confidence:\s*([0-9.]+)\))?\s*$"
    )
    assertions: List[Assertion] = []
    for line in raw.splitlines():
        m = pattern.match(line.strip())
        if not m:
            continue
        try:
            atype = AssertionType(m.group(1).lower())
        except ValueError:
            continue
        try:
            confidence = float(m.group(3)) if m.group(3) else 0.0
        except ValueError:
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        try:
            assertions.append(Assertion(type=atype, statement=m.group(2), confidence=confidence))
        except ValueError:
            continue
    return assertions


def build_review_block(verdict: str, count: int, note: str = "") -> str:
    note_line = f"- 备注：{note}\n" if note else ""
    instruction = (
        "存在关键 NEGATIVE_EVIDENCE 或无可解析 assertion，请修复后再给出最终汇总。"
        if verdict == "fail"
        else "全部断言通过，可给出最终汇总。"
    )
    return (
        "\n\n## 复核结果（reviewer）\n\n"
        f"- verdict: {verdict}（{count} 条 assertion）\n{note_line}"
        f"- {instruction}"
    )


async def run_review(
    *,
    run_id: str,
    aggregated: str,
    task_registry: Any,
    lane_registry: Any,
    event_recorder: Any,
    llm_config: Any,
    max_chars: int = 50 * 1024,
    emit_review: Optional[Callable[[str, str, int, str], None]] = None,
) -> Dict[str, Any]:
    """reviewer 复核聚合 → ReviewReport + markdown 块（ChatDispatcher/API lane 共用）。"""
    review_goal = (
        "复核以下多 agent 子任务聚合结果，逐条给出 assertion。\n"
        + aggregated[:max_chars]
    )
    lane_id = f"lane-review-{run_id}"
    task_id = f"task-review-{run_id}"

    task = Task(
        task_id=task_id,
        name=f"Review {run_id}",
        description=review_goal,
        parameters={"goal": review_goal},
    )
    task_registry.create_task(task)
    task_registry.mark_running(task_id)
    lane = Lane(lane_id=lane_id, task_id=task_id, agent_id="reviewer", metadata={})
    lane_registry.create_lane(lane)

    executor = LaneExecutor(
        lane_registry=lane_registry,
        task_registry=task_registry,
        event_recorder=event_recorder,
        agent_runner=SubagentRunner(llm_config),
    )
    result = await run_lane_with_retry(executor, lane, "reviewer")
    if result.get("status") != "succeeded":
        raise RuntimeError(result.get("error", "reviewer 未产出内容"))
    raw = result["result"]["output"]

    assertions = parse_assertions(raw)
    executor.submit_with_report(lane_id, task_id, assertions, reviewer_id="reviewer")
    if len(assertions) == 0:
        verdict = "fail"
        review_note = "reviewer 未产出任何可解析 assertion"
    else:
        verdict = (
            "fail"
            if any(
                a.type == AssertionType.NEGATIVE_EVIDENCE and a.confidence >= 0.7
                for a in assertions
            )
            else "pass"
        )
        review_note = ""
    block = build_review_block(verdict, len(assertions), note=review_note)
    if emit_review is not None:
        emit_review(
            task_id,
            verdict,
            len(assertions),
            review_note or f"{verdict}（{len(assertions)} 条 assertion）",
        )
    logger.info("编排复核完成: verdict=%s, assertions=%d", verdict, len(assertions))
    return {"verdict": verdict, "block": block, "assertion_count": len(assertions)}
