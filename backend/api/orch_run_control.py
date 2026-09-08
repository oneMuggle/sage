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
from typing import Deque, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from backend.data.orch_context_repo import (
    OrchestrationContextError,
    OrchestrationContextRepository,
)
from backend.data.orch_task_repo import OrchTaskRepository
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
    context_repo: Optional[OrchestrationContextRepository] = None,
    task_repo: Optional[OrchTaskRepository] = None,
) -> None:
    """注入运行时依赖（由 backend.main 启动时调用）。"""
    global _snapshot_store, _event_hub, _context_repo, _task_repo
    _snapshot_store = snapshot_store
    _event_hub = event_hub
    _context_repo = context_repo
    _task_repo = task_repo
    _steer_attempts.clear()


def get_event_hub() -> Optional[EventHub]:
    """返回启动时装配的 EventHub（live-events P0）。

    ChatDispatcher 发布 canonical ``task.step.*`` 事件时惰性取用 ——
    未启动/未装配返回 ``None``，调用方降级为仅镜像聊天流。
    """
    return _event_hub


def get_snapshot_store() -> Optional[SnapshotStore]:
    """返回启动时装配的 SnapshotStore（O4, 2026-09-08）。

    producer 在 multi 模式注册 ``observe_subagents`` 工具时取用 ——
    未启动/未装配返回 ``None``，调用方降级为不注册该工具。
    """
    return _snapshot_store


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
_steer_attempts: dict[tuple[str, str], Deque[float]] = defaultdict(deque)


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
