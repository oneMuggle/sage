"""统一的编排规划进度事件协议（2026-11-25）。

供 plan_preflight / legacy_routes / planner 共用：把"分类→澄清→侦察→
调研→拆解"各阶段的开始、心跳、完成、跳过、失败统一成 ``plan_progress``
事件，前端 PlanningTimeline 据此渲染气泡内时间线。

纪律：本模块的所有 emit 都不得阻断或改变规划主流程 —— 推送失败只记
debug；包装器对 runner 的异常原样上抛，由调用方既有降级逻辑处理。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

PLAN_STAGE_MODE_CLASSIFY = "mode_classify"
PLAN_STAGE_COMPLEXITY_CLASSIFY = "complexity_classify"
PLAN_STAGE_CLARIFY = "clarify"
PLAN_STAGE_SCOUT = "scout"
PLAN_STAGE_SCOUT_DEEP = "scout_deep"
PLAN_STAGE_DECOMPOSE = "decompose"

STATUS_STARTED = "started"
STATUS_PROGRESS = "progress"
STATUS_DONE = "done"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"

KIND_MESSAGE = "message"
KIND_THINKING = "thinking"
KIND_TOOL_CALL = "tool_call"
KIND_TOOL_RESULT = "tool_result"
KIND_REASONING = "reasoning"
KIND_HEARTBEAT = "heartbeat"
KIND_SKIP_REASON = "skip_reason"
KIND_ERROR = "error"

MAX_PROGRESS_TEXT = 500

#: plan_progress.detail 的序列化字节上限 —— 超限丢弃 detail（正文仍在），
#: 避免单条 NDJSON 行被撑爆。与 ``SCOUT_CLIENT_META_MAX_BYTES`` 同口径：
#: 落库与实时下发用同一预算，避免"实时无清单、刷新后却有"的不一致。
MAX_PROGRESS_DETAIL_BYTES = 32768

Emit = Callable[[Dict[str, Any]], Awaitable[None]]


def _safe_detail(detail: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """裁剪 detail：不可序列化或超限时丢弃（正文 text 不受影响）。"""
    if not detail:
        return {}
    try:
        encoded = json.dumps(detail, ensure_ascii=False)
    except (TypeError, ValueError):
        logger.warning("plan_progress detail 不可序列化，已丢弃")
        return {}
    if len(encoded.encode("utf-8")) > MAX_PROGRESS_DETAIL_BYTES:
        logger.warning(
            "plan_progress detail 超过 %d 字节，已丢弃", MAX_PROGRESS_DETAIL_BYTES
        )
        return {}
    return detail


async def emit_plan_progress(
    emit: Optional[Emit],
    *,
    stage: str,
    status: str,
    kind: str = KIND_MESSAGE,
    text: str = "",
    detail: Optional[Dict[str, Any]] = None,
    elapsed_ms: Optional[int] = None,
) -> None:
    """推送单条 plan_progress；emit 缺失/失败一律静默。"""
    if emit is None:
        return
    payload: Dict[str, Any] = {
        "stage": stage,
        "status": status,
        "kind": kind,
        "text": text[:MAX_PROGRESS_TEXT],
        "detail": _safe_detail(detail),
    }
    if elapsed_ms is not None:
        payload["elapsed_ms"] = int(elapsed_ms)
    try:
        await emit({"state": "plan_progress", "plan_progress": payload})
    except Exception:  # noqa: BLE001 — 进度事件绝不阻断规划
        logger.debug("plan_progress emit 失败: %s/%s", stage, status, exc_info=True)


async def emit_planning_skipped(
    emit: Optional[Emit],
    *,
    stages: List[str],
    reason: str,
) -> None:
    """批量标记若干阶段为 skipped（捷径路径：模板/计划模式/简单任务）。"""
    for stage in stages:
        await emit_plan_progress(
            emit,
            stage=stage,
            status=STATUS_SKIPPED,
            kind=KIND_SKIP_REASON,
            text=reason,
        )


async def run_planning_stage(
    emit: Optional[Emit],
    *,
    stage: str,
    runner: Callable[[], Awaitable[Any]],
    heartbeat_interval_s: float = 5.0,
    describe_result: Optional[Callable[[Any], str]] = None,
    detail_result: Optional[Callable[[Any], Dict[str, Any]]] = None,
) -> Any:
    """包裹单个规划阶段：started → (heartbeat…) → done/failed。

    runner 的返回值原样返回；异常原样上抛（调用方保留既有降级语义）。
    外层取消时取消内层 task 并补发 failed 事件后继续上抛 CancelledError。

    ``detail_result``（2026-11-27）：把 runner 结果转成 done 事件的结构化
    ``detail``（如侦察事实清单）—— 前端据此渲染可展开的事实区块。

    注意：``asyncio.wait`` 只接受 Task/Future 集合 —— py3.10 传 coroutine
    会直接 TypeError（py3.8 只是弃用告警），因此必须 ``ensure_future``。
    """
    interval = max(0.05, heartbeat_interval_s)
    started_at = time.monotonic()

    def _elapsed_ms() -> int:
        return int((time.monotonic() - started_at) * 1000)

    await emit_plan_progress(emit, stage=stage, status=STATUS_STARTED, text="")
    task: asyncio.Future[Any] = asyncio.ensure_future(runner())
    try:
        while True:
            done, _pending = await asyncio.wait({task}, timeout=interval)
            if task in done:
                result = task.result()
                text = describe_result(result) if describe_result is not None else ""
                detail: Optional[Dict[str, Any]] = None
                if detail_result is not None:
                    try:
                        detail = detail_result(result)
                    except Exception:  # noqa: BLE001 — detail 构造失败不阻断规划
                        logger.warning(
                            "plan_progress detail_result 失败: stage=%s", stage, exc_info=True
                        )
                        detail = None
                await emit_plan_progress(
                    emit,
                    stage=stage,
                    status=STATUS_DONE,
                    text=text or "",
                    detail=detail,
                    elapsed_ms=_elapsed_ms(),
                )
                return result
            await emit_plan_progress(
                emit,
                stage=stage,
                status=STATUS_PROGRESS,
                kind=KIND_HEARTBEAT,
                elapsed_ms=_elapsed_ms(),
            )
    except asyncio.CancelledError:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        # 取消路径自身处于取消上下文：向下游推「已取消」事件最多等 100ms，
        # 避免挂起的 emit 回调把取消拖延成悬挂任务；失败一律吞掉后照常 re-raise。
        with contextlib.suppress(Exception):
            await asyncio.wait_for(
                emit_plan_progress(
                    emit,
                    stage=stage,
                    status=STATUS_FAILED,
                    kind=KIND_ERROR,
                    text="已取消",
                    elapsed_ms=_elapsed_ms(),
                ),
                timeout=0.1,
            )
        raise
    except Exception as exc:  # noqa: BLE001 — 原样上抛给调用方降级
        await emit_plan_progress(
            emit,
            stage=stage,
            status=STATUS_FAILED,
            kind=KIND_ERROR,
            text=str(exc),
            elapsed_ms=_elapsed_ms(),
        )
        raise


def make_stream_progress_emitter(
    emit: Optional[Emit],
    *,
    stage: str,
    flush_chars: int = 200,
    flush_interval_s: float = 0.6,
) -> Callable[[str, str], Awaitable[None]]:
    """把逐 delta 的流式回调聚合成节流的 plan_progress progress 事件。"""
    buffer: List[str] = []
    state: Dict[str, float] = {"last_flush": time.monotonic()}

    async def _on_delta(kind: str, text: str) -> None:
        if not text:
            return
        buffer.append(text)
        now = time.monotonic()
        if (
            sum(len(part) for part in buffer) < flush_chars
            and now - state["last_flush"] < flush_interval_s
        ):
            return
        chunk = "".join(buffer).strip()
        buffer.clear()
        state["last_flush"] = now
        if chunk:
            await emit_plan_progress(
                emit,
                stage=stage,
                status=STATUS_PROGRESS,
                kind=kind,
                text=chunk,
            )

    return _on_delta
