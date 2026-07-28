"""todo_write / structured_output 工具的会话级内存状态存储。

claw-code 把 todo 列表落盘（``.clawd-todos.json``）；sage 的 todo 与
structured output 都是**会话内的 agent 内部状态**，无需持久化：

- 以 ``ToolExecutionContext.session_id`` 为键做会话隔离，并发会话互不
  串扰；无上下文的调用（单测 / 内部任务）落到单一匿名桶。
- 线程安全（``RLock``）；存取均返回拷贝，调用方无法篡改存储内部结构。
- 纯内存、无 I/O、导入无副作用。
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

from .context import current_tool_context

#: 无 ToolExecutionContext 时的兜底会话键
ANONYMOUS_SESSION_ID = "__anonymous__"


def resolve_session_id() -> str:
    """取当前 ContextVar 上下文的 session_id；无上下文 → 匿名桶。"""
    ctx = current_tool_context()
    return ctx.session_id if ctx is not None else ANONYMOUS_SESSION_ID


class SessionStateStore:
    """按键隔离的「最后一次写入」状态存储（全量替换语义）。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._buckets: Dict[str, Any] = {}

    def replace(self, session_id: str, value: Any) -> None:
        """整体替换 ``session_id`` 桶的内容（深拷贝一层 dict/list 元素）。"""
        with self._lock:
            self._buckets[session_id] = _shelter(value)

    def get(self, session_id: str) -> Any:
        """读取桶内容副本；不存在 → ``None``。"""
        with self._lock:
            value = self._buckets.get(session_id)
            return _shelter(value)

    def clear(self, session_id: Optional[str] = None) -> None:
        """清空指定桶；``session_id=None`` 清空全部（测试复位用）。"""
        with self._lock:
            if session_id is None:
                self._buckets.clear()
            else:
                self._buckets.pop(session_id, None)


def _shelter(value: Any) -> Any:
    """对 list[dict] 结构做一层防御性拷贝，其余类型原样返回。"""
    if isinstance(value, list):
        return [dict(item) if isinstance(item, dict) else item for item in value]
    if isinstance(value, dict):
        return dict(value)
    return value


_todo_store = SessionStateStore()


def get_todo_store() -> SessionStateStore:
    """todo_write 工具的全局存储单例。"""
    return _todo_store


__all__ = [
    "ANONYMOUS_SESSION_ID",
    "SessionStateStore",
    "resolve_session_id",
    "get_todo_store",
]
