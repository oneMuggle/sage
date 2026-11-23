"""Orchestration run control REST endpoints.

Provides:
- GET /orch/runs/{run_id}/snapshot — current run snapshot (JSON)
- GET /orch/runs/{run_id}/events?after_seq=N — NDJSON event stream
- POST /orch/runs/{run_id}/tasks/{task_id}/steer — parent-agent 追加上下文
- POST /orch/runs/{run_id}/cancel — run 取消控制
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from backend.data.orch_context_repo import (
    OrchestrationContextError,
    OrchestrationContextRepository,
)
from backend.data.orch_run_repo import OrchRunRepository
from backend.data.orch_task_repo import OrchTask, OrchTaskRepository
from backend.data.orch_transcript_repo import OrchTranscriptRepository
from backend.domain.orch_events import ControlEventType, Visibility, make_event
from backend.orchestration.event_hub import EventHub
from backend.orchestration.snapshot_store import SnapshotStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orch/runs", tags=["orchestration"])

# Module-level singletons, wired at startup by backend.main
_snapshot_store: Optional[SnapshotStore] = None
_event_hub: Optional[EventHub] = None
_context_repo: Optional[OrchestrationContextRepository] = None
_task_repo: Optional[OrchTaskRepository] = None


def configure(
    snapshot_store: SnapshotStore,
    event_hub: EventHub,
    context_repo: OrchestrationContextRepository | None = None,
    task_repo: OrchTaskRepository | None = None,
) -> None:
    """注入运行时依赖（由 backend.main 启动时调用）。"""
    global _snapshot_store, _event_hub, _context_repo, _task_repo
    _snapshot_store = snapshot_store
    _event_hub = event_hub
    _context_repo = context_repo
    _task_repo = task_repo
    _steer_attempts.clear()


def get_event_hub() -> EventHub | None:
    """返回启动时装配的 EventHub（live-events P0）。

    ChatDispatcher 发布 canonical ``task.step.*`` 事件时惰性取用 ——
    未启动/未装配返回 ``None``，调用方降级为仅镜像聊天流。
    """
    return _event_hub


def get_snapshot_store() -> SnapshotStore | None:
    """返回启动时装配的 SnapshotStore（O4, 2026-09-08）。

    producer 在 multi 模式注册 ``observe_subagents`` 工具时取用 ——
    未启动/未装配返回 ``None``，调用方降级为不注册该工具。
    """
    return _snapshot_store


# ---------------------------------------------------------------------------
# M4.2: canonical run 目录（TaskCenter 统一运行视图数据源）
# ---------------------------------------------------------------------------

# scope → orch_runs.status 集合。只作内部映射键，不接受用户自定义状态值。
_DIRECTORY_SCOPES: Dict[str, Tuple[str, ...]] = {
    "active": ("running",),
    "failed": ("failed",),
    "finished": ("completed", "cancelled"),
    "all": ("running", "completed", "failed", "cancelled"),
}


def _plan_tasks(plan_json: Optional[str]) -> List[Dict[str, Any]]:
    """解析 plan_json 的 tasks 列表（损坏/缺失降级为空，不阻断目录）。"""
    try:
        plan = json.loads(plan_json or "{}")
    except (TypeError, ValueError):
        return []
    if not isinstance(plan, dict):
        return []
    tasks = plan.get("tasks")
    return tasks if isinstance(tasks, list) else []


def _task_to_dict(task: OrchTask) -> Dict[str, Any]:
    return {
        "task_id": task.task_id,
        "run_id": task.run_id,
        "agent_id": task.agent_id,
        "goal": task.goal,
        "status": task.status,
        "retry_count": task.retry_count,
        "error": task.error,
        "output_preview": task.output_preview,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
        "used_tokens": task.used_tokens,
        "duration_ms": task.duration_ms,
        "parent_task_id": task.parent_task_id,
        "depth": task.depth,
        "retry_of": task.retry_of,
    }


@router.get("/directory")
async def list_run_directory(
    scope: Literal["active", "failed", "finished", "all"] = Query(default="active"),
    limit: int = Query(default=50, ge=1, le=200),
) -> JSONResponse:
    """M4.2: canonical run 目录 —— 跨会话列出 run 及其子任务。

    不依赖前端内存 taskBoard：会话从未被前端加载过时，TaskCenter 仍能
    从这里看到运行中的 run 与子任务（统一运行视图的真相层投影）。

    scope: active=running / failed=failed / finished=completed+cancelled / all

    注意：本路由必须早于 legacy ``/orch/runs/{run_id}`` 注册。orch_run_control
    在 ``backend/main.py`` 中先于 legacy_router 挂载，故 /directory 不会被
    当成 run_id 落到 catch-all 上。
    """
    runs = OrchRunRepository().list_by_statuses(
        _DIRECTORY_SCOPES[scope], limit=limit
    )
    tasks_by_run: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    if runs:
        task_repo = _task_repo or OrchTaskRepository()
        for task in task_repo.list_by_runs([run.run_id for run in runs]):
            tasks_by_run[task.run_id].append(_task_to_dict(task))
    return JSONResponse(
        {
            "generated_at": int(time.time() * 1000),
            "scope": scope,
            "runs": [
                {
                    "run_id": run.run_id,
                    "session_id": run.session_id,
                    "status": run.status,
                    "created_at": run.created_at,
                    "dispatched_at": run.dispatched_at,
                    "confirmed_at": run.confirmed_at,
                    "original_request": run.original_request,
                    "final_summary": run.final_summary,
                    "plan": _plan_tasks(run.plan_json),
                    "tasks": tasks_by_run.get(run.run_id, []),
                }
                for run in runs
            ],
        }
    )


@router.get("/{run_id}/snapshot")
async def get_snapshot(run_id: str) -> JSONResponse:
    """返回 run 的当前快照。"""
    if _snapshot_store is None:
        return JSONResponse({"error": "not_initialized"}, status_code=503)
    snapshot = _snapshot_store.get_run_snapshot(run_id)
    if snapshot is None:
        return JSONResponse({"error": "run_not_found"}, status_code=404)
    return JSONResponse(snapshot.to_dict())


@router.get("/{run_id}/events")
async def stream_events(
    request: Request,
    run_id: str,
    after_seq: int = Query(default=0, ge=0),
) -> StreamingResponse:
    """NDJSON 事件流，支持 after_seq 续传。

    客户端断线后可携带上次收到的 seq 重连，服务端从 after_seq 之后
    重放保留历史，然后继续推送新事件。慢客户端不阻塞其他订阅者。
    """
    if _event_hub is None:
        return StreamingResponse(
            _error_stream("not_initialized"),
            media_type="application/x-ndjson",
        )

    async def generate():
        subscription = await _event_hub.subscribe(run_id, after_seq=after_seq)
        try:
            async for event in subscription:
                if await request.is_disconnected():
                    break
                yield json.dumps(event.to_dict(), ensure_ascii=False) + "\n"
        except asyncio.CancelledError:
            pass
        finally:
            await subscription.close()

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _error_stream(message: str):
    yield json.dumps({"error": message}) + "\n"


@router.get("/{run_id}/tasks/{task_id}/transcript")
async def get_task_transcript(
    run_id: str,
    task_id: str,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
) -> JSONResponse:
    """任务过程消息分页（M1 transcript）。

    与 ``/events``（canonical 状态事件，NDJSON 流）互补：这里返回消息级
    过程记录（goal / reasoning / assistant / tool_call / tool_result /
    error），供任务详情 Transcript 视图回看，运行中按 ``after_seq`` 轮询续接。
    """
    repo = OrchTranscriptRepository()
    # 多取一条用于 has_more 判断
    messages = repo.list_messages(run_id, task_id, after_seq=after_seq, limit=limit + 1)
    has_more = len(messages) > limit
    page = messages[:limit]
    next_seq = page[-1].seq if page else after_seq
    return JSONResponse(
        {
            "run_id": run_id,
            "task_id": task_id,
            "messages": [message.to_dict() for message in page],
            "next_seq": next_seq,
            "has_more": has_more,
        }
    )


# ---------------------------------------------------------------------------
# Phase 3: 父 agent 注入（steer）/ run 取消
# ---------------------------------------------------------------------------


_STEER_CONTENT_MAX_BYTES = 8 * 1024
_VALID_MESSAGE_TYPES = {
    "constraint",
    "clarification",
    "additional_context",
    "correction",
    "priority_update",
    "reference",
}
_VALID_APPLY_MODES = {"next_boundary", "new_followup"}
_VALID_SOURCES = {"user", "parent_agent", "system"}
_STEER_RATE_LIMIT = 10
_STEER_RATE_WINDOW_SECONDS = 60.0
_steer_attempts: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)


@router.post("/{run_id}/tasks/{task_id}/steer")
async def steer_task(  # noqa: PLR0911 — many early-return validation paths
    request: Request,
    run_id: str,
    task_id: str,
) -> JSONResponse:
    """父 agent / 用户向运行中 task 追加上下文。

    并发控制：请求体需带 ``expected_task_revision``；服务端用 CAS 比对，
    版本不一致返回 ``409 task_state_changed``，客户端需重拉快照后重试。

    安全约束：
    - 仅接受 ``message_type`` 白名单（约束/澄清/参考等），不得扩权/绕过审批
    - 单条内容 ``content_redacted`` 上限 8 KB
    - task 处于终态（succeeded/failed/cancelled）时拒绝
    """
    if _context_repo is None or _task_repo is None or _event_hub is None:
        return JSONResponse({"error": "not_initialized"}, status_code=503)

    now = time.monotonic()
    attempts = _steer_attempts[(run_id, task_id)]
    while attempts and now - attempts[0] >= _STEER_RATE_WINDOW_SECONDS:
        attempts.popleft()
    if len(attempts) >= _STEER_RATE_LIMIT:
        # 释放空 deque，防止长期占用内存
        if not attempts:
            _steer_attempts.pop((run_id, task_id), None)
        return JSONResponse(
            {"error": "rate_limited", "retry_after_seconds": 60},
            status_code=429,
        )
    attempts.append(now)

    # 读 + 校验 body
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"error": "invalid_json", "detail": "request body is not valid JSON"},
            status_code=400,
        )
    if not isinstance(body, dict):
        return JSONResponse({"error": "invalid_body"}, status_code=400)

    source = body.get("source", "parent_agent")
    message_type = body.get("message_type")
    content = body.get("content_redacted") or body.get("content") or ""
    apply_mode = body.get("apply_mode", "next_boundary")
    expected_revision = body.get("expected_task_revision")
    created_by = body.get("created_by")

    # 白名单校验
    if source not in _VALID_SOURCES:
        return JSONResponse(
            {"error": "invalid_source", "source": source}, status_code=400,
        )
    if message_type not in _VALID_MESSAGE_TYPES:
        return JSONResponse(
            {"error": "invalid_message_type", "message_type": message_type},
            status_code=400,
        )
    if apply_mode not in _VALID_APPLY_MODES:
        return JSONResponse(
            {"error": "invalid_apply_mode", "apply_mode": apply_mode},
            status_code=400,
        )
    if not isinstance(content, str) or not content.strip():
        return JSONResponse({"error": "empty_content"}, status_code=400)
    if len(content.encode("utf-8")) > _STEER_CONTENT_MAX_BYTES:
        return JSONResponse(
            {"error": "content_too_large",
             "max_bytes": _STEER_CONTENT_MAX_BYTES},
            status_code=400,
        )
    if expected_revision is None:
        return JSONResponse(
            {"error": "missing_expected_task_revision"}, status_code=400,
        )
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
        return JSONResponse(
            {"error": "invalid_expected_task_revision"}, status_code=400,
        )

    # Task 存在性 + CAS + 持久化必须在同一快照锁内完成，避免终态事件
    # 在检查与 INSERT 之间插入，产生不可消费的 pending context。
    if _snapshot_store is None:
        return JSONResponse({"error": "not_initialized"}, status_code=503)
    async with _snapshot_store.task_steering_context(run_id, task_id) as state:
        if state is None:
            if _snapshot_store.get_run_snapshot(run_id) is None:
                return JSONResponse({"error": "run_not_found"}, status_code=404)
            return JSONResponse({"error": "task_not_found"}, status_code=404)
        task_status, current_revision = state
        if task_status in {"succeeded", "completed", "failed", "cancelled"}:
            return JSONResponse(
                {"error": "task_terminal", "task_status": task_status},
                status_code=409,
            )
        if current_revision != expected_revision:
            return JSONResponse(
                {
                    "error": "task_state_changed",
                    "expected_task_revision": expected_revision,
                    "current_task_revision": current_revision,
                },
                status_code=409,
            )

        try:
            msg = _context_repo.create(
                run_id=run_id,
                task_id=task_id,
                source=source,
                message_type=message_type,
                content_redacted=content,
                apply_mode=apply_mode,
                expected_task_revision=expected_revision,
                created_by=created_by,
            )
        except OrchestrationContextError as exc:
            return JSONResponse(
                {"error": "invalid_context", "detail": str(exc)}, status_code=400,
            )

        # 在锁内 bump 数据库审计 revision，使其成为可观察的 steer 次数痕迹。
        # 注意：此 revision 与 SnapshotStore 内存 revision 含义不同 ——
        # 内存 revision 跟踪 task 的所有状态变更事件（task.created / .started / .progress 等），
        # 用作 CAS 权威基准；DB revision 仅累计成功 steer 次数，用于事后审计。
        # 两者不应被视为同一值。
        if _task_repo is not None:
            try:
                _task_repo.bump_revision_for_steer(task_id)
            except Exception:  # noqa: BLE001 — 审计失败不应阻断 steer 成功路径
                logger.exception("steer: failed to bump DB audit revision for task %s", task_id)

    # 广播 task.context.append_requested + task.context.appended
    # producer_generation 与 task 当前值对齐，确保 steer 控制事件不被
    # SnapshotStore 的 "旧 worker 事件不覆盖新状态" 过滤丢弃。
    producer_generation = 0
    if _snapshot_store is not None:
        producer_generation = _snapshot_store.get_task_producer_generation(
            run_id, task_id
        )

    append_req_event = make_event(
        run_id=run_id,
        seq=0,  # EventHub.publish 会分配真实 seq
        event_type=ControlEventType.CONTEXT_APPEND_REQUESTED.value,
        producer="orch-run-control",
        producer_generation=producer_generation,
        entity={"task_id": task_id},
        payload={
            "context_id": msg.context_id,
            "source": source,
            "message_type": message_type,
            "apply_mode": apply_mode,
        },
        visibility=Visibility.INTERNAL.value,
        command_id=f"steer-req-{msg.context_id}",
    )
    await _event_hub.publish(append_req_event)

    appended_event = make_event(
        run_id=run_id,
        seq=0,
        event_type=ControlEventType.CONTEXT_APPENDED.value,
        producer="orch-run-control",
        producer_generation=producer_generation,
        entity={"task_id": task_id},
        payload={
            "context_id": msg.context_id,
            "source": source,
            "message_type": message_type,
        },
        visibility=Visibility.INTERNAL.value,
        command_id=f"steer-appended-{msg.context_id}",
    )
    await _event_hub.publish(appended_event)

    return JSONResponse(
        {
            "ok": True,
            "context_id": msg.context_id,
            "status": msg.status,
            "task_id": task_id,
            "run_id": run_id,
            "apply_mode": apply_mode,
        },
        status_code=202,
    )


__all__ = ["router", "configure"]
