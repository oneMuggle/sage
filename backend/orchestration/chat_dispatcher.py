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
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from backend.data.database import get_database
from backend.domain.orch_events import RunEvent, make_event
from backend.orchestration.events import EventRecorder
from backend.orchestration.executor import LaneExecutor
from backend.orchestration.lane_registry import LaneRegistry
from backend.orchestration.models import Lane, RecoveryPolicy, Task, TaskPacket
from backend.orchestration.orch_settings import OrchSettings, load_orch_settings
from backend.orchestration.report_schema import Assertion
from backend.orchestration.subagent_events import SubagentEventSink
from backend.orchestration.subagent_runner import (
    SubagentRunner,
    run_lane_accepts_backoff,
    run_lane_with_retry,
)
from backend.orchestration.task_registry import TaskRegistry
from backend.orchestration.topology import (
    DependencyCycleError,
    build_waves,
    downstream_closure,
    find_cycle,
)

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

#: 级联失败错误前缀 —— 下游任务因上游 failed/stopped 未启动即置 failed。
_CASCADE_ERROR_PREFIX = "blocked_by_failed:"

#: L2 (2026-08-23): followup 降级提示 —— 追加到聚合 markdown 对应子任务块尾部，
#: 让 conductor 明确"拿到的是新任务结果而非续聊上下文"，避免误以为续聊已生效。
_FOLLOWUP_DEGRADED_NOTE = (
    "\n[注意] followup 已降级为新任务（父任务不存在/未完成/自指），"
    "本次结果不含续聊上下文。"
)

#: 编排语义判定 prompt（轻量二分类）：LLM 只需回答 multi / single。
_CLASSIFY_PROMPT = """判断以下用户消息是否需要多 agent 协作（拆解为多个子任务、由不同角色并行执行）才能最好地完成。
只需返回一个词：multi 或 single。
- multi：复杂任务、多步骤、需要搜集资料/研究/并行工作。例如"我需要学习量化交易，先搜集相关资料后，整理一份学习资料和操作指南"。
- single：简单问答、单步请求。例如"今天天气怎么样"、"解释什么是递归"。

用户消息: {message}

答案:"""

#: scratch 根目录名（data_dir 下）。
SCRATCH_ROOT = "orch_scratch"

#: worktree 根目录名（data_dir 下）—— 创建（_create_worktree_for）与
#: 崩溃残留清扫（_sweep_stale_worktrees）共用，保证路径推导一致。
WORKTREES_ROOT = "orch_worktrees"

# 安全修复波 (2026-08-23): run_id 白名单 —— 客户端可控（ChatRequest.run_id /
# plan_override 路径无格式校验），却拼进 worktree/scratch 路径并参与
# ``shutil.rmtree``。不设白名单时 ``run_id="../../victim"`` 可路径穿越删除
# 任意目录；同 run_id 双活还会误删并发 run 的 worktree。首字符限字母数字
# （封死 ``-`` 开头被 git 当 flag、``.``/``_`` 开头歧义），后续允许字母数字、
# 下划线、连字符，上限 128 字符。生产生成值 ``orch-<uuid4>`` 天然合规。
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")

#: task_id 白名单 —— 与 run_id 同策略，防止 ``../../`` 路径穿越。
#: 生产值来自 LLM 计划（``t1``..``tN``）或自分配计数器，格式严格可控。
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


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
    output_schema: Optional[Dict[str, Any]] = None
    parent_task_id: Optional[str] = None
    status: str = "queued"  # queued|running|done|failed
    output: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    retry_count: int = 0
    # L2 (2026-08-23): followup_of 已携带但无法建立父依赖（不存在/未完成/自指）
    # → 降级为普通新任务并置位，聚合时对 conductor 显式提示不含续聊上下文。
    followup_degraded: bool = False
    # RD2 (round10): 重派原语 —— 本任务重派自哪个已失败/被取消的任务（继承
    # 其 scratch 现场 + error 注入 retry_hint）。None = 普通任务/降级。
    retry_of: Optional[str] = None
    # live-events P0: 派发本次批次的 conductor 工具调用 ID —— 前端聊天流内
    # 把 subagent_event 实时步骤关联到 "Delegate <goal>" 卡片的关联键。
    parent_tool_call_id: Optional[str] = None


# P2-9 (2026-08-14): 进程内活动 dispatcher 注册表 —— 供 run 级 cancel 端点
# 定位并置位取消事件。producer 在构造后注册、finally 注销（长连接结束即删）。
# live-events P1: 审批模式端点 / 审批 resolved 回填也经此定位 dispatcher。
_ACTIVE_DISPATCHERS: Dict[str, ChatDispatcher] = {}

#: 子代理审批模式合法取值（live-events P1）。
_APPROVAL_MODES = ("ask", "auto")


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
        workspace_root: Optional[str] = None,
        event_hub: Optional[Any] = None,
        session_id: Optional[str] = None,
    ) -> None:
        # 安全修复波 (2026-08-23): 白名单校验必须在任何副作用（DB 连接、
        # worktree 清扫）之前 —— 非法 run_id 直接拒绝构造。
        if not _RUN_ID_RE.fullmatch(run_id):
            raise ValueError(f"非法 run_id: {run_id!r}")
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
        self.workspace_root = workspace_root
        self._worktree_dirs: List[Path] = []
        self._states: Dict[str, ChatTaskState] = {}
        self._histories: Dict[str, List[Dict[str, Any]]] = {}
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
        # O3 (2026-09-08): 会话归因 —— 透传给 SubagentRunner → child.run_loop
        # → llm_client，让子代理 LLM 消耗落 usage_events.session_id（此前
        # 恒 NULL，会话级花费统计不含子代理）。init_orch_run 兜底再赋值。
        self.session_id = session_id
        # O1 (2026-09-08): steering 边界投递的 repo（构造失败降级 None，
        # 投递整体跳过 —— steering 是增强能力，绝不阻塞派发）。
        try:
            from backend.data.orch_context_repo import OrchestrationContextRepository

            self._context_repo = OrchestrationContextRepository()
        except Exception as exc:  # noqa: BLE001 — 降级铁律
            logger.debug("orch context repo 初始化失败，steering 投递停用: %s", exc)
            self._context_repo = None
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
        # BU2 (round11): run 级 token 预算守门状态 —— 触发一次即置位
        # （_cancelled 随之置位收口剩余任务），dispatch 入口据此拒绝后续批次。
        self._budget_exceeded = False
        self._budget_limit = 0
        # BD (round12): 后台派发句柄 —— 同一时刻至多一个在飞；collect 侧
        # shield 等待，超时/取消不杀派发本身。
        self._bg_task: Optional[asyncio.Task] = None
        # B3 (2026-09-09): 单任务跳过 —— task_id → skip 信号（cancel_task 置位）
        # 与 task_id → merged 取消事件（skip ∨ run 级取消，SubagentRunner 的
        # interrupt_event 消费）。_run_one 建档、finally 注销。
        self._task_skip_events: Dict[str, asyncio.Event] = {}
        self._task_cancel_events: Dict[str, asyncio.Event] = {}
        # live-events P0: canonical RunEvent 通道（EventHub.publish）。None 时
        # 惰性解析 orch_run_control.get_event_hub()（启动即装配），再取不到
        # 则仅镜像聊天流 —— 双通道缺一不阻塞另一。
        self._event_hub = event_hub
        # live-events P0: 本批次 conductor 工具调用 ID（dispatch_subagents
        # 经 notify_tool_call 注入），落到每个 ChatTaskState.parent_tool_call_id。
        self._current_tool_call_id: Optional[str] = None
        # live-events P1: 子代理审批模式（run 级，默认继承全局 orch 设置）。
        self.approval_mode: str = getattr(self.settings, "subagent_approval_mode", "ask")
        # live-events P1: 待决审批表 request_id → task_id，供 answer 路由回填。
        self._pending_approvals: Dict[str, str] = {}
        # M1 终审 (2026-08-23): 崩溃残留机会性清扫 —— 同 run_id 重派时清掉上次
        # 进程崩溃遗留的孤儿 worktree 目录。必须在任何子任务创建 worktree 之前
        # 执行（构造期即完成）；失败全吞降级，绝不阻塞派发。
        self._sweep_stale_worktrees()

    def _sweep_stale_worktrees(self) -> None:
        """删除本 run 的 ``<data_dir>/orch_worktrees/<run_id>`` 残留目录（若存在）。

        仅清本 run 自己的目录（其他并发 run 不受影响）。路径推导与
        ``_create_worktree_for`` 一致。rmtree 后 best-effort ``git worktree
        prune``（安全修复波 2026-08-23）—— 清掉主仓 ``.git/worktrees/`` 悬空
        条目，否则同路径重建 worktree 会 rc=128 失败静默回落 scratch。任何
        异常全吞降级 logger.debug。
        """
        try:
            data_dir = Path(get_database().db_path).parent
            stale_root = data_dir / WORKTREES_ROOT / self.run_id
            if stale_root.exists():
                shutil.rmtree(stale_root)
                logger.debug("已清扫崩溃残留 worktree 根: %s", stale_root)
                self._prune_after_sweep()
        except Exception as exc:  # noqa: BLE001 — 清扫失败不阻塞派发
            logger.debug("worktree 残留清扫跳过 run=%s err=%s", self.run_id, exc)

    def _prune_after_sweep(self) -> None:
        """rmtree 成功后清理 git worktree 管理元数据（best-effort，全吞降级）。"""
        try:
            from backend.orchestration.worktree import prune_worktrees

            root = Path(self.workspace_root) if self.workspace_root else None
            if root is None or not root.is_dir():
                return
            if not prune_worktrees(root):
                logger.debug("worktree prune 未成功 workspace=%s", root)
        except Exception as exc:  # noqa: BLE001 — prune 失败不阻塞派发
            logger.debug("worktree prune 跳过 run=%s err=%s", self.run_id, exc)

    def cancel(self) -> bool:
        """置位取消事件。幂等：已 set 返回 False，否则 True。"""
        if self._cancelled.is_set():
            return False
        self._cancelled.set()
        return True

    def cancel_task(self, task_id: str) -> bool:
        """B3 (2026-09-09): 单任务跳过 —— 只停一个子任务，不影响其余。

        queued（含等信号量槽位）→ acquire 后守卫直接转 cancelled（"skipped
        by user"）；running → merged 事件置位，SubagentRunner watcher 软中断
        子代理（同 run 级取消通道），下一迭代收口。

        Returns:
            True = 已受理；False = 任务不存在/已终态/重复跳过（端点转 409）。
            仅本批（已进 dispatch 的任务）可跳过 —— 尚未开波的后续批次任务
            还没有事件档案，返回 False。
        """
        skip = self._task_skip_events.get(task_id)
        if skip is None or skip.is_set():
            return False
        state = self._states.get(task_id)
        if state is None or state.status in ("done", "failed", "cancelled"):
            return False
        skip.set()
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

    def start_background_dispatch(
        self, tasks: List[Dict[str, str]]
    ) -> Optional[asyncio.Task]:
        """BD (round12): 以后台任务启动派发，立即返回句柄（不阻塞）。

        已有后台派发在飞（未终态）时返回 None —— conductor 应先 collect。
        """
        if self._bg_task is not None and not self._bg_task.done():
            return None
        self._bg_task = asyncio.create_task(
            self.dispatch(tasks), name=f"bg-dispatch-{self.run_id}"
        )
        return self._bg_task

    def background_snapshot(self) -> Dict[str, Any]:
        """BD3 (round13): 非阻塞快照 —— 各子任务当前状态与结果预览。

        status: none（从未后台派发）/ running（在飞）/ completed（已终态）。
        """
        if self._bg_task is None:
            status = "none"
        elif self._bg_task.done():
            status = "completed"
        else:
            status = "running"
        tasks = [
            {
                "task_id": s.task_id,
                "status": s.status,
                "output_preview": self._preview(s),
                "error": (s.error[:200] if s.error else None),
            }
            for s in self._states.values()
        ]
        return {"status": status, "tasks": tasks}

    async def wait_background(self, timeout: Optional[float] = None) -> str:
        """等待后台派发完成，返回聚合 markdown。

        ``asyncio.shield`` 保证 collect 的超时/取消不会杀掉派发本身
        （任务板照常推进，conductor 可再次 collect）。无在飞后台派发时
        抛 RuntimeError。
        """
        if self._bg_task is None:
            raise RuntimeError("no_background_dispatch: 尚无后台派发可收集")
        return await asyncio.wait_for(asyncio.shield(self._bg_task), timeout)

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
        # BU2 (round11): 预算触顶后拒绝后续批次 —— conductor 收到明确错误
        # 可停止重试派发（错误文本随工具结果进上下文）。
        if self._budget_exceeded:
            raise ValueError(
                f"budget_exceeded: 本 run token 预算（{self._budget_limit}）已耗尽，"
                "派发被拒绝。请直接基于已有结果输出最终汇总。"
            )
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
            raw_schema = raw.get("output_schema")
            output_schema = raw_schema if isinstance(raw_schema, dict) else None
            if raw_task_id and raw_task_id in self._plan_by_id:
                # P2-7 计划权威：goal/agent 以计划为准（计划卡
                # 编辑在派发前生效的杠杆点）。depends_on 直接随 plan_json 透传。
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
            # 安全前置：task_id 白名单校验，防止路径穿越。
            if not _TASK_ID_RE.fullmatch(task_id):
                safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", task_id)[:64] or "t_unsafe"
                logger.warning("task_id 不合规，已替换: %r -> %s", task_id, safe_id)
                task_id = safe_id
            followup_of = raw.get("followup_of")
            # L1 (2026-08-23): 自指 followup 守卫 —— task 引用自身不构成有效续聊。
            # 缺守卫时隐式自环依赖会被 build_waves 判环拒掉整批；改为 warning 后
            # 降级普通任务（与其余无效 followup_of 同一降级路径）。
            parent_task_id = (
                followup_of
                if isinstance(followup_of, str)
                and followup_of != task_id
                and followup_of in self._states
                and self._states[followup_of].status == "done"
                else None
            )
            # L2 (2026-08-23): 降级可见性 —— followup_of 已携带但无法建立父依赖
            # （不存在/未完成/自指）→ 置位，_aggregate 对 conductor 显式提示。
            followup_degraded = followup_of is not None and parent_task_id is None
            if parent_task_id is not None:
                # 续聊必须复用父任务的 agent/profile，避免历史 system prompt
                # 与新任务角色不一致；调用方传入的 agent_id 仅用于普通任务。
                agent_id = self._states[parent_task_id].agent_id
                # 续聊 goal 是新的 user 消息，不能被计划中的原始 goal 覆盖。
                goal = str(raw.get("goal", ""))
            state = ChatTaskState(
                task_id=task_id,
                agent_id=agent_id,
                goal=goal,
                output_schema=output_schema,
                parent_task_id=parent_task_id,
                followup_degraded=followup_degraded,
                parent_tool_call_id=self._current_tool_call_id,
            )
            if followup_of is not None and state.parent_task_id is None:
                logger.warning(
                    "无效 followup_of=%r，任务 %s 降级为普通新任务",
                    followup_of,
                    task_id,
                )
            # RD2/RD13 (round10/13): 重派原语 —— 源任务须本 run 内存在、非
            # 自身、且未 done（done 用 followup_of 续聊）。同批场景下源在
            # 解析时可能尚未执行（queued/running 也接受），失败原因由
            # _apply_retry_inheritance 在执行期读取。无效（不存在/done/自指）
            # 降级普通新任务（与无效 followup_of 同款降级路径）。
            retry_of_raw = raw.get("retry_of")
            state.retry_of = (
                retry_of_raw
                if isinstance(retry_of_raw, str)
                and retry_of_raw != task_id
                and retry_of_raw in self._states
                and self._states[retry_of_raw].status != "done"
                else None
            )
            if retry_of_raw is not None and state.retry_of is None:
                logger.warning(
                    "无效 retry_of=%r，任务 %s 降级为普通新任务",
                    retry_of_raw,
                    task_id,
                )
            self._states[state.task_id] = state
            states.append(state)
            self._emit_task_status(state)  # queued

        # P1 拓扑调度 (spec 2026-08-21): 派发前环预检 —— 拒单时未发任何
        # 子代理、仅 queued 事件。错误经工具层回传 conductor 可自纠重派。
        batch_plan_deps: Dict[str, List[str]] = {}
        for raw_item in tasks:
            rid = raw_item.get("task_id")
            if rid and rid in self._plan_by_id:
                batch_plan_deps[str(rid)] = [
                    str(d)
                    for d in (self._plan_by_id[rid].get("depends_on") or [])
                ]
        cycle = find_cycle(batch_plan_deps)
        if cycle:
            raise ValueError(
                "任务依赖存在环，拒绝派发：" + " -> ".join(cycle)
                + "。请修正 depends_on 后重新派发。"
            )

        async def _run_one(state: ChatTaskState) -> None:
            # B3 (2026-09-09): 单任务跳过 —— 每任务一对事件：``skip``（用户
            # 单任务跳过信号，cancel_task 置位）与 ``merged``（run 级取消 ∨
            # skip 的合并事件）。SubagentRunner 的 interrupt watcher 只收
            # 单个事件，故经 relay 把两个源都汇入 merged；runner 拿 merged
            # 后，run 级取消与单任务跳过走同一条软中断通道。
            skip = asyncio.Event()
            merged = asyncio.Event()
            self._task_skip_events[state.task_id] = skip
            self._task_cancel_events[state.task_id] = merged

            async def _relay(src: asyncio.Event) -> None:
                await src.wait()
                merged.set()

            relays = [
                asyncio.ensure_future(_relay(self._cancelled)),
                asyncio.ensure_future(_relay(skip)),
            ]
            # 源事件已置位时同步汇入 —— relay 任务尚未获得调度机会，
            # 否则 cancel-before-dispatch 场景守卫会漏判（历史语义回归）。
            if self._cancelled.is_set() or skip.is_set():
                merged.set()
            try:
                await _run_one_inner(state, skip, merged)
            finally:
                self._task_skip_events.pop(state.task_id, None)
                self._task_cancel_events.pop(state.task_id, None)
                for relay_task in relays:
                    relay_task.cancel()

        async def _run_one_inner(
            state: ChatTaskState,
            task_skip: asyncio.Event,
            merged_cancel: asyncio.Event,
        ) -> None:
            async with self._semaphore:
                # P2-9 (2026-08-14) + P0-3 (2026-08-20): 取消后 queued 任务不再启动
                # （转 cancelled）。守卫在 acquire 之后 —— 排队等槽的任务 cancel 前
                # 已越过入口，拿到槽后再判一次才真正短路；running 子任务经
                # SubagentRunner interrupt watcher 打断（interrupt_event=merged）。
                # B3: run 级取消与单任务跳过共用该守卫，error 文案区分。
                if merged_cancel.is_set():
                    state.status = "cancelled"
                    state.error = (
                        "cancelled by user"
                        if self._cancelled.is_set()
                        else "skipped by user"
                    )
                    self._emit_task_status(state)
                    return
                state.status = "running"
                state.started_at = time.time()
                self._emit_task_status(state)
                # 让其他子任务也有机会 emit running,保证 queued/running/done 三阶段序
                await asyncio.sleep(0)
                # RV1 (round8): 已完成任务回放 —— 计划条目带 preset_output
                # （rerun-failed 场景由端点注入原 output_preview）时直接收口
                # done：不建 lane、不派子代理、零 LLM 调用；histories 注入
                # user/assistant 对供 followup 回放与下游聚合。
                _plan_item = self._plan_by_id.get(state.task_id)
                _preset = _plan_item.get("preset_output") if _plan_item else None
                if isinstance(_preset, str) and _preset.strip():
                    preset_text = _preset.strip()
                    state.status = "done"
                    state.output = preset_text
                    self._histories[state.task_id] = [
                        {"role": "user", "content": state.goal},
                        {"role": "assistant", "content": preset_text},
                    ]
                    state.finished_at = time.time()
                    self._emit_task_status(state)
                    return
                # O2 (2026-09-08): wall-clock 超时 —— wait_for 取消内层协程
                # （子 run_loop 的 async for 在取消点收口，同 agent_tool 异步
                # 通路的 L12 根修语义）。0 = 关闭。超时任务置 failed（error
                # 前缀 task_timeout:），下游依赖任务由既有级联闭包收口。
                task_timeout = getattr(self.settings, "subagent_task_timeout_s", 0)
                try:
                    if task_timeout and task_timeout > 0:
                        content = await asyncio.wait_for(
                            self._run_subagent(state), timeout=task_timeout
                        )
                    else:
                        content = await self._run_subagent(state)
                    state.status = "done"
                    state.output = content
                except asyncio.TimeoutError:  # noqa: UP041 — py3.8 下 ≠ 内建 TimeoutError
                    state.status = "failed"
                    state.error = (
                        f"task_timeout: 子任务执行超过 {task_timeout} 秒，已强制终止"
                    )
                    logger.warning(
                        "subagent %s 超时（%ss），已终止", state.task_id, task_timeout
                    )
                except Exception as exc:  # noqa: BLE001 — 单任务失败隔离
                    # P0-3 (2026-08-20): cancel 触发的异常 → cancelled 而非 failed
                    # （SubagentRunner 已有 interrupt 通道，见 P0-1/P0-3）。
                    # B3: 单任务跳过（merged 置位但 run 未取消）同归 cancelled。
                    state.status = (
                        "cancelled" if merged_cancel.is_set() else "failed"
                    )
                    state.error = str(exc)
                    logger.warning("subagent %s failed: %s", state.task_id, exc)
                finally:
                    state.finished_at = time.time()
                    self._emit_task_status(state)
                    # BU2 (round11): 每任务终态后预算守门 —— 超限置位
                    # _cancelled，同批 queued 任务经既有 merged 守卫收口。
                    self._check_run_budget()

        # P1 拓扑调度 (spec 2026-08-21): 依 depends_on 分波执行。
        # - 波内 asyncio.gather 全并行（信号量限流不变）
        # - 波间屏障：上一波全部终态才进下一波
        # - 级联取消：上游 failed/stopped → 传递闭包内未启动下游直接置 failed
        #   （不发子代理运行），error 前缀 blocked_by_failed:<根因上游>。
        # 用户全局取消时不做级联标注（下游由 _run_one 统一转 cancelled）。
        deps_by_id: Dict[str, List[str]] = {}
        for state in states:
            plan_item = self._plan_by_id.get(state.task_id)
            raw_deps = (
                [str(d) for d in (plan_item.get("depends_on") or [])]
                if plan_item
                else []
            )
            deps_by_id[state.task_id] = [
                d for d in raw_deps if d in self._states and d != state.task_id
            ]
            if (
                state.parent_task_id
                and state.parent_task_id not in deps_by_id[state.task_id]
            ):
                deps_by_id[state.task_id].append(state.parent_task_id)

        # RD13 (round13): 重派任务剥离指向重派源的依赖 —— 源在同批先行失败
        # 时，波间闭包会把依赖它的重派任务连带判死（blocked_by_failed:），
        # 重派语义要求其独立执行（其余依赖保留波次语义）。
        for state in states:
            if state.retry_of and state.retry_of in deps_by_id.get(state.task_id, []):
                deps_by_id[state.task_id] = [
                    dep for dep in deps_by_id[state.task_id] if dep != state.retry_of
                ]

        try:
            waves = build_waves([s.task_id for s in states], deps_by_id)
        except DependencyCycleError as exc:  # 预检漏网（自指等）兜底
            raise ValueError(
                "任务依赖存在环，拒绝派发：" + " -> ".join(exc.cycle)
            ) from exc

        by_id = {s.task_id: s for s in states}
        cumulative_failed: Set[str] = set()
        for wave in waves:
            runnable = [
                by_id[tid]
                for tid in wave
                if by_id[tid].status not in ("failed", "cancelled")
            ]
            await asyncio.gather(*(_run_one(s) for s in runnable))
            if self._cancelled.is_set():
                continue
            newly_failed = {
                s.task_id for s in runnable if s.status in ("failed", "cancelled")
            }
            if not newly_failed:
                continue
            cumulative_failed |= newly_failed
            for tid in sorted(downstream_closure(deps_by_id, newly_failed)):
                downstream = by_id.get(tid)
                if downstream is None:
                    continue
                if downstream.status in ("failed", "cancelled", "done"):
                    continue
                culprits = [
                    d for d in deps_by_id.get(tid, []) if d in cumulative_failed
                ]
                downstream.status = "failed"
                downstream.error = _CASCADE_ERROR_PREFIX + (
                    ",".join(culprits) if culprits else "upstream"
                )
                # 级联置 failed 的任务并入累计失败集 —— 更下游才能引用到
                # 直接上游 id（否则多级链 t1→t2→t3 中 t3 拿不到 t2）。
                cumulative_failed.add(tid)
                downstream.finished_at = time.time()
                self._emit_task_status(downstream)
        aggregated = self._aggregate(states)
        # P0-2 验证环：仅当本次调用已覆盖 plan 全部任务后跑 reviewer；
        # 失败降级跳过（绝不阻塞聊天）。
        # Wave 2 P1-4: 加 _reviewed 一次性守卫 —— 同一 run 只 review 一次。
        # 2026-09-06: repo 层已改为 INSERT OR REPLACE（幂等 upsert），不再
        # 因重复 task_id 抛 IntegrityError，但保留 _reviewed 守卫避免浪费
        # token 重复跑 reviewer。
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
                    logger.warning("编排复核失败，跳过验证: %s", exc)
        return aggregated

    async def _run_subagent(self, state: ChatTaskState) -> str:
        """执行单个子任务，并在结束后清理该任务的临时 worktree。"""
        workspace_dir = await self._create_worktree_for(state)
        try:
            return await self._run_subagent_impl(state, workspace_dir)
        finally:
            if workspace_dir is not None:
                from backend.orchestration.worktree import remove_worktree_async

                try:
                    await remove_worktree_async(workspace_dir)
                except Exception as exc:  # noqa: BLE001 — 清理不得覆盖任务结果
                    logger.warning(
                        "子任务 %s worktree 清理异常（忽略）: %s",
                        state.task_id,
                        exc,
                    )
                if workspace_dir in self._worktree_dirs:
                    self._worktree_dirs.remove(workspace_dir)

    async def _run_subagent_impl(
        self, state: ChatTaskState, workspace_dir: Optional[Path]
    ) -> str:
        """经 LaneExecutor 执行子任务（P0-1）：创建 lane+task，复用重试策略。

        子 agent 优先使用 worktree 的 ToolPolicy 根目录；不可用时回落 scratch。
        """
        task_id = f"task-{state.task_id}"
        lane_id = f"lane-{state.task_id}"
        scratch_dir = self._scratch_dir_for(state)
        scratch_dir.mkdir(parents=True, exist_ok=True)

        parameters = {
            "goal": state.goal,
            "agent_id": state.agent_id,
            "scratch_dir": str(scratch_dir),
            "workspace_dir": str(workspace_dir) if workspace_dir else None,
        }
        self._apply_retry_inheritance(state, parameters)
        if state.parent_task_id is not None:
            parameters["history"] = self._histories.get(state.parent_task_id, [])
        if state.output_schema is not None:
            parameters["output_schema"] = state.output_schema

        task = Task(
            task_id=task_id,
            name=f"Subtask {state.task_id}",
            description=state.goal,
            parameters=parameters,
            packet=TaskPacket(
                objective=state.goal,
                recovery_policy=RecoveryPolicy(
                    on_failure="retry", max_retries=self.settings.max_retries
                ),
            ),
        )
        # RT10 (round7): 重试退避配置（RecoveryPolicy.retry_backoff_secs）传入
        # 重试环——字段此前无消费者，重试是立即连发。
        _backoff_secs = task.packet.recovery_policy.retry_backoff_secs
        self.task_registry.create_task(task)
        self.task_registry.mark_running(task_id)

        lane = Lane(
            lane_id=lane_id,
            task_id=task_id,
            agent_id=state.agent_id,
            worktree=str(workspace_dir) if workspace_dir else None,
            metadata={"task_id": state.task_id},
        )
        self.lane_registry.create_lane(lane)

        # live-events P0: 子代理中间事件投影 —— 聊天镜像 + canonical
        # task.step.*。双通道均尽力而为，缺一不阻塞另一。
        sink = SubagentEventSink(
            run_id=self.run_id,
            task_id=state.task_id,
            entity_task_id=state.task_id,
            agent_id=state.agent_id,
            goal=state.goal,
            parent_tool_call_id=state.parent_tool_call_id,
            emit_chat=self._emit_chat_event,
            publish_event=self._make_publisher(),
            note_approval=lambda request_id: self._pending_approvals.setdefault(
                request_id, state.task_id
            ),
        )

        executor = LaneExecutor(
            lane_registry=self.lane_registry,
            task_registry=self.task_registry,
            event_recorder=self.event_recorder,
            agent_runner=SubagentRunner(
                self.llm_config,
                # B3: 消费本任务 merged 取消事件（run 级取消 ∨ 单任务跳过）；
                # 无档案（理论不可达，防御）回落 run 级事件。
                interrupt_event=self._task_cancel_events.get(
                    state.task_id, self._cancelled
                ),
                event_sink=sink,
                approval_mode=self.approval_mode,
                session_id=self.session_id,
                context_repo=self._context_repo,
                # O1: 投递用 canonical task_id（t1..tN，与 steer 端点一致），
                # 不是 lane 空间的 "task-tN"。
                context_task_id=state.task_id,
            ),
        )
        # O5 (2026-09-08): 子代理执行期间置位嵌套深度 —— AgentTool 据此
        # 拒绝孙代理派生（自定义 profile 白名单含 agent 工具时防穿透）。
        from backend.orchestration.depth import (
            current_subagent_depth,
            enter_subagent_depth,
            exit_subagent_depth,
        )

        depth_token = enter_subagent_depth(current_subagent_depth() + 1)
        try:
            # RT10: backoff 仅对接受该 kwarg 的实现传递 —— 测试桩常见
            # (executor, lane, agent_id) 三参签名。mock.patch(side_effect=…)
            # 包装的 MagicMock 签名恒为 (*args, **kwargs)，须穿透到
            # side_effect 真实函数探测（run_lane_accepts_backoff），否则
            # kwarg 照样落进三参 fake 的 TypeError（CI 实证）。
            _pass_backoff = run_lane_accepts_backoff(run_lane_with_retry)
            if _pass_backoff:
                result = await run_lane_with_retry(
                    executor, lane, state.agent_id, backoff_secs=_backoff_secs
                )
            else:
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
                if _pass_backoff:
                    result = await run_lane_with_retry(
                        executor, lane, state.agent_id, backoff_secs=_backoff_secs
                    )
                else:
                    result = await run_lane_with_retry(executor, lane, state.agent_id)
        finally:
            exit_subagent_depth(depth_token)

        # 重试信息回填 state → task_status 事件携带
        state.retry_count = lane.metadata.get("retry_count", 0) if lane.metadata else 0
        if result.get("status") == "failed":
            raise RuntimeError(result.get("error", "subtask failed"))
        if result.get("status") != "succeeded":
            raise RuntimeError(f"subtask unexpected status: {result.get('status')}")
        result_payload = result.get("result")
        if isinstance(result_payload, dict):
            messages = result_payload.get("messages")
            if isinstance(messages, list):
                self._histories[state.task_id] = list(messages)
        return result_payload["output"]

    def _apply_retry_inheritance(
        self, state: ChatTaskState, parameters: Dict[str, Any]
    ) -> None:
        """RD2 (round10): 重派继承（就地改 parameters）。

        源任务 scratch 现场延续（避免重派=从零再来）+ error 注入 retry_hint
        （RT9 消费端前置"【重试 · 第 N 次】上次执行失败…"进子代理 prompt）。
        非 retry 任务（state.retry_of 为空）无操作。
        """
        if not state.retry_of:
            return
        src_state = self._states.get(state.retry_of)
        src_task = self.task_registry.get_task(f"task-{state.retry_of}")
        src_scratch = (
            src_task.parameters.get("scratch_dir") if src_task is not None else None
        )
        if isinstance(src_scratch, str) and src_scratch:
            parameters["scratch_dir"] = src_scratch
        parameters["retry_hint"] = {
            "attempt": (src_state.retry_count if src_state is not None else 0) + 1,
            "last_error": str(
                (src_state.error if src_state is not None else None) or "unknown"
            )[:2000],
        }
        logger.info(
            "任务 %s 为 %s 的重派（继承 scratch 现场 + 失败原因）",
            state.task_id,
            state.retry_of,
        )

    async def _create_worktree_for(self, state: ChatTaskState) -> Optional[Path]:
        """按配置为任务创建 worktree；任何不可用情况都回落 scratch。

        所有 git/路径操作在线程中执行，异常一律降级为 None —— 绝不阻塞聊天。
        """
        if not self.settings.worktree_isolation or not self.workspace_root:
            return None
        try:
            from backend.orchestration.worktree import (
                create_worktree_async,
                is_git_repo_async,
            )

            repo = Path(self.workspace_root)
            if not await is_git_repo_async(repo):
                logger.warning(
                    "worktree 隔离不可用，子任务 %s 回落 scratch", state.task_id
                )
                return None
            worktree_dir = (
                Path(get_database().db_path).parent
                / WORKTREES_ROOT
                / self.run_id
                / state.task_id
            )
            if await create_worktree_async(repo, worktree_dir):
                self._worktree_dirs.append(worktree_dir)
                return worktree_dir
            logger.warning("worktree 隔离不可用，子任务 %s 回落 scratch", state.task_id)
            return None
        except Exception as exc:  # noqa: BLE001 — 创建异常降级 scratch
            logger.warning(
                "worktree 隔离创建异常，子任务 %s 回落 scratch: %s",
                state.task_id,
                exc,
            )
            return None

    def _scratch_dir_for(self, state: ChatTaskState) -> Path:
        """子任务隔离目录：``<data_dir>/orch_scratch/<run_id>/<task_id>``。"""
        data_dir = Path(get_database().db_path).parent
        root = (data_dir / self.settings.scratch_root / self.run_id).resolve()
        candidate = (root / state.task_id).resolve()
        # containment: resolve() 后必须仍在 root 内，防符号链接或 ".." 逃逸。
        # Windows fix (2026-09-06): 原实现用 ``startswith(str(root) + "/")``,
        # 而 Windows 分隔符是 ``\`` —— 判断恒 False,每次 dispatch 都误报
        # "task_id 路径穿越"。改用 ``Path.relative_to``（语义等价且跨平台,
        # py3.8 兼容的 try/except 写法）。
        try:
            candidate.relative_to(root)
        except ValueError:
            raise ValueError(f"task_id 路径穿越: {state.task_id!r}") from None
        return candidate

    def _check_run_budget(self) -> None:
        """BU2 (round11): 任务终态后预算守门 —— 超限触发 run 级取消。

        预算键 ``OrchSettings.run_token_budget``（0 = 关闭）。用量窗口 =
        首次派发时间戳起的本 session 累计 total_tokens（O3 使子代理用量
        归因到同一 session）。只触发一次；usage 读取 fail-open 返 0，
        守门降级绝不误触发。
        """
        budget = getattr(self.settings, "run_token_budget", 0)
        if budget <= 0 or self._budget_exceeded:
            return
        if not self.session_id or not self._first_dispatch_at:
            return
        from backend.services.usage_tracker import UsageTracker

        used = UsageTracker().session_usage_since(
            self.session_id, int(self._first_dispatch_at * 1000)
        )
        if used > budget:
            self._budget_exceeded = True
            self._budget_limit = budget
            logger.warning(
                "run %s 触发 token 预算上限：已用 %d > 预算 %d，剩余任务停止派发",
                self.run_id,
                used,
                budget,
            )
            self._cancelled.set()

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
            "parent_tool_call_id": state.parent_tool_call_id,
        }
        try:
            self.entry_queue.put_nowait(event)
        except Exception:  # noqa: BLE001
            logger.debug("task_status 推送失败（队列满/关闭），忽略")
        # Wave 2 P1-4: 状态迁移同步写库。失败在 _persist_task_state 内部降级，
        # 绝不阻塞聊天进度推送。
        self._persist_task_state(state)
        self._publish_task_lifecycle(state)

    # ==================== live-events P0/P1 ====================

    def notify_tool_call(self, tool_call_id: Optional[str]) -> None:
        """记录本批次 conductor 的 dispatch_subagents 工具调用 ID。

        由 ``DispatchSubagentsTool.execute_async`` 在 dispatch 前调用；
        ``subagent_event`` / ``task_status`` 载荷携带它，前端据此把子代理
        实时步骤关联到聊天流里的 "Delegate <goal>" 卡片。
        """
        self._current_tool_call_id = tool_call_id

    _TASK_LIFECYCLE_EVENTS = {
        "queued": "task.queued",
        "running": "task.started",
        "done": "task.succeeded",
        "failed": "task.failed",
        "cancelled": "task.cancelled",
    }

    def _publish_task_lifecycle(self, state: ChatTaskState) -> None:
        """任务状态迁移 → canonical ``task.*`` 事件（fire-and-forget）。

        canonical 流（Drawer/快照/observe_subagents 的事实源）此前在 chat
        派发路径没有任务级事件源，task.step.* 事件会被快照层因"task 未建"
        丢弃。这里把 task_status 迁移同步投影为 task.queued/started/
        succeeded/failed/cancelled，让 step/审批事件有归属的 task 实体。
        发布失败全吞（观测尽力而为，绝不阻塞派发循环）。
        """
        event_type = self._TASK_LIFECYCLE_EVENTS.get(state.status)
        publisher = self._make_publisher()
        if event_type is None or publisher is None:
            return
        payload: Dict[str, Any] = {"goal": state.goal, "agent_id": state.agent_id}
        if state.status == "done":
            payload["output_preview"] = self._preview(state)
        elif state.status == "failed":
            payload["error"] = state.error
        event = make_event(
            run_id=self.run_id,
            seq=0,
            event_type=event_type,
            producer="chat-dispatcher",
            entity={"task_id": state.task_id, "agent_id": state.agent_id},
            payload=payload,
        )

        async def _run() -> None:
            try:
                await publisher(event)
            except Exception as exc:  # noqa: BLE001 — 观测尽力而为
                logger.debug("task lifecycle 事件发布失败 task=%s: %s",
                             state.task_id, exc)

        try:
            asyncio.get_running_loop().create_task(_run())
        except RuntimeError:  # pragma: no cover — 均在协程上下文调用
            return

    def set_approval_mode(self, mode: str) -> bool:
        """切换本 run 的子代理审批模式（"ask" | "auto"）；非法值返回 False。

        影响尚未启动的子任务（已运行中的子代理 enforcer 在构造时已定）。
        切换成功即向聊天流推 ``approval_mode`` 事件，前端任务树头部开关回显。
        """
        if mode not in _APPROVAL_MODES:
            return False
        self.approval_mode = mode
        self._emit_chat_event({
            "state": "approval_mode",
            "run_id": self.run_id,
            "mode": mode,
        })
        return True

    def _emit_chat_event(self, event: Optional[Dict[str, Any]]) -> None:
        """聊天流入队（subagent_event / approval_mode 镜像），降级同 task_status。"""
        if not event:
            return
        try:
            self.entry_queue.put_nowait(event)
        except Exception:  # noqa: BLE001 — 队列满/关闭不阻塞执行
            logger.debug("聊天镜像事件推送失败（队列满/关闭），忽略")

    def _make_publisher(self):
        """返回 canonical RunEvent 发布协程（EventHub.publish），未装配 → None。"""
        hub = self._event_hub
        if hub is None:
            try:
                from backend.api.orch_run_control import get_event_hub

                hub = get_event_hub()
            except Exception:  # noqa: BLE001 — 观测通道缺失不阻塞执行
                hub = None
        if hub is None:
            return None

        async def _publish(event: RunEvent) -> None:
            await hub.publish(event)

        return _publish

    async def resolve_approval(self, request_id: str, approved: bool) -> bool:
        """审批已应答 —— 回填 canonical ``task.approval_resolved`` + 聊天镜像。

        由 ``/permissions/{request_id}/answer`` 路由在 gate.answer 成功后调用
        （best-effort：未知 request_id / 通道缺失静默返回 False）。返回是否
        命中本 dispatcher 的待决审批。
        """
        task_id = self._pending_approvals.pop(request_id, None)
        if task_id is None:
            return False
        state = self._states.get(task_id)
        publisher = self._make_publisher()
        if publisher is not None:
            sink = SubagentEventSink(
                run_id=self.run_id,
                task_id=task_id,
                entity_task_id=task_id,
                agent_id=state.agent_id if state is not None else "",
                goal=state.goal if state is not None else "",
                parent_tool_call_id=(
                    state.parent_tool_call_id if state is not None else None
                ),
                emit_chat=self._emit_chat_event,
                publish_event=publisher,
            )
            await sink.emit_approval_resolved(request_id, approved)
        return True

    def init_orch_run(self, session_id: str, plan_json: str, original_request: str = "") -> None:
        """由 caller (legacy_routes) 在第一次 dispatch 前调一次。失败降级。

        original_request: resume 恢复流的原始请求（前端逐字重发）。
        """
        # O3: 构造未传 session_id 时兜底赋值（调用方总是持有会话 id）。
        if session_id and not self.session_id:
            self.session_id = session_id
        try:
            from backend.data.orch_run_repo import OrchRun

            self._orch_run_repo.upsert(OrchRun(
                run_id=self.run_id,
                session_id=session_id or "",
                status="running",
                created_at=int(time.time() * 1000),
                plan_json=plan_json,
                original_request=original_request or None,
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
        # BU3 (round11): 预算触顶提示 —— 让 conductor 知道取消原因是预算
        # 而非失败，直接基于已有结果汇总。
        if self._budget_exceeded:
            header += (
                f"- ⚠ 已触发 run 级 token 预算上限（>{self._budget_limit} tokens），"
                "剩余任务已停止派发。请基于以上已有结果直接给出最终汇总。\n"
            )

        blocks: List[str] = []
        for state in states:
            header_item = f"## 子任务 {state.task_id}（{state.agent_id}）"
            if state.status == "done" and state.output:
                body = state.output[: self.settings.max_subagent_result_chars]
                block = f"{header_item}\n\n{body}"
            elif state.status == "failed":
                err = (state.error or "未知错误")[: self.settings.max_subagent_result_chars]
                block = f"{header_item}\n\n[失败] {err}"
            else:
                block = f"{header_item}\n\n[状态: {state.status}]"
            # L2 (2026-08-23): followup 降级对 conductor 可见 —— 提示本块不含续聊上下文。
            if state.followup_degraded:
                block += _FOLLOWUP_DEGRADED_NOTE
            blocks.append(block)
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
        """解析 reviewer 输出的 assertion 行（Wave 3 B1 委托 review.parse_assertions）。

        保留方法壳：测试经 ``patch.object(dispatcher, "_parse_assertions", ...)``
        桩依赖此属性；实现体已搬至 ``backend.orchestration.review``，行为不变。
        """
        from backend.orchestration.review import parse_assertions

        return parse_assertions(raw)

    async def _run_review(self, aggregated: str) -> dict:
        """P0-2 验证环 —— 委托 review.run_review（Wave 3 B1 提取，行为不变）。"""
        from backend.orchestration.review import run_review

        return await run_review(
            run_id=self.run_id,
            aggregated=aggregated,
            task_registry=self.task_registry,
            lane_registry=self.lane_registry,
            event_recorder=self.event_recorder,
            llm_config=self.llm_config,
            max_chars=MAX_SUBAGENT_RESULT_CHARS,
            emit_review=self._emit_task_review,
        )

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


def find_dispatcher_for_approval(request_id: str) -> Optional[ChatDispatcher]:
    """在活动 dispatcher 注册表中定位持有该审批请求的 run（未命中 → None）。

    live-events P1: ``/permissions/{request_id}/answer`` 路由在 gate.answer
    成功后经此定位 dispatcher 并回填 ``task.approval_resolved`` 事件。
    """
    for dispatcher in _ACTIVE_DISPATCHERS.values():
        if request_id in dispatcher._pending_approvals:
            return dispatcher
    return None
