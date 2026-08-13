"""ChatDispatcher — 轻量子 agent 执行器（Multi-Agent Orchestration 方案 C）。

conductor（主 LLM）经 ``dispatch_subagents`` 工具调用本 dispatcher，把
``[{agent_id, goal}]`` 并行派发给子 agent。Wave 1（P0-1/P0-3）起子任务经
``LaneExecutor`` 执行：每个子任务在 lane_registry 产生 lane 镜像，
``RecoveryPolicy(on_failure="retry", max_retries=2)`` 提供重试，重试次数
回填 task_status 事件的 ``retry_count`` 字段；子 agent 以
``ToolPolicy(workspace_root=<scratch_dir>)`` 构建，文件工具被锁进
``<data_dir>/orch_scratch/<run_id>/<task_id>`` 隔离目录。task_status 事件
仍推送 entry_queue，前端进度可视化字段保持兼容。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.data.database import get_database
from backend.orchestration.events import EventRecorder
from backend.orchestration.executor import LaneExecutor
from backend.orchestration.lane_registry import LaneRegistry
from backend.orchestration.models import Lane, RecoveryPolicy, Task, TaskPacket
from backend.orchestration.report_schema import Assertion, AssertionType
from backend.orchestration.subagent_runner import SubagentRunner, run_lane_with_retry
from backend.orchestration.task_registry import TaskRegistry

logger = logging.getLogger(__name__)

#: 并发上限 —— 子 agent 同时执行数（多出的排队等待）。
MAX_CONCURRENT_SUBAGENTS = 4

#: 单子结果截断上限 —— 聚合 markdown 进 conductor 上下文，防止灌爆。
MAX_SUBAGENT_RESULT_CHARS = 50 * 1024

#: 聚合 markdown 总上限（F3 2026-08-12）—— maxItems 放宽到 8 后，8 项最坏
#: 8×50KB=400KB，必须整体兜底，防止一次性灌爆 conductor 上下文。
MAX_AGGREGATE_CHARS = 120 * 1024

#: task_status.output_preview 上限（UI 展开预览）。
MAX_OUTPUT_PREVIEW_CHARS = 500

#: 编排语义判定 prompt（轻量二分类）：LLM 只需回答 multi / single。
_CLASSIFY_PROMPT = """判断以下用户消息是否需要多 agent 协作（拆解为多个子任务、由不同角色并行执行）才能最好地完成。
只需返回一个词：multi 或 single。
- multi：复杂任务、多步骤、需要搜集资料/研究/并行工作。例如"我需要学习量化交易，先搜集相关资料后，整理一份学习资料和操作指南"。
- single：简单问答、单步请求。例如"今天天气怎么样"、"解释什么是递归"。

用户消息: {message}

答案:"""

#: scratch 根目录名（data_dir 下）。
SCRATCH_ROOT = "orch_scratch"


async def _classify_orchestration_mode(
    message: str,
    orchestration_mode: str,
    llm_client: Optional[Any] = None,
) -> str:
    """语义判定消息是否进编排（multi）还是单 agent（single）。

    - ``force_multi`` / ``force_single``：用户 override，直接定，跳过 LLM
    - ``auto``：轻量 LLM 二分类；无 client / 失败 → ``single``（= 没开编排）

    这是 tool-toggle 门的判定源：mode=single 时 producer 不注册
    dispatch_subagents 工具（简单任务在结构上无法被过度拆解）。
    """
    if orchestration_mode == "force_multi":
        return "multi"
    if orchestration_mode == "force_single":
        return "single"
    if llm_client is None:
        return "single"
    try:
        # str.replace, NOT .format(): user message may contain literal { / }
        # (JSON / code snippets / template strings) which would make .format()
        # raise KeyError/IndexError and silently downgrade to single with a
        # misleading "判定失败" log.
        prompt = _CLASSIFY_PROMPT.replace("{message}", message)
        response = await llm_client.complete(prompt)
        return "multi" if "multi" in (response or "").strip().lower() else "single"
    except Exception as exc:  # noqa: BLE001 — 判定失败必须降级，绝不阻塞聊天
        logger.warning("编排语义判定失败，降级 single: %s", exc)
        return "single"


@dataclass
class ChatTaskState:
    """单个子任务的可变状态（dispatcher 内存态，不落库）。"""

    task_id: str
    agent_id: str
    goal: str
    status: str = "queued"  # queued|running|done|failed
    output: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    retry_count: int = 0


class ChatDispatcher:
    """并行执行子任务并向聊天流推送 task_status 事件的轻量调度器。"""

    def __init__(
        self,
        stream_id: str,
        entry_queue: asyncio.Queue[Dict[str, Any]],
        run_id: str,
        llm_config: Optional[Dict[str, Any]] = None,
        lane_registry: Optional[Any] = None,
        task_registry: Optional[Any] = None,
        event_recorder: Optional[EventRecorder] = None,
        total_tasks: Optional[int] = None,
    ) -> None:
        self.stream_id = stream_id
        self.entry_queue = entry_queue
        self.run_id = run_id
        self.llm_config = llm_config
        # P0-1：子任务经 LaneExecutor 执行（lane 镜像 + RecoveryPolicy 重试）。
        self.lane_registry = lane_registry or LaneRegistry()
        self.task_registry = task_registry or TaskRegistry()
        self.event_recorder = event_recorder or EventRecorder()
        # P0-2：总任务数门控 —— 达到 plan 总量后跑 reviewer 验证环（Task 5）。
        self.total_tasks = total_tasks
        self._states: Dict[str, ChatTaskState] = {}
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_SUBAGENTS)
        # F1 (2026-08-12): run 内全局递增的 task 计数器。修复前每次 dispatch
        # 调用都从 t1 重编号，与 producer 计划的全局编号 t1..tN 错位 —— 前端
        # 按 task_id 合并 status，计划 t4-t6 永远收不到更新（UI 恒显 3/6）。
        self._next_task_index = 0

    async def dispatch(self, tasks: List[Dict[str, str]]) -> str:
        """并行执行子任务，返回聚合 markdown（截断后进 conductor 上下文）。

        Args:
            tasks: ``[{"agent_id": ..., "goal": ...}]``。task_id 按 run 内
                全局递增分配（``t{run_sequence}``），跨多次 dispatch 调用唯一，
                与 producer 的 task_plan 编号 t1..tN 对齐。

        Returns:
            聚合 markdown：每个子结果截断 MAX_SUBAGENT_RESULT_CHARS 后拼接；
            单任务失败以错误摘要参与聚合，其余任务继续（错误隔离）。
        """
        states: List[ChatTaskState] = []
        for raw in tasks:
            # 缺 agent_id（malformed input）→ 失败事件占位，不抛穿整次 dispatch。
            # 让 conductor 看到 status=failed + error，能定位 producer bug。
            # F1 (2026-08-12): task_id 从 run 内全局计数器分配（跨调用唯一，
            # 与计划编号 t1..tN 对齐），不再按本次调用内 index 重编号。
            task_id = f"t{self._next_task_index + 1}"
            self._next_task_index += 1
            try:
                state = ChatTaskState(
                    task_id=task_id,
                    agent_id=raw["agent_id"],
                    goal=raw.get("goal", ""),
                )
            except KeyError as exc:
                state = ChatTaskState(
                    task_id=task_id,
                    agent_id="<missing>",
                    goal=raw.get("goal", ""),
                )
                self._states[state.task_id] = state
                states.append(state)
                self._emit_task_status(state)  # queued (status 仍是 "queued")
                state.status = "failed"
                state.error = f"missing required key: {exc.args[0]}"
                self._emit_task_status(state)  # failed
                continue
            self._states[state.task_id] = state
            states.append(state)
            self._emit_task_status(state)  # queued

        async def _run_one(state: ChatTaskState) -> None:
            async with self._semaphore:
                state.status = "running"
                state.started_at = time.time()
                self._emit_task_status(state)
                # 让其他子任务也有机会 emit running,保证 queued/running/done 三阶段序
                await asyncio.sleep(0)
                try:
                    content = await self._run_subagent(state)
                    state.status = "done"
                    state.output = content
                except Exception as exc:  # noqa: BLE001 — 单任务失败隔离
                    state.status = "failed"
                    state.error = str(exc)
                    logger.warning("subagent %s failed: %s", state.task_id, exc)
                finally:
                    state.finished_at = time.time()
                    self._emit_task_status(state)

        await asyncio.gather(*(_run_one(s) for s in states if s.status != "failed"))
        aggregated = self._aggregate(states)
        # P0-2 验证环：仅当本次调用已覆盖 plan 全部任务后跑 reviewer；
        # 失败降级跳过（绝不阻塞聊天）。
        if self.total_tasks and self._next_task_index >= self.total_tasks:
            try:
                review = await self._run_review(aggregated)
                aggregated = aggregated + review["block"]
            except Exception as exc:  # noqa: BLE001 — 复核失败降级
                logger.warning("编排复核失败，跳过验证: %s", exc)
        return aggregated

    async def _run_subagent(self, state: ChatTaskState) -> str:
        """经 LaneExecutor 执行子任务（P0-1）：创建 lane+task，复用重试策略。

        子 agent 以 ToolPolicy(workspace_root=<scratch_dir>) 构建（P0-3）——
        write_file 等文件工具被锁进隔离目录，越界写返回 path_outside_workspace。
        """
        task_id = f"task-{state.task_id}"
        lane_id = f"lane-{state.task_id}"
        scratch_dir = self._scratch_dir_for(state)
        scratch_dir.mkdir(parents=True, exist_ok=True)

        task = Task(
            task_id=task_id,
            name=f"Subtask {state.task_id}",
            description=state.goal,
            parameters={
                "goal": state.goal,
                "agent_id": state.agent_id,
                "scratch_dir": str(scratch_dir),
            },
            packet=TaskPacket(
                objective=state.goal,
                recovery_policy=RecoveryPolicy(on_failure="retry", max_retries=2),
            ),
        )
        self.task_registry.create_task(task)
        self.task_registry.mark_running(task_id)

        lane = Lane(
            lane_id=lane_id,
            task_id=task_id,
            agent_id=state.agent_id,
            metadata={"task_id": state.task_id},
        )
        self.lane_registry.create_lane(lane)

        executor = LaneExecutor(
            lane_registry=self.lane_registry,
            task_registry=self.task_registry,
            event_recorder=self.event_recorder,
            agent_runner=SubagentRunner(self.llm_config),
        )
        result = await run_lane_with_retry(executor, lane, state.agent_id)

        # 重试信息回填 state → task_status 事件携带
        state.retry_count = lane.metadata.get("retry_count", 0) if lane.metadata else 0
        if result.get("status") == "failed":
            raise RuntimeError(result.get("error", "subtask failed"))
        if result.get("status") != "succeeded":
            raise RuntimeError(f"subtask unexpected status: {result.get('status')}")
        return result["result"]["output"]

    def _scratch_dir_for(self, state: ChatTaskState) -> Path:
        """子任务隔离目录：``<data_dir>/orch_scratch/<run_id>/<task_id>``。"""
        data_dir = Path(get_database().db_path).parent
        return data_dir / SCRATCH_ROOT / self.run_id / state.task_id

    def _emit_task_status(self, state: ChatTaskState) -> None:
        """推 task_status 事件；队列满/关闭静默降级（进度尽力而为）。"""
        event: Dict[str, Any] = {
            "state": "task_status",
            "run_id": self.run_id,
            "task_id": state.task_id,
            "status": state.status,
            "agent_id": state.agent_id,
            "goal": state.goal,
            "error": state.error,
            "retry_count": state.retry_count,
            "output_preview": self._preview(state),
        }
        try:
            self.entry_queue.put_nowait(event)
        except Exception:  # noqa: BLE001
            logger.debug("task_status 推送失败（队列满/关闭），忽略")

    def _preview(self, state: ChatTaskState) -> Optional[str]:
        """done → output 前 500 字；failed → error 前 500 字。"""
        if state.status == "done" and state.output:
            return state.output[:MAX_OUTPUT_PREVIEW_CHARS]
        if state.status == "failed" and state.error:
            return state.error[:MAX_OUTPUT_PREVIEW_CHARS]
        return None

    def _aggregate(self, states: List[ChatTaskState]) -> str:
        """聚合 markdown：成功子结果 + 失败摘要，每项截断。

        P0-1（进度可视化）：首部追加「已收到 X/N 子任务结果」摘要，
        让 conductor 看到还没齐时不要急着汇总。所有子任务完成时
        header 退化为单行声明，不展示"仍在并行运行"等干扰信息。
        """
        total = len(states)
        done = sum(1 for s in states if s.status == "done")
        failed = sum(1 for s in states if s.status == "failed")
        in_flight = total - done - failed

        if in_flight > 0:
            header = (
                f"## 子任务进度摘要（部分完成）\n\n"
                f"- 已收到 {done}/{total} 子任务结果"
                + (f"（{failed} 失败）" if failed else "")
                + f",{in_flight} 个仍在并行运行。\n"
                f"- 提醒：在剩余 {in_flight} 个子任务未完成前，"
                f"本次回答只能基于当前结果。"
                f"请等待所有子任务完成后给出最终汇总。\n\n"
            )
        else:
            header = (
                f"## 子任务进度摘要（全部完成）\n\n"
                f"- 已收到 {done}/{total} 子任务结果"
                + (f"（{failed} 失败）" if failed else "")
                + "。\n\n"
            )

        blocks: List[str] = []
        for state in states:
            header_item = f"## 子任务 {state.task_id}（{state.agent_id}）"
            if state.status == "done" and state.output:
                body = state.output[:MAX_SUBAGENT_RESULT_CHARS]
                blocks.append(f"{header_item}\n\n{body}")
            elif state.status == "failed":
                err = (state.error or "未知错误")[:MAX_SUBAGENT_RESULT_CHARS]
                blocks.append(f"{header_item}\n\n[失败] {err}")
            else:
                blocks.append(f"{header_item}\n\n[状态: {state.status}]")
        result = header + "\n\n".join(blocks)
        # F3 (2026-08-12): maxItems 放宽到 8 后单批聚合体积翻倍，整体截断兜底
        # （保留头部进度摘要 + 前部子任务），防一次性灌爆 conductor 上下文。
        if len(result) > MAX_AGGREGATE_CHARS:
            result = (
                result[:MAX_AGGREGATE_CHARS]
                + "\n\n[聚合结果超过上限，已截断；详见各子任务输出]"
            )
        return result

    def _parse_assertions(self, raw: str) -> List[Assertion]:
        """解析 reviewer 输出的 assertion 行 → ``list[Assertion]``。

        容忍非严格格式：行前缀 ``[FACT|HYPOTHESIS|NEGATIVE_EVIDENCE]``，可选
        ``(confidence: 0-1)`` 后缀。无法解析 / 未知 kind / 空 statement 的行
        跳过；confidence 解析失败归 0.0 并夹紧到 [0.0, 1.0]（绝不 raise）。
        返回 ``Assertion`` 对象 —— ``LaneExecutor.submit_with_report`` 直接把它
        们交给 ``ReviewReport``，dict 会因缺少 ``to_dict()`` 崩溃。
        """
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
                continue  # 未知 kind → 跳过
            try:
                confidence = float(m.group(3)) if m.group(3) else 0.0
            except ValueError:
                confidence = 0.0
            confidence = max(0.0, min(1.0, confidence))
            try:
                assertions.append(
                    Assertion(type=atype, statement=m.group(2), confidence=confidence)
                )
            except ValueError:
                continue  # 空 statement 等 → 跳过
        return assertions

    def _review_block(self, verdict: str, count: int) -> str:
        """复核结论 markdown（追加进聚合，进入 conductor 上下文）。"""
        if verdict == "fail":
            instruction = "存在关键 NEGATIVE_EVIDENCE，请修复后再给出最终汇总。"
        else:
            instruction = "全部断言通过，可给出最终汇总。"
        return (
            "\n\n## 复核结果（reviewer）\n\n"
            f"- verdict: {verdict}（{count} 条 assertion）\n"
            f"- {instruction}"
        )

    async def _run_review(self, aggregated: str) -> dict:
        """P0-2 验证环：reviewer 子 agent 复核聚合 → ReviewReport + markdown 块。

        reviewer 失败（raise）由 dispatch 捕获 → 跳过验证（降级不阻塞）。
        review task 不带 packet → executor ``_get_recovery_policy`` 给出
        ``{on_failure: "fail", max_retries: 0}``（reviewer 不重试）。
        """
        review_goal = (
            "复核以下多 agent 子任务聚合结果，逐条给出 assertion。\n"
            + aggregated[:MAX_SUBAGENT_RESULT_CHARS]
        )
        lane_id = f"lane-review-{self.run_id}"
        task_id = f"task-review-{self.run_id}"

        task = Task(
            task_id=task_id,
            name=f"Review {self.run_id}",
            description=review_goal,
            parameters={"goal": review_goal},
        )
        self.task_registry.create_task(task)
        # 置 RUNNING：executor 成功路径 mark_completed / 失败路径 mark_failed
        # 都要求 RUNNING 态（否则 review task 停在 CREATED，状态机不一致）。
        self.task_registry.mark_running(task_id)
        lane = Lane(lane_id=lane_id, task_id=task_id, agent_id="reviewer", metadata={})
        self.lane_registry.create_lane(lane)

        executor = LaneExecutor(
            lane_registry=self.lane_registry,
            task_registry=self.task_registry,
            event_recorder=self.event_recorder,
            agent_runner=SubagentRunner(self.llm_config),
        )
        result = await run_lane_with_retry(executor, lane, "reviewer")
        if result.get("status") != "succeeded":
            raise RuntimeError(result.get("error", "reviewer 未产出内容"))
        raw = result["result"]["output"]

        assertions = self._parse_assertions(raw)
        executor.submit_with_report(lane_id, task_id, assertions, reviewer_id="reviewer")
        verdict = (
            "fail"
            if any(
                a.type == AssertionType.NEGATIVE_EVIDENCE and a.confidence >= 0.7
                for a in assertions
            )
            else "pass"
        )
        block = self._review_block(verdict, len(assertions))
        logger.info("编排复核完成: verdict=%s, assertions=%d", verdict, len(assertions))
        return {"verdict": verdict, "block": block}
