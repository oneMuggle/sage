"""todo_write / structured_output 工具的会话级状态存储。

claw-code 把 todo 列表落盘（``.clawd-todos.json``）。sage 侧：

- **todo 清单自 B4 (2026-09-09) 起 write-through 持久化**（
  ``session_todos`` 表）：重启/重开会话后任务板可恢复。落库仅作用于
  todo 单例（``_NotifyingTodoStore``），读 miss 时从 DB 回填缓存；
  匿名桶（无会话上下文）不落库。落库/读库失败全部静默降级 —— 持久化
  是增强，绝不影响工具执行。
- **structured output 状态仍纯内存**：它是单次委派的输出格式 scratch，
  无跨重启价值，保持 ``SessionStateStore`` 原语义。
- 以 ``ToolExecutionContext.session_id`` 为键做会话隔离，并发会话互不
  串扰；无上下文的调用（单测 / 内部任务）落到单一匿名桶。
- 线程安全（``RLock``）；存取均返回拷贝，调用方无法篡改存储内部结构。
- LRU 上限 ``MAX_SESSION_BUCKETS``（256）：桶数溢出时淘汰最久未访问的
  桶，防止泄漏/伪造的 session_id 无限堆积撑爆内存。todo 被淘汰后可经
  DB 回填（B4），structured output 淘汰即失（可接受）。
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from contextlib import suppress
from typing import Any, Callable, Dict, List, Optional

from .context import current_tool_context

logger = logging.getLogger(__name__)

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
        self._cache_put(session_id, value)

    def _cache_put(self, session_id: str, value: Any) -> None:
        """写缓存（不触发持久化/通知）—— ``replace`` 与读 miss 回填共用。"""
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


#: todo 变更监听器：(session_id, 全量 todos) —— legacy_routes 注册以推 SSE。
TodoListener = Callable[[str, List[Dict[str, Any]]], None]

_listeners: List[TodoListener] = []


def add_todo_listener(listener: TodoListener) -> None:
    if listener not in _listeners:
        _listeners.append(listener)


def remove_todo_listener(listener: TodoListener) -> None:
    if listener in _listeners:
        _listeners.remove(listener)


def _notify_listeners(session_id: str, value: Any) -> None:
    """通知所有监听者；单个异常吞掉（推送是尽力而为）。"""
    for listener in list(_listeners):
        with suppress(Exception):  # 降级铁律：推送失败不影响工具执行
            listener(session_id, value)


class _NotifyingTodoStore(SessionStateStore):
    """replace 后同步通知监听者 + write-through 持久化（todo 单例）。

    B4 (2026-09-09): ``replace`` 同步落 ``session_todos`` 表；``get`` 在
    缓存 miss（冷启动/被 LRU 淘汰）时从 DB 回填缓存后返回。匿名桶不落
    库不回填。落库/读库失败静默降级 —— 持久化是增强，绝不影响工具执行。
    """

    def replace(self, session_id: str, value: Any) -> None:
        super().replace(session_id, value)
        self._persist(session_id, value)
        _notify_listeners(session_id, self.get(session_id))

    def get(self, session_id: str) -> Any:
        value = super().get(session_id)
        if value is None:
            value = self._load_persisted(session_id)
            if value is not None:
                # 回填缓存（走 _cache_put：不重复落库、不触发监听通知）。
                self._cache_put(session_id, value)
        return value

    @staticmethod
    def _persist(session_id: str, value: Any) -> None:
        if session_id == ANONYMOUS_SESSION_ID:
            return
        try:
            from backend.data.session_todo_repo import SessionTodoRepository

            SessionTodoRepository().upsert(
                session_id, value if isinstance(value, list) else []
            )
        except Exception as exc:  # noqa: BLE001 — 降级铁律
            logger.debug("todo 持久化失败（忽略）session=%s: %s", session_id, exc)

    @staticmethod
    def _load_persisted(session_id: str) -> Optional[List[Dict[str, Any]]]:
        if session_id == ANONYMOUS_SESSION_ID:
            return None
        try:
            from backend.data.session_todo_repo import SessionTodoRepository

            return SessionTodoRepository().get(session_id)
        except Exception as exc:  # noqa: BLE001 — 降级铁律
            logger.debug("todo 读取持久层失败（忽略）session=%s: %s", session_id, exc)
            return None

    def clear(self, session_id: Optional[str] = None) -> None:
        """清内存桶 + 删持久行 —— clear 语义是"处处遗忘"。

        B4 前只清内存；持久化后若不删行，get 会从 DB 复活已 clear 的清单。
        删库失败静默降级（与 _persist 同策略）。
        """
        super().clear(session_id)
        try:
            from backend.data.session_todo_repo import SessionTodoRepository

            repo = SessionTodoRepository()
            if session_id is None:
                repo.delete_all()
            elif session_id != ANONYMOUS_SESSION_ID:
                repo.delete(session_id)
        except Exception as exc:  # noqa: BLE001 — 降级铁律
            logger.debug("todo 持久行清理失败（忽略）session=%s: %s", session_id, exc)


_todo_store = _NotifyingTodoStore()


def get_todo_store() -> SessionStateStore:
    """todo_write 工具的全局存储单例。"""
    return _todo_store


__all__ = [
    "ANONYMOUS_SESSION_ID",
    "MAX_SESSION_BUCKETS",
    "SessionStateStore",
    "TodoListener",
    "add_todo_listener",
    "remove_todo_listener",
    "resolve_session_id",
    "get_todo_store",
]
