"""``orch_routes`` — 编排 run 的详情/计划更新/取消端点（Wave 2 P1-4）。

``get_run`` 供前端详情展示；``plan`` 更新仅允许未派发状态（首次 dispatch 后锁定,
防改已跑计划,返回 409）。由 legacy_router 挂载（``router.include_router``），
最终前缀 ``/api/v1/orch``。

Wave 4 (2026-09-06): 历史编排记录功能移除 —— 删除 ``list_runs`` (GET /runs)
和 ``resume_run`` (POST /runs/{id}/resume) 端点及其模型 (OrchRunSummary /
ResumeResponse)。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from backend.data.database import (  # noqa: F401 — _SQLITE_LOCK 由测试与文档语义保留
    _SQLITE_LOCK,
    make_with_db_lock,
)
from backend.data.orch_run_repo import OrchRun, OrchRunRepository
from backend.data.orch_task_repo import OrchTaskRepository

router = APIRouter(prefix="/orch", tags=["orchestration-runs"])


def with_db_lock(func):
    """装饰器：把 sync 函数包在全局 `_SQLITE_LOCK` 内,串行化 SQLite 访问。

    D3 (P6): 实现统一收敛到 ``database.make_with_db_lock`` —— 用
    FunctionType 把 wrapper 的 ``__globals__`` 重绑到本模块, 既满足
    FastAPI 字符串注解必须在本模块解析的约束 (body 模型如
    PlanUpdateRequest), 又消除与 legacy_routes 的重复实现漂移风险。
    """
    return make_with_db_lock(globals())(func)


class OrchRunDetail(BaseModel):
    run_id: str
    session_id: str
    status: str
    created_at: int
    plan: List[Dict[str, Any]]
    tasks: List[Dict[str, Any]]
    # Wave 3 A9: resume 恢复流原始请求
    original_request: Optional[str] = None


class SessionRunsResponse(BaseModel):
    """C1 (2026-09-09): 会话编排 run 列表（历史任务板恢复数据源）。"""

    runs: List[OrchRunDetail]


class PlanUpdateRequest(BaseModel):
    plan: List[Dict[str, Any]] = Field()  # ≥1 行守卫

    @field_validator("plan")
    @classmethod
    def _require_plan(cls, value: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not value:
            raise ValueError("plan must contain at least one item")
        return value


def _run_detail(run: OrchRun) -> OrchRunDetail:
    """C1 (2026-09-09): OrchRun → OrchRunDetail（get_run / 会话列表共用）。"""
    task_repo = OrchTaskRepository()
    plan = json.loads(run.plan_json).get("tasks", [])
    tasks = [
        {
            "task_id": t.task_id,
            "run_id": t.run_id,
            "agent_id": t.agent_id,
            "goal": t.goal,
            "status": t.status,
            "retry_count": t.retry_count,
            "error": t.error,
            "output_preview": t.output_preview,
            "started_at": t.started_at,
            "finished_at": t.finished_at,
            # RT24 (round32): 任务级用量/时长 —— 终态落库值，历史回看可见。
            "used_tokens": getattr(t, "used_tokens", None),
            "duration_ms": getattr(t, "duration_ms", None),
            "retry_of": getattr(t, "retry_of", None),
            # 任务层级：历史回放需返回父子与深度（spec 2026-09-19）。
            "parent_task_id": getattr(t, "parent_task_id", None),
            "depth": getattr(t, "depth", 0),
        }
        for t in task_repo.list_by_run(run.run_id)
    ]
    return OrchRunDetail(
        run_id=run.run_id,
        session_id=run.session_id,
        status=run.status,
        created_at=run.created_at,
        plan=plan,
        tasks=tasks,
        original_request=run.original_request,
    )


@router.get("/runs", response_model=SessionRunsResponse)
@with_db_lock
def list_session_runs(
    session_id: str = Query(..., min_length=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> SessionRunsResponse:
    """C1 (2026-09-09): 按会话列编排 run（新→旧），历史任务板恢复数据源。

    Wave 4 曾删除无过滤的 ``GET /runs``；本端点是带 session_id 归属过滤的
    窄口 —— 只返回该会话自己的 run（plan + tasks + 状态）。
    """
    runs = OrchRunRepository().list_by_session(session_id, limit=limit)
    return SessionRunsResponse(runs=[_run_detail(r) for r in runs])


@router.get("/runs/{run_id}", response_model=OrchRunDetail)
@with_db_lock
def get_run(run_id: str) -> OrchRunDetail:
    run_repo = OrchRunRepository()
    run = run_repo.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return _run_detail(run)


class RerunFailedResponse(BaseModel):
    """RV2 (round8): rerun-failed 响应 —— 前端拿 plan_override 走既有
    chatStream planOverride 通道重发（Wave 3 A10）。"""

    session_id: Optional[str] = None
    goal: str
    plan_override: List[Dict[str, Any]]


class RerunFailedRequest(BaseModel):
    """RV4 (round27): 可选任务子集 —— 单任务重试。

    提供 ``task_ids`` 时只重建所选失败任务及其下游未完成闭包；缺省
    （或 None）保持 RV2 语义：全部失败任务重建。
    """

    task_ids: Optional[List[str]] = None

    model_config = {"extra": "forbid"}


def _depends_closure(
    selected: List[str], deps_of: Dict[str, List[str]]
) -> List[str]:
    """所选任务 + 传递依赖闭包（下游引用所选者）。"""
    dependents: Dict[str, List[str]] = {}
    for tid, deps in deps_of.items():
        for d in deps:
            dependents.setdefault(d, []).append(tid)
    seen = list(selected)
    queue = list(selected)
    while queue:
        cur = queue.pop(0)
        for child in dependents.get(cur, []):
            if child not in seen:
                seen.append(child)
                queue.append(child)
    return seen


@router.post("/runs/{run_id}/rerun-failed", response_model=RerunFailedResponse)
@with_db_lock
def rerun_failed(
    run_id: str, payload: Optional[RerunFailedRequest] = None
) -> RerunFailedResponse:
    """RV2 (round8): 构造"只重跑失败任务"的计划覆盖。

    - done 任务 → 原条目 + ``preset_output``（orch_tasks.output_preview），
      dispatcher 原生短路回放（RV1），零 LLM 调用；
    - failed/cancelled/blocked/pending 任务 → 原条目重建（goal/agent_id/
      depends_on 保持）；
    - run 非终态 → 409；无失败任务 → 409；无计划 → 409。

    RV4 (round27): 带 ``task_ids`` 时退化为单任务重试 —— 只重建所选任务
    及其下游未完成闭包，其余失败任务不进入新计划（goal 文案说明）。
    """
    run_repo = OrchRunRepository()
    run = run_repo.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.status == "running":
        raise HTTPException(status_code=409, detail="run still running")
    detail = _run_detail(run)
    if not detail.plan:
        raise HTTPException(status_code=409, detail="run has no plan to rebuild")
    status_by_id = {t["task_id"]: t for t in detail.tasks}

    # RV4 (round27): 单任务重试 —— 解析所选子集与下游未完成闭包。
    selected: List[str] = []
    if payload is not None and payload.task_ids:
        plan_ids = {
            str(it.get("task_id") or f"t{i + 1}")
            for i, it in enumerate(detail.plan)
            if isinstance(it, dict)
        }
        deps_of: Dict[str, List[str]] = {}
        for i, it in enumerate(detail.plan):
            if not isinstance(it, dict):
                continue
            tid = str(it.get("task_id") or f"t{i + 1}")
            raw = it.get("depends_on")
            deps_of[tid] = [str(d) for d in raw] if isinstance(raw, list) else []
        for tid in payload.task_ids:
            if tid not in plan_ids:
                raise HTTPException(status_code=404, detail=f"task not found: {tid}")
            st = str((status_by_id.get(tid) or {}).get("status") or "pending")
            if st == "done":
                raise HTTPException(
                    status_code=409, detail=f"task already done: {tid}"
                )
            selected.append(tid)
        closure = set(_depends_closure(selected, deps_of))
    else:
        closure = None  # None = RV2 全量失败重建语义

    override: List[Dict[str, Any]] = []
    done_count = 0
    failed_count = 0
    excluded_count = 0
    for idx, item in enumerate(detail.plan):
        if not isinstance(item, dict):
            continue
        tid = str(item.get("task_id") or f"t{idx + 1}")
        task = status_by_id.get(tid) or {}
        status = str(task.get("status") or "pending")
        # RV4: 子集模式下，闭包外的未完成任务不进入新计划。
        if (
            closure is not None
            and tid not in closure
            and status in ("failed", "cancelled", "blocked", "pending")
        ):
            excluded_count += 1
            continue
        entry: Dict[str, Any] = {
            "task_id": tid,
            "goal": str(item.get("goal") or task.get("goal") or ""),
            "agent_id": str(
                item.get("agent_id") or task.get("agent_id") or "primary"
            ),
        }
        deps = item.get("depends_on")
        if isinstance(deps, list) and deps:
            entry["depends_on"] = [str(d) for d in deps]
        # 重跑保留层级（spec 2026-09-19）：否则重跑后的任务树退化为平铺。
        if item.get("parent_task_id"):
            entry["parent_task_id"] = str(item["parent_task_id"])
        if item.get("depth") is not None:
            try:
                entry["depth"] = max(0, int(item["depth"]))
            except (TypeError, ValueError):
                entry["depth"] = 0
        if status == "done":
            entry["preset_output"] = (
                str(task.get("output_preview") or "").strip()
                or "[已完成，结果未留存预览]"
            )
            done_count += 1
        elif status in ("failed", "cancelled", "blocked"):
            failed_count += 1
        override.append(entry)
    if failed_count == 0:
        raise HTTPException(status_code=409, detail="no failed tasks to rerun")
    original = (run.original_request or "").strip()
    if closure is not None:
        excluded_note = (
            "，另有 %d 个失败任务未包含" % excluded_count if excluded_count else ""
        )
        head = "单任务重试（%s，已完成 %d 个子任务结果保留%s）" % (
            ", ".join(selected),
            done_count,
            excluded_note,
        )
        goal = f"{head}：{original}" if original else head
    else:
        goal = (
            f"重跑失败任务（已完成 {done_count} 个子任务结果保留）：{original}"
            if original
            else f"重跑失败任务（已完成 {done_count} 个子任务结果保留）"
        )
    return RerunFailedResponse(
        session_id=run.session_id, goal=goal, plan_override=override
    )


@router.post("/runs/{run_id}/plan")
@with_db_lock
def update_plan(run_id: str, body: PlanUpdateRequest) -> Dict[str, Any]:
    repo = OrchRunRepository()
    run = repo.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.dispatched_at is not None or run.status != "running":
        raise HTTPException(status_code=409, detail="plan locked after dispatch")
    run.plan_json = json.dumps({"tasks": body.plan, "reasoning": ""}, ensure_ascii=False)
    repo.upsert(run)
    return {"ok": True, "run_id": run_id, "plan": body.plan}


class CancelRunRequest(BaseModel):
    reason: str = "user_cancelled"


class CancelRunResponse(BaseModel):
    ok: bool
    run_id: str
    status: str


class ApprovalModeRequest(BaseModel):
    """run 级子代理审批模式切换请求（live-events P1）。"""

    mode: str

    @field_validator("mode")
    @classmethod
    def _require_known_mode(cls, value: str) -> str:
        if value not in ("ask", "auto"):
            raise ValueError("mode must be 'ask' or 'auto'")
        return value


@router.post("/runs/{run_id}/approval-mode")
def set_approval_mode(run_id: str, body: ApprovalModeRequest) -> Dict[str, Any]:
    """切换本 run 的子代理审批模式（live-events P1 分级信任）。

    - ``ask``：风险工具逐次审批（默认；子代理审批请求会转发前端弹窗）
    - ``auto``：非危险工具自动批准，破坏性/可疑/边界升级仍转人工

    仅作用于**活动中的 run**（进程内注册表命中）；历史 run / 未派发 run
    返回 404 —— 模式不持久化，新 run 继承全局 orch 设置
    ``orch.subagentApprovalMode``。切换成功即向聊天流推 ``approval_mode``
    事件供前端任务树头部开关回显。
    """
    from backend.orchestration.chat_dispatcher import _ACTIVE_DISPATCHERS

    dispatcher = _ACTIVE_DISPATCHERS.get(run_id)
    if dispatcher is None:
        raise HTTPException(status_code=404, detail="active run not found")
    if not dispatcher.set_approval_mode(body.mode):
        raise HTTPException(status_code=422, detail=f"invalid mode: {body.mode}")
    return {"ok": True, "run_id": run_id, "mode": body.mode}


@router.post("/runs/{run_id}/cancel", response_model=CancelRunResponse)
@with_db_lock
def cancel_run(run_id: str, body: Optional[CancelRunRequest] = None) -> CancelRunResponse:
    """Run 级取消：置 cancelled + 停 dispatcher 新任务（running 不硬杀）。"""
    repo = OrchRunRepository()
    run = repo.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.status in ("cancelled", "completed", "failed"):
        raise HTTPException(status_code=409, detail=f"run already in terminal state: {run.status}")
    repo.update_status(run_id, "cancelled")
    # Fix #3 (2026-09-06): 若 producer 正在等待用户确认,唤醒它以取消状态退出。
    try:
        from backend.api.legacy_routes import _RUN_CONFIRM_EVENTS

        evt = _RUN_CONFIRM_EVENTS.get(run_id)
        if evt is not None:
            evt.set()
    except Exception:  # noqa: BLE001
        pass
    # 进程内注册表定位 dispatcher 与 primary agent 并置位。
    # late import 避免 orch_routes ↔ legacy_routes 的模块初始化环。
    try:
        from backend.api.legacy_routes import interrupt_run

        interrupt_run(run_id)
    except Exception as exc:  # noqa: BLE001 — 注册表命中失败不阻塞状态落库
        # Durable cancellation remains authoritative; log control-plane failure
        # so operators can detect a run that may still be executing.
        import logging

        logging.getLogger(__name__).warning(
            "run cancellation bridge failed for %s: %s", run_id, exc
        )
    return CancelRunResponse(ok=True, run_id=run_id, status="cancelled")


class CancelTaskResponse(BaseModel):
    ok: bool
    run_id: str
    task_id: str
    status: str


@router.post("/runs/{run_id}/tasks/{task_id}/cancel", response_model=CancelTaskResponse)
def cancel_run_task(run_id: str, task_id: str) -> CancelTaskResponse:
    """B3 (2026-09-09): 单任务跳过 —— 只停一个子任务，不影响其余。

    进程内注册表定位活动 dispatcher；queued 任务 acquire 后短路、running
    任务经 interrupt 通道软中断（同 run 级取消语义）。run 不活动 / 任务
    不在本批或已终态分别 404 / 409。
    """
    from backend.orchestration.chat_dispatcher import _ACTIVE_DISPATCHERS

    dispatcher = _ACTIVE_DISPATCHERS.get(run_id)
    if dispatcher is None:
        raise HTTPException(status_code=404, detail="active run not found")
    if not dispatcher.cancel_task(task_id):
        raise HTTPException(
            status_code=409,
            detail=f"task not cancellable (unknown/terminal): {task_id}",
        )
    return CancelTaskResponse(
        ok=True, run_id=run_id, task_id=task_id, status="cancelling"
    )


# Fix #3 (2026-09-06): 用户确认端点 —— 前端 PlanCard "开始执行" 按钮调用。
# 唤醒在 legacy_routes.producer 中等待的 asyncio.Event,触发 conductor 启动。


class ConfirmRunResponse(BaseModel):
    ok: bool
    run_id: str


@router.post("/runs/{run_id}/confirm", response_model=ConfirmRunResponse)
def confirm_run(run_id: str) -> ConfirmRunResponse:
    """用户确认编排计划 → 唤醒 producer 开始 conductor 执行。

    前置条件: run 状态为 running 且尚未派发 (dispatched_at is None)。
    若 run 不存在或已终态 → 404/409。
    """
    repo = OrchRunRepository()
    run = repo.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.status != "running":
        raise HTTPException(
            status_code=409, detail=f"run not in running state: {run.status}"
        )
    # 设置确认事件唤醒 producer。
    try:
        from backend.api.legacy_routes import _RUN_CONFIRM_EVENTS

        evt = _RUN_CONFIRM_EVENTS.get(run_id)
        if evt is not None:
            evt.set()
        else:
            # producer 可能已跳过等待（超时或竞态）,不影响确认语义
            import logging

            logging.getLogger(__name__).debug(
                "confirm_run: no pending confirm event for %s (producer may have passed)",
                run_id,
            )
    except Exception as exc:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).warning(
            "confirm_run: failed to set confirm event for %s: %s", run_id, exc
        )
    return ConfirmRunResponse(ok=True, run_id=run_id)


# ---------------------------------------------------------------------------
# Round 2 (2026-09-19): 计划模式 × 编排打通 —— 已批准计划文本 → 结构化任务项
# （docs/plans/2026-09-19_orch-plan-preflight-round2-plan.md）。前端批准条
# "按计划执行（编排）" → 本端点 → plan_override 通道派发（复用恢复流管道）。
# ---------------------------------------------------------------------------

#: 计划文本上限 —— /plan 产出的 markdown 实际远小于此；防病态输入。
PLAN_TEXT_MAX_CHARS = 20000

#: 计划文本结构化 prompt。要求 goal 自包含（子代理执行者看不到计划全文），
#: agent_hint 取种子角色；清洗交给 ``sanitize_llm_plan_tasks``（与 Planner
#: 同款纪律：≤8 任务、depends 只引更早任务、非法 hint 丢弃）。
_PLAN_ITEMS_PROMPT = """你是编排计划结构化助手。以下是一份用户已批准的执行计划文本，把它转换为可派发的任务列表。

计划文本:
{text}

要求:
1. 每个任务的 description 必须自包含——执行者只能看到它，看不到本计划全文；把该步骤做什么/涉及对象/预期产出写清楚，并给出可检验的完成定义（验收标准）。
2. agent_hint 从这些角色中选最合适的一个（无法确定则省略）: researcher / coder / writer / reviewer / memory_manager
3. depends_on 只引用更早任务的 id（t1、t2…）；任务总数不超过 {max_tasks} 个。
4. 可选 parent_task_id 表示所属父任务，只引用更早任务的 id；它只影响归属和展示，不创建执行依赖。

只返回 JSON（无 markdown 围栏、无多余文本）:
{{"tasks": [{{"id": "t1", "title": "短标题", "description": "自包含目标", "depends_on": [], "parent_task_id": null, "agent_hint": "researcher"}}], "reasoning": "拆解策略说明"}}"""


class PlanItemsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=PLAN_TEXT_MAX_CHARS)


class PlanItem(BaseModel):
    task_id: str
    agent_id: str
    goal: str
    depends_on: List[str] = Field(default_factory=list)
    # 任务层级（spec 2026-09-19）：parent 只表达归属，不参与调度。
    parent_task_id: Optional[str] = None
    depth: Optional[int] = None


class PlanItemsResponse(BaseModel):
    items: List[PlanItem]
    reasoning: str = ""


def placeholder_deps_to_ids(blocked_by: List[str]) -> List[str]:
    """sanitized 任务的 ``idx:k`` 占位依赖 → plan_override 的 ``t{k+1}`` id。

    sanitize 保证依赖只引更早任务，因此映射后仍是无环前向引用。
    """
    ids: List[str] = []
    for dep in blocked_by:
        if dep.startswith("idx:"):
            try:
                ids.append(f"t{int(dep.split(':', 1)[1]) + 1}")
            except ValueError:
                continue
    return ids


def _parse_plan_items_response(raw: Any) -> Optional[Tuple[List[Dict[str, Any]], str]]:
    """解析 LLM 结构化响应 → (sanitized tasks, reasoning)；不可用返回 None。"""
    from backend.orchestration.planner import _CODE_FENCE_RE

    if not isinstance(raw, str) or not raw.strip():
        return None
    text = _CODE_FENCE_RE.sub("", raw.strip()).strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    from backend.orchestration.planner import sanitize_llm_plan_tasks

    tasks = sanitize_llm_plan_tasks(data.get("tasks"))
    if not tasks:
        return None
    reasoning = data.get("reasoning")
    return tasks, reasoning if isinstance(reasoning, str) else ""


@router.post("/plan-items", response_model=PlanItemsResponse)
async def plan_items(body: PlanItemsRequest) -> PlanItemsResponse:
    """已批准计划文本 → 结构化编排任务项（plan_override 形状）。

    供前端"按计划执行（编排）"调用。显式用户动作，失败响亮：
    - 503 no_llm_configured —— 未配置 LLM 端点；
    - 502 llm_call_failed / plan_items_parse_failed —— LLM 调用失败或输出
      无法解析为任务列表（前端 toast 引导回落单 agent 执行按钮）。
    """
    from backend.orchestration.llm_factory import build_llm_client_from_settings
    from backend.orchestration.planner import MAX_PLAN_TASKS

    client = build_llm_client_from_settings()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="no_llm_configured: 计划结构化需要已配置的 LLM 端点",
        )

    prompt = _PLAN_ITEMS_PROMPT.replace("{text}", body.text).replace(
        "{max_tasks}", str(MAX_PLAN_TASKS)
    )
    try:
        raw = await client.complete(prompt)
    except Exception as exc:  # noqa: BLE001 — 上游错误原样透出给前端 toast
        raise HTTPException(status_code=502, detail=f"llm_call_failed: {exc}")

    parsed = _parse_plan_items_response(raw)
    if parsed is None:
        raise HTTPException(
            status_code=502, detail="plan_items_parse_failed: 未能从计划文本解析出任务列表"
        )
    tasks, reasoning = parsed

    # 占位符 → 计划项编号（sanitize 保证父级只引更早任务）。
    _id_by_placeholder = {
        task["_placeholder"]: f"t{index}" for index, task in enumerate(tasks, 1)
    }
    items = [
        PlanItem(
            task_id=f"t{index}",
            agent_id=task["parameters"].get("agent_hint", "primary"),
            goal=task["description"],
            depends_on=placeholder_deps_to_ids(task["blocked_by"]),
            parent_task_id=_id_by_placeholder.get(
                task.get("_parent_placeholder") or ""
            ),
        )
        for index, task in enumerate(tasks, 1)
    ]
    return PlanItemsResponse(items=items, reasoning=reasoning)
