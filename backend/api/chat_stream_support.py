# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""聊天流支撑函数（C2f，DSH 对标 R31，自 legacy_routes.py 迁出）。

producer 与聊天路由共用的纯支撑逻辑唯一归属：orch run 终态闭环、
dispatcher 构造（run_id 文案改写）、图片附件校验、memory_used 事件
构造、工作段清理、NDJSON 序列化。

legacy_routes 再导出全部名字——调用方（producer）留在 legacy_routes，
测试 patch ``backend.api.legacy_routes._finalize_orch_run`` 的 seam
不受影响。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from backend.orchestration.chat_dispatcher import ChatDispatcher
from backend.orchestration.orch_settings import load_orch_settings

logger = logging.getLogger(__name__)

#: run 终态 → canonical 事件类型（M4.3a）。
_RUN_TERMINAL_EVENT_TYPES: Dict[str, str] = {
    "completed": "run.completed",
    "failed": "run.failed",
    "cancelled": "run.cancelled",
}


def _read_orch_run_snapshot(run_id: str) -> Tuple[str, str]:
    """读 run 的 (status, session_id)；读失败按 ("", "") 降级。

    必须在 finalize **之前**读：用户取消端点先把 status 写成 ``cancelled``，
    随后的 finalize 会覆盖它 —— 只有提前快照才能识别出"被取消"。
    """
    try:
        from backend.data.orch_run_repo import OrchRunRepository

        run = OrchRunRepository().get(run_id)
        if run is None:
            return "", ""
        return getattr(run, "status", "") or "", getattr(run, "session_id", "") or ""
    except Exception as exc:  # noqa: BLE001 — 读失败不影响主流
        logger.debug("读取 orch run 快照失败 (%s): %s", run_id, exc)
        return "", ""


def _publish_run_terminal_event(
    run_id: str, status: str, final_summary: Optional[str]
) -> None:
    """发布 canonical run 终态事件（M4.3a）。

    EventHub 未装配 / 无运行中的事件循环时静默跳过 —— canonical 事件是
    观测通道，不能反过来阻断 run 收尾。
    """
    event_type = _RUN_TERMINAL_EVENT_TYPES.get(status)
    if event_type is None:
        return
    try:
        from backend.api.orch_run_control import get_event_hub

        hub = get_event_hub()
    except Exception as exc:  # noqa: BLE001 — 通道缺失不影响主流
        logger.debug("run 终态事件发布跳过 (%s): %s", run_id, exc)
        return
    if hub is None:
        return
    try:
        from backend.domain.orch_events import make_event

        event = make_event(
            run_id=run_id,
            seq=0,
            event_type=event_type,
            producer="chat-stream-support",
            payload={"status": status, "final_summary": final_summary or ""},
        )
    except Exception as exc:  # noqa: BLE001 — 构造失败不影响主流
        logger.debug("run 终态事件构造失败 (%s): %s", run_id, exc)
        return

    async def _publish() -> None:
        try:
            await hub.publish(event)
        except Exception as exc:  # noqa: BLE001 — 观测尽力而为
            logger.debug("run 终态事件发布失败 (%s): %s", run_id, exc)

    try:
        asyncio.get_running_loop().create_task(_publish())
    except RuntimeError:  # pragma: no cover — 均在协程上下文调用
        return


def _notify_orch_run_terminal(
    run_id: str, status: str, final_summary: Optional[str], session_id: str
) -> None:
    """推编排 run 终态系统通知（M4.3a）。失败只记日志，不影响主流。"""
    try:
        from backend.services.orch_run_notifications import (
            push_run_notification,
            summarize_for_notification,
        )

        push_run_notification(
            run_id,
            status,
            session_id=session_id or None,
            body=summarize_for_notification(final_summary),
        )
    except Exception as exc:  # noqa: BLE001 — 通知降级不影响主流
        logger.debug("编排 run 终态通知失败 (%s): %s", run_id, exc)


def _finalize_orch_run(
    run_id: Optional[str], status: str, final_summary: Optional[str]
) -> None:
    """P0-4 (2026-08-20): orch run 生命周期闭环（降级型）。

    此前 OrchRunRepository.finalize 生产路径零调用者，orch_runs 永远
    停留 "running"。single 路径 run_id=None 直接跳过。

    M4.3a: 闭环成功后补两件事 —— 发布 canonical run 终态事件
    （``run.completed`` / ``run.failed`` / ``run.cancelled``）、推系统通知。
    """
    if not run_id:
        return
    previous_status, session_id = _read_orch_run_snapshot(run_id)
    try:
        from backend.data.orch_run_repo import OrchRunRepository

        OrchRunRepository().finalize(run_id, status, final_summary)
    except Exception as exc:  # noqa: BLE001 — 闭环失败不影响主流
        logger.warning("orch run finalize 失败 (%s): %s", run_id, exc)
        return
    # effective_status 必须与 orch_runs 行的**最终状态**一致 ——
    # OrchRunRepository.finalize 的 SQL 只更新 status='running' 的行，
    # 已是终态的行不动（P0-4：不被迟到的 producer finally 覆盖）。
    #   - 之前 running → 行被写成 status
    #   - 之前已是终态 → 行保持原状态，通知也报原状态
    # 用户取消端点先写 cancelled 且对终态 run 返回 409，所以"之前是
    # cancelled"就意味着用户主动取消 —— 通知报 cancelled 而非 failed。
    if previous_status in _RUN_TERMINAL_EVENT_TYPES:
        effective_status = previous_status
    else:
        effective_status = status if status in _RUN_TERMINAL_EVENT_TYPES else "failed"
    _publish_run_terminal_event(run_id, effective_status, final_summary)
    _notify_orch_run_terminal(run_id, effective_status, final_summary, session_id)


def _build_orchestration_dispatcher(
    *,
    stream_id: str,
    entry_queue: Any,
    run_id: str,
    llm_config: Optional[Dict[str, Any]],
    total_tasks: Optional[int],
    workspace_root: Optional[str],
    session_id: Optional[str] = None,
    step_confirm: bool = False,
) -> ChatDispatcher:
    """构造 ChatDispatcher；非法 run_id 的 ValueError 重抛为前端可读文案。

    ChatDispatcher.__init__ 对 run_id 做白名单 fullmatch（防路径穿越/非法
    字符），非法值抛 ``ValueError(f"非法 run_id: {run_id!r}")`` —— 原始串含
    repr 与英文，直接透传给前端不可读。这里只改写文案：**拒绝语义保留**，
    不吞错、不降级 single（非法 run_id 是客户端 bug，应显式失败提示刷新，
    而非用"单机模式"掩盖）。
    """
    try:
        return ChatDispatcher(
            stream_id=stream_id,
            entry_queue=entry_queue,
            run_id=run_id,
            llm_config=llm_config,
            total_tasks=total_tasks,
            settings=load_orch_settings(),
            workspace_root=workspace_root,
            session_id=session_id,
            step_confirm=step_confirm,
        )
    except ValueError as exc:
        raise ValueError(
            "编排启动失败：run_id 格式非法（应为 orch-* 标识符），"
            f"请刷新后重试。原始信息: {exc}"
        ) from exc

#: G6: 图片附件上限（张数 / 单张解码后字节数）
_CHAT_IMAGE_MAX_COUNT = 4
_CHAT_IMAGE_MAX_BYTES = 5 * 1024 * 1024

_ALLOWED_IMAGE_MIME_PREFIXES = ("data:image/png", "data:image/jpeg", "data:image/webp", "data:image/gif")


def _validate_chat_images(images: List[str]) -> Optional[str]:
    """校验 base64 data URL 图片列表；返回错误文案或 None（全部合法）。"""
    if len(images) > _CHAT_IMAGE_MAX_COUNT:
        return f"图片数量 {len(images)} 超过上限 {_CHAT_IMAGE_MAX_COUNT}"
    import base64 as _base64

    for index, image_url in enumerate(images):
        if not isinstance(image_url, str) or not image_url.startswith(_ALLOWED_IMAGE_MIME_PREFIXES):
            return (
                f"images[{index}] 不是合法的图片 data URL"
                f"（支持 png/jpeg/webp/gif）"
            )
        _, _, payload = image_url.partition(",")
        if not payload:
            return f"images[{index}] 缺少 base64 数据段"
        try:
            decoded_size = len(_base64.b64decode(payload, validate=True))
        except Exception:
            return f"images[{index}] base64 解码失败"
        if decoded_size > _CHAT_IMAGE_MAX_BYTES:
            return (
                f"images[{index}] 解码后 {decoded_size} 字节超过单张上限 "
                f"{_CHAT_IMAGE_MAX_BYTES} 字节 (5 MiB)"
            )
    return None

def _memory_used_event_from_hits(
    hits: List[Dict[str, str]],
    session_id: str,
) -> Dict[str, Any]:
    """R17-E/R99: 由注入命中的结构化条目构造 memory_used 流事件。

    R99 起条目直接来自 ``get_context_with_hits`` 的实际注入内容（芯片
    展示与注入上下文严格同源，不再单独跑 recall）；每类总体截断 5 条、
    preview 由 MemoryManager 侧截 100 字。空命中返回 ``None``（事件属
    增强信息，绝不影响对话主流程）。
    """
    memories: List[Dict[str, Any]] = []
    for hit in hits or []:
        if not isinstance(hit, dict):
            continue
        preview = str(hit.get("preview", ""))
        if not preview.strip():
            continue
        memories.append(
            {
                "id": str(hit.get("id") or preview),
                "memory_type": str(hit.get("memory_type") or "memory"),
                "preview": preview,
            }
        )
    if not memories:
        return None
    return {
        "state": "memory_used",
        "session_id": session_id,
        "memories": memories[:5],
    }

def _clear_working_segment(agent: Any, session_id: str, segment_id: int) -> None:
    """清空共享工作记忆中指定段的消息（context-isolation Task 14）。

    **必须经 ``agent.memory_manager`` 取共享实例**：``WorkingMemory`` 是普通类
    （无单例/``__new__`` 覆盖），``WorkingMemory()`` 构造的是全新的空实例，
    对它调 ``clear_segment`` 遍历空队列、什么都清不掉（2026-09-18 修复）。

    bare agent（``memory_manager is None``）时静默跳过，不影响主流程。
    """
    memory_manager = getattr(agent, "memory_manager", None)
    if memory_manager is None:
        return
    memory_manager.working.clear_segment(session_id, segment_id)

def _ndjson(d: dict) -> str:
    """序列化为 NDJSON 行（以 \\n 结尾）。

    Args:
        d: 可被 json.dumps 序列化的字典

    Returns:
        单行 JSON 字符串，末尾带换行符
    """
    return json.dumps(d, ensure_ascii=False) + "\n"
