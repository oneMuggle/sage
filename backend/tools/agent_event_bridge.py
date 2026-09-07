"""``agent`` 工具的聊天流事件桥（live-events P2 通路治理）。

背景：``AgentTool`` 在单 agent（非编排）模式下派遣只读子代理。其内部
事件（工具调用/结果/审批）此前对外完全不可见 —— 用户只能等最终答案。

本模块维护 session → 聊天流入队回调 的进程内注册表：聊天 producer 在
流开始时登记、结束时注销；``AgentTool.execute_async`` 在事件循环上
（与 producer 同一 loop，``put_nowait`` 安全）查表转发子代理事件。

线程模型说明：老的 ``execute``（同步,worker 线程 + ``asyncio.run``）
**不经**本桥 —— 跨线程不能直接 ``put_nowait``（不唤醒消费者）。事件
转发仅限异步通路，这也是把 run_loop 的 ``agent`` 分发迁到
``execute_async`` 的原因之一（见 agent.py 分发点）。
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

#: session_id → 聊天流入队回调（producer 生命周期内有效）。
_STREAM_EMITTERS: Dict[str, Callable[[Dict[str, Any]], None]] = {}


def register_stream_emitter(session_id: str, emit: Callable[[Dict[str, Any]], None]) -> None:
    """登记会话的聊天流入队回调（producer 在流开始时调用，覆盖旧值）。"""
    _STREAM_EMITTERS[session_id] = emit


def unregister_stream_emitter(session_id: str) -> None:
    """注销（producer finally 调用；未知 session 静默）。"""
    _STREAM_EMITTERS.pop(session_id, None)


def get_stream_emitter(session_id: Optional[str]) -> Optional[Callable[[Dict[str, Any]], None]]:
    """查会话的入队回调；未登记/无 session 返回 ``None``（转发降级关闭）。"""
    if not session_id:
        return None
    return _STREAM_EMITTERS.get(session_id)


__all__ = [
    "register_stream_emitter",
    "unregister_stream_emitter",
    "get_stream_emitter",
]
