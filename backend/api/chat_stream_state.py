# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""活跃聊天流状态注册表（C2c，DSH 对标 R28，自 legacy_routes.py 迁出）。

三张纯内存注册表 + 两个中断纯函数的唯一归属：

- ``_ACTIVE_STREAMS``：stream_id → 本流真实运行实例（producer 在
  run_loop 前登记、finally 注销；/interrupt 经它命中真实 agent）；
- ``_PENDING_RUN_CANCELLATIONS``：run 级取消的 pending 令牌（plan 未
  绑定 stream 时暂存，dispatcher 绑定时由 producer 消费）；
- ``_RUN_CONFIRM_EVENTS``：run 确认事件（producer 发 task_plan 后等待
  前端"开始执行"；orch_routes.confirm_run 设置事件唤醒 producer）。

``interrupt_stream`` / ``interrupt_run`` 只操作内存注册表与运行实例，
不依赖 DB——独立成模块后可脱离 FastAPI 完整单测。

legacy_routes.py 再导出全部五个名字：orch_routes 的
``from backend.api.legacy_routes import _RUN_CONFIRM_EVENTS`` 与既有
测试路径零变更。调用方对注册表只做**原地变异**（赋键 / pop / add /
discard），不重绑名字——跨模块共享同一对象即语义正确。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional, Set

from backend.core.legacy.agent import SageAgent

__all__ = [
    "_ACTIVE_STREAMS",
    "_PENDING_RUN_CANCELLATIONS",
    "_RUN_CONFIRM_EVENTS",
    "interrupt_run",
    "interrupt_stream",
]

# P0-2 (2026-08-20): stream_id → 本流真实运行实例。旧 /interrupt 用
# Depends(get_agent) 每次新建空实例，中断信号永远到不了 producer 里
# 正在跑的 agent。producer 在 run_loop 前登记、finally 注销。
_ACTIVE_STREAMS: Dict[str, Dict[str, Any]] = {}
_PENDING_RUN_CANCELLATIONS: Set[str] = set()
# Fix #3 (2026-09-06): 用户确认事件 —— producer 发 task_plan 后等待用户在前端
# 点击"开始执行"。orch_routes.confirm_run 设置事件唤醒 producer。
# cancel_run 也会设置事件（以取消状态退出等待）。
_RUN_CONFIRM_EVENTS: Dict[str, asyncio.Event] = {}


def interrupt_stream(stream_id: Optional[str]) -> str:
    """中断目标流：主 agent interrupt（+ multi 模式 cancel dispatcher）。

    返回命中标识（"stream"/"none"）供端点回传与测试断言。
    纯内存注册表操作，不依赖 DB。
    """
    if not stream_id:
        return "none"
    entry = _ACTIVE_STREAMS.get(stream_id)
    if entry is None:
        return "none"
    entry["cancelled"] = True
    agent_obj: SageAgent = entry["agent"]
    agent_obj.interrupt()
    run_id = entry.get("run_id")
    if run_id:
        from backend.orchestration.chat_dispatcher import _ACTIVE_DISPATCHERS

        dispatcher = entry.get("dispatcher") or _ACTIVE_DISPATCHERS.get(run_id)
        if dispatcher is not None:
            dispatcher.cancel()
    return "stream"


def interrupt_run(run_id: str) -> str:
    """Cancel every active stream belonging to an orchestration run.

    If planning has not bound the run id to its stream yet, retain a pending
    cancellation token.  The producer consumes it when the dispatcher binds.
    """
    matched = False
    for entry in list(_ACTIVE_STREAMS.values()):
        if entry.get("run_id") != run_id:
            continue
        matched = True
        entry["cancelled"] = True
        agent_obj: SageAgent = entry["agent"]
        agent_obj.interrupt()
        dispatcher = entry.get("dispatcher")
        if dispatcher is None:
            from backend.orchestration.chat_dispatcher import _ACTIVE_DISPATCHERS

            dispatcher = _ACTIVE_DISPATCHERS.get(run_id)
        if dispatcher is not None:
            dispatcher.cancel()
    if not matched:
        # P2-9 兼容回退：run 级 cancel 在无 stream entry 时仍直接命中
        # dispatcher 注册表（如 resume 流或仅注册 dispatcher 的场景）。
        from backend.orchestration.chat_dispatcher import _ACTIVE_DISPATCHERS

        if _ACTIVE_DISPATCHERS.get(run_id) is not None:
            _ACTIVE_DISPATCHERS[run_id].cancel()
            return "stream"
        _PENDING_RUN_CANCELLATIONS.add(run_id)
    return "stream" if matched else "pending"
