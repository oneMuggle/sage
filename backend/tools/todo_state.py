"""todo_write / structured_output 工具的会话级内存状态存储。

claw-code 把 todo 列表落盘（``.clawd-todos.json``）；sage 的 todo 与
structured output 都是**会话内的 agent 内部状态**，无需持久化：

- 以 ``ToolExecutionContext.session_id`` 为键做会话隔离，并发会话互不
  串扰；无上下文的调用（单测 / 内部任务）落到单一匿名桶。
- 线程安全（``RLock``）；存取均返回拷贝，调用方无法篡改存储内部结构。
- LRU 上限 ``MAX_SESSION_BUCKETS``（256）：桶数溢出时淘汰最久未访问的
  桶，防止泄漏/伪造的 session_id 无限堆积撑爆内存。代价是被淘汰的
  长空闲会话丢失「最后状态」——todo / structured output 都是 agent 内部
  的 scratch 状态，可接受。
- 纯内存、无 I/O、导入无副作用。
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Optional

from .context import current_tool_context

#: 无 ToolExecutionContext 时的兜底会话键
ANONYMOUS_SESSION_ID = "__anonymous__"

#: 会话桶数量上限（LRU 淘汰）：防泄漏/伪造 session_id 无限堆积
MAX_SESSION_BUCKETS = 256


def resolve_session_id() -> str:
    """取当前 ContextVar 上下文的 session_id；无上下文 → 匿名桶。"""
    ctx = current_tool_context()
    return ctx.session_id if ctx is not None else ANONYMOUS_SESSION_ID


class SessionStateStore:
    """按键隔离的「最后一次写入」状态存储（全量替换语义）。

    带 LRU 淘汰：至多保留 ``max_buckets`` 个桶，溢出时淘汰最久未访问者。
    淘汰 = 长空闲会话的最后状态丢失——两类存储都是 agent 内部 scratch
    状态，可接受（见模块 docstring）。
    """

    def __init__(self, max_buckets: int = MAX_SESSION_BUCKETS) -> None:
        self._lock = threading.RLock()
        self._max_buckets = max_buckets
        self._buckets: OrderedDict[str, Any] = OrderedDict()

    def replace(self, session_id: str, value: Any) -> None:
        """整体替换 ``session_id`` 桶的内容（一层防御性浅拷贝，见 ``_shelter``）。

        写入计为一次 LRU 访问；超过容量上限时淘汰最久未访问的桶。
        """
        with self._lock:
            if session_id in self._buckets:
                self._buckets.move_to_end(session_id)
            self._buckets[session_id] = _shelter(value)
            while len(self._buckets) > self._max_buckets:
                self._buckets.popitem(last=False)

    def get(self, session_id: str) -> Any:
        """读取桶内容副本（计为 LRU 访问）；不存在 → ``None``。"""
        with self._lock:
            if session_id not in self._buckets:
                return None
            self._buckets.move_to_end(session_id)
            return _shelter(self._buckets[session_id])

    def clear(self, session_id: Optional[str] = None) -> None:
        """清空指定桶；``session_id=None`` 清空全部（测试复位用）。"""
        with self._lock:
            if session_id is None:
                self._buckets.clear()
            else:
                self._buckets.pop(session_id, None)


def _shelter(value: Any) -> Any:
    """防御性浅拷贝（一层）——嵌套结构共享引用。

    list → 新列表，其中 dict 元素各做一层 ``dict(item)`` 拷贝；dict →
    一层拷贝；其余类型原样返回。**深层嵌套对象仍与存储共享引用**：
    本拷贝只挡得住"增删外层元素/改外层键值"级别的篡改，挡不住对嵌套
    子结构的就地修改。
    """
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
    "MAX_SESSION_BUCKETS",
    "SessionStateStore",
    "resolve_session_id",
    "get_todo_store",
]
