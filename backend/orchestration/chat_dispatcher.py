"""ChatDispatcher — 轻量子 agent 执行器（Multi-Agent Orchestration 方案 C）。

conductor（主 LLM）经 ``dispatch_subagents`` 工具调用本 dispatcher，把
``[{task_id, agent_id, goal}]`` 并行派发给子 agent。Wave 1（P0-1/P0-3）起子任务经
``LaneExecutor`` 执行：每个子任务在 lane_registry 产生 lane 镜像，
``RecoveryPolicy(on_failure="retry", max_retries=2)`` 提供重试，重试次数
回填 task_status 事件的 ``retry_count`` 字段；子 agent 以
``ToolPolicy(workspace_root=<scratch_dir>)`` 构建，文件工具被锁进
``<data_dir>/orch_scratch/<run_id>/<task_id>`` 隔离目录。task_status 事件
仍推送 entry_queue，前端进度可视化字段保持兼容。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from backend.data.database import get_database
from backend.orchestration.events import EventRecorder
from backend.orchestration.executor import LaneExecutor
from backend.orchestration.lane_registry import LaneRegistry
from backend.orchestration.models import Lane, RecoveryPolicy, Task, TaskPacket
from backend.orchestration.orch_settings import OrchSettings, load_orch_settings
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

#: Wave 2 Minor 2 fix (2026-08-14): 防御性 retry 循环上限 —— 防未来 executor
#: 退化（一直返回 retrying）导致 _run_subagent 无限循环 hang。
MAX_LANE_ITERATIONS = 8

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
    - ``template:<id>``：模板即强制编排 → ``multi``（跳过 LLM；模板不存在
      时降级 single 由 decompose 层负责，这里不校验存在性）
    - ``auto``：轻量 LLM 二分类；无 client / 失败 → ``single``（= 没开编排）

    这是 tool-toggle 门的判定源：mode=single 时 producer 不注册
    dispatch_subagents 工具（简单任务在结构上无法被过度拆解）。
    """
    # P2-8 (2026-08-14): template:<id> 即强制编排 —— 跳过 LLM 二分类。
    # 模板存在性在 decompose_from_template 校验（不存在 → 降级 single）。
    if orchestration_mode.startswith("template:"):
        return "multi"
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


# P2-9 (2026-08-14): 进程内活动 dispatcher 注册表 —— 供 run 级 cancel 端点
# 定位并置位取消事件。producer 在构造后注册、finally 注销（长连接结束即删）。
_ACTIVE_DISPATCHERS: Dict[str, ChatDispatcher] = {}


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
        settings: Optional[OrchSettings] = None,
    ) -> None:
        self.stream_id = stream_id
        self.entry_queue = entry_queue
        self.run_id = run_id
        self.llm_config = llm_config
        # P2-9 (2026-08-14): 执行参数配置化 —— 模块常量改实例引用。
        # 不传 → load_orch_settings() 从持久化 app_settings 回落默认。
        self.settings = settings or load_orch_settings()
        # P0-1：子任务经 LaneExecutor 执行（lane 镜像 + RecoveryPolicy 重试）。
        self.lane_registry = lane_registry or LaneRegistry()
        self.task_registry = task_registry or TaskRegistry()
        self.event_recorder = event_recorder or EventRecorder()
        # P0-2：总任务数门控 —— 达到 plan 总量后跑 reviewer 验证环（Task 5）。
        self.total_tasks = total_tasks
        self._states: Dict[str, ChatTaskState] = {}
        self._semaphore = asyncio.Semaphore(self.settings.max_concurrent_subagents)
        # F1 (2026-08-12): run 内全局递增的 task 计数器。修复前每次 dispatch
        # 调用都从 t1 重编号，与 producer 计划的全局编号 t1..tN 错位 —— 前端
        # 按 task_id 合并 status，计划 t4-t6 永远收不到更新（UI 恒显 3/6）。
        self._next_task_index = 0
        # Wave 2 P1-4: repo 复用 LaneRepository 模式（self.db = get_database()）。
        # 构造不接 db_path —— 测试经 SAGE_DB_PATH env + 重置 _db 单例切 tmp DB。
        from backend.data.orch_run_repo import OrchRunRepository
        from backend.data.orch_task_repo import OrchTaskRepository

        self._orch_run_repo = OrchRunRepository()
        self._orch_task_repo = OrchTaskRepository()
        # Wave 2 P1-4 (2026-08-14): review 一次性守卫 —— 防重复 review 触发
        # IntegrityError（同一 run 二次 review 会撞唯一约束）；_first_dispatch_at
        # 记录首次 dispatch 时间（resume 场景前端展示用）。
        self._reviewed: bool = False
        self._first_dispatch_at: Optional[float] = None
        # P2-7 (2026-08-14): 计划权威 —— 首 dispatch 从 orch_runs.plan_json 读权威
        # 计划建索引；_dispatched_plan_ids 记录已派发的计划 task_id（review 门用）。
        self._plan_by_id: Dict[str, dict] = {}
        self._plan_loaded = False
        self._dispatched_plan_ids: Set[str] = set()
        # P2-9 (2026-08-14): 取消事件 —— cancel() 幂等 set；_run_one 开头检查。
        self._cancelled = asyncio.Event()

    def cancel(self) -> bool:
        """置位取消事件。幂等：已 set 返回 False，否则 True。"""
        if self._cancelled.is_set():
            return False
        self._cancelled.set()
        return True

    def _ensure_plan_loaded(self) -> None:
        """首 dispatch 时从 orch_runs.plan_json 读权威计划建索引（DB 单源）。

        计划卡 update_plan 在派发前落库 → 首派发即读到编辑后计划。读库失败/空 →
        _plan_by_id 保持空，后续走未知/缺省路由（不强制闭环）。只建一次。
        """
        if self._plan_loaded:
            return
        self._plan_loaded = True
        try:
            run = self._orch_run_repo.get(self.run_id)
            if run and run.plan_json:
                raw = json.loads(run.plan_json)
                tasks = raw.get("tasks", []) if isinstance(raw, dict) else []
                self._plan_by_id = {
                    t["task_id"]: t
                    for t in tasks
                    if isinstance(t, dict) and t.get("task_id")
                }
        except Exception as exc:  # noqa: BLE001 — 读库失败降级，不阻塞派发
            logger.warning("计划权威索引构建失败 run=%s err=%s", self.run_id, exc)

    async def dispatch(self, tasks: List[Dict[str, str]]) -> str:
        """并行执行子任务，返回聚合 markdown（截断后进 conductor 上下文）。

        P2-7 (2026-08-14): 三态路由 —— task_id 匹配计划 → goal/agent 以计划
        为准（计划权威，DB 单源）；未知 task_id → 回退 tool-passed 值（允许
        conductor 动态加任务）；缺 task_id → 自分配（计数器仅作缺省，跳过计划
        已占编号）。匹配计划的 task_id 与 producer 的 task_plan 编号 t1..tN 对齐。

        Args:
            tasks: ``[{"task_id": ..., "agent_id": ..., "goal": ...}]``。

        Returns:
            聚合 markdown：每个子结果截断 MAX_SUBAGENT_RESULT_CHARS 后拼接；
            单任务失败以错误摘要参与聚合，其余任务继续（错误隔离）。
        """
        # Wave 2 P1-4: 首次 dispatch 时间戳（放函数开头，resume 场景多轮
        # dispatch 只记第一次）。P1-5: 同步落库 dispatched_at —— update_plan
        # 据此返回 409（编辑生效窗口 = 首次派发前）。落库失败降级不阻塞。
        if self._first_dispatch_at is None:
            self._first_dispatch_at = time.time()
            self._mark_run_dispatched(int(self._first_dispatch_at * 1000))
        # P2-7: 首 dispatch 从 orch_runs.plan_json 读权威计划建索引（只建一次）。
        self._ensure_plan_loaded()
        states: List[ChatTaskState] = []
        for raw in tasks:
            raw_task_id = raw.get("task_id")
            if raw_task_id and raw_task_id in self._plan_by_id:
                # P2-7 计划权威：goal/agent 以计划为准（覆盖 tool-passed；计划卡
                # 编辑在派发前生效的杠杆点）。depends_on 直接随 plan_json 透传（A4 不用）。
                plan_item = self._plan_by_id[raw_task_id]
                task_id = raw_task_id
                agent_id = str(plan_item.get("agent_id", raw.get("agent_id", "primary")))
                goal = str(plan_item.get("goal", raw.get("goal", "")))
                self._dispatched_plan_ids.add(task_id)
            elif raw_task_id:
                # 未知 task_id（不在计划）→ 回退 tool-passed 值，允许 conductor 动态加任务。
                task_id = raw_task_id
                agent_id = str(raw.get("agent_id", "primary"))
                goal = str(raw.get("goal", ""))
            else:
                # 缺 task_id（malformed/旧客户端）→ 自分配（保留 _next_task_index 作缺省计数器）。
                # 跳过循环：候选号撞计划编号或已用状态则递增（计划权威下 t1..tN 已占用）。
                task_id = f"t{self._next_task_index + 1}"
                while task_id in self._plan_by_id or task_id in self._states:
                    self._next_task_index += 1
                    task_id = f"t{self._next_task_index + 1}"
                self._next_task_index += 1
                agent_id = str(raw.get("agent_id", "primary"))
                goal = str(raw.get("goal", ""))
            state = ChatTaskState(task_id=task_id, agent_id=agent_id, goal=goal)
            self._states[state.task_id] = state
            states.append(state)
            self._emit_task_status(state)  # queued

        async def _run_one(state: ChatTaskState) -> None:
            async with self._semaphore:
                # P2-9 (2026-08-14): 取消后 queued 任务不再启动（转 cancelled）。守卫在
                # acquire 之后 —— 排队等槽的任务 cancel 前已越过入口，拿到槽后再判一次
                # 才真正短路；running 子任务已过守卫不硬杀（SubagentRunner 无中断通道），
                # 尽力放行，已完成结果仍入聚合。
                if self._cancelled.is_set():
                    state.status = "cancelled"
                    state.error = "cancelled by user"
                    self._emit_task_status(state)
                    return
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

        await asyncio.gather(
            *(_run_one(s) for s in states if s.status not in ("failed", "cancelled"))
        )
        aggregated = self._aggregate(states)
        # P0-2 验证环：仅当本次调用已覆盖 plan 全部任务后跑 reviewer；
        # 失败降级跳过（绝不阻塞聊天）。
        # Wave 2 P1-4: 加 _reviewed 一次性守卫 —— 同一 run 只 review 一次，
        # 二次触发会撞 review 落库唯一约束（IntegrityError）；review 抛异常则
        # 复位 _reviewed，下次 dispatch 可重试。
        # P2-9/A8 fix round 1 (2026-08-14): 取消后不再拉 reviewer —— 单批全量
        # dispatch 中 cancel 时 plan_covered 已满足，跳过验证环避免浪费 token /
        # 落 review / 给已取消 run 推 task_review 事件。
        if self.total_tasks and not self._reviewed and not self._cancelled.is_set():
            if self._plan_by_id:
                # 计划权威下：计划全部 task_id 已派发 → 触发验证环
                plan_covered = set(self._plan_by_id).issubset(self._dispatched_plan_ids)
            else:
                # 无计划（DB 空/读失败）→ 回退旧门（计数器覆盖 total）
                plan_covered = self._next_task_index >= self.total_tasks
            if plan_covered:
                self._reviewed = True
                try:
                    review = await self._run_review(aggregated)
                    aggregated = aggregated + review["block"]
                except Exception as exc:  # noqa: BLE001 — 复核失败降级
                    self._reviewed = False
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
                recovery_policy=RecoveryPolicy(
                    on_failure="retry", max_retries=self.settings.max_retries
                ),
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
        # Wave 2 Minor 2 fix: 防御性 max-iteration guard。run_lane_with_retry
        # 理论上内循环会收敛（max_retries 耗尽 → failed 终态），但防未来
        # executor 退化一直返回 retrying 导致 hang，调用层设硬上限。
        iterations = 0
        while result.get("status") == "retrying":
            iterations += 1
            if iterations >= self.settings.max_lane_iterations:
                raise RuntimeError(
                    f"MAX_ITERATIONS_EXCEEDED: retry loop exceeded "
                    f"max_iterations={self.settings.max_lane_iterations}"
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
        return data_dir / self.settings.scratch_root / self.run_id / state.task_id

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
        # Wave 2 P1-4: 状态迁移同步写库。失败在 _persist_task_state 内部降级，
        # 绝不阻塞聊天进度推送。
        self._persist_task_state(state)

    def init_orch_run(self, session_id: str, plan_json: str) -> None:
        """由 caller (legacy_routes) 在第一次 dispatch 前调一次。失败降级。"""
        try:
            from backend.data.orch_run_repo import OrchRun

            self._orch_run_repo.upsert(OrchRun(
                run_id=self.run_id,
                session_id=session_id or "",
                status="running",
                created_at=int(time.time() * 1000),
                plan_json=plan_json,
            ))
        except Exception as exc:  # noqa: BLE001 — 降级铁律
            logger.warning("orch_run 落库失败 run_id=%s err=%s", self.run_id, exc)

    def _mark_run_dispatched(self, dispatched_at: int) -> None:
        """首次派发落库 dispatched_at（幂等）。run 行不存在则跳过,失败降级。"""
        try:
            self._orch_run_repo.mark_dispatched(self.run_id, dispatched_at)
        except Exception as exc:  # noqa: BLE001 — 降级铁律
            logger.warning(
                "orch_run 派发标记失败 run_id=%s err=%s", self.run_id, exc
            )

    def _persist_task_state(self, state: ChatTaskState) -> None:
        """状态迁移同步写库；写失败降级（logger.warning，绝不阻塞聊天）。"""
        try:
            self._orch_task_repo.upsert_state(
                task_id=state.task_id,
                run_id=self.run_id,
                agent_id=state.agent_id,
                goal=state.goal,
                status=state.status,
                retry_count=state.retry_count,
                error=state.error,
                output_preview=self._preview(state),
                started_at=int(state.started_at * 1000) if state.started_at else None,
                finished_at=int(state.finished_at * 1000) if state.finished_at else None,
            )
        except Exception as exc:  # noqa: BLE001 — 降级铁律
            logger.warning("orch_task 落库失败 task_id=%s err=%s", state.task_id, exc)

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
        P2-9/A8 fix round 1 (2026-08-14)：cancelled 从 in_flight 扣除，
        聚合头单列「已取消」—— 取消的任务不再显示为"仍在并行运行"，
        避免误导 conductor 继续等待/重复 dispatch。
        """
        total = len(states)
        done = sum(1 for s in states if s.status == "done")
        failed = sum(1 for s in states if s.status == "failed")
        cancelled = sum(1 for s in states if s.status == "cancelled")
        in_flight = total - done - failed - cancelled

        if in_flight > 0:
            header = (
                f"## 子任务进度摘要（部分完成）\n\n"
                f"- 已收到 {done}/{total} 子任务结果"
                + (f"（{failed} 失败）" if failed else "")
                + (f"（{cancelled} 已取消）" if cancelled else "")
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
                + (f"（{cancelled} 已取消）" if cancelled else "")
                + "。\n\n"
            )

        blocks: List[str] = []
        for state in states:
            header_item = f"## 子任务 {state.task_id}（{state.agent_id}）"
            if state.status == "done" and state.output:
                body = state.output[: self.settings.max_subagent_result_chars]
                blocks.append(f"{header_item}\n\n{body}")
            elif state.status == "failed":
                err = (state.error or "未知错误")[: self.settings.max_subagent_result_chars]
                blocks.append(f"{header_item}\n\n[失败] {err}")
            else:
                blocks.append(f"{header_item}\n\n[状态: {state.status}]")
        result = header + "\n\n".join(blocks)
        # F3 (2026-08-12): maxItems 放宽到 8 后单批聚合体积翻倍，整体截断兜底
        # （保留头部进度摘要 + 前部子任务），防一次性灌爆 conductor 上下文。
        if len(result) > self.settings.max_aggregate_chars:
            result = (
                result[: self.settings.max_aggregate_chars]
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

    def _review_block(self, verdict: str, count: int, note: str = "") -> str:
        """复核结论 markdown（追加进聚合，进入 conductor 上下文）。

        Wave 2 Minor 1 fix: 新增 note 参数 —— 0-parse 等特殊失败原因备注行。
        """
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
        # Wave 2 Minor 1 fix: 0-parse → verdict=fail（消除 vacuous pass ——
        # reviewer 什么都没产出却判 pass 的静默假阳性）。
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
        block = self._review_block(verdict, len(assertions), note=review_note)
        # Wave 2: task_review NDJSON 事件契约（spec §5.2）—— verdict 产出后
        # 立即推 entry_queue，前端 TaskReviewEvent 消费展示。
        self._emit_task_review(
            task_id=task_id,
            verdict=verdict,
            assertion_count=len(assertions),
            summary=review_note or f"{verdict}（{len(assertions)} 条 assertion）",
        )
        logger.info("编排复核完成: verdict=%s, assertions=%d", verdict, len(assertions))
        return {"verdict": verdict, "block": block, "assertion_count": len(assertions)}

    def _emit_task_review(
        self,
        task_id: str,
        verdict: str,
        assertion_count: int,
        summary: str,
    ) -> None:
        """推 task_review NDJSON 事件；队列满/关闭静默降级（spec §8）。"""
        event: Dict[str, Any] = {
            "state": "task_review",
            "run_id": self.run_id,
            "task_id": task_id,
            "reviewer_id": "reviewer",
            "verdict": verdict,
            "assertion_count": assertion_count,
            "summary": summary,
        }
        try:
            self.entry_queue.put_nowait(event)
        except Exception:  # noqa: BLE001 — 降级铁律
            logger.debug("task_review 推送失败（队列满/关闭），忽略")
