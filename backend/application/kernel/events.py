<<<<<<< HEAD
# ruff: noqa: UP006, UP007, UP035
=======
# ruff: noqa: UP006, UP007, UP035, UP045
>>>>>>> origin/main
"""四模式事件总线（emit / bail / serial / waterfall）。

插件之间需要的不只是"广播"，而是四种**契约不同**的交互：

============  ==============================================  ==================
模式          语义                                            典型场景
============  ==============================================  ==================
``emit``      同步广播，忽略返回值                            观测 / 日志 / 审计
``bail``      顺序执行，首个非 None/False 返回值即结果        守卫 / 拦截（是否允许）
``serial``    顺序 await，首个有效返回值终止链                多级审批
``waterfall`` 每个监听器包装下游结果，必须消费 next           中间件 / 参数改写
============  ==============================================  ==================

约定：

- 事件名 ``namespace/action``（如 ``tool/pre``）。``validate_event_name`` 提供校验，
  但**不强制**——存量 ``PreToolUse`` 等旧名在 R79 之前的迁移期照常可用。
- 排序：``priority`` 降序，同优先级按注册顺序；``on`` 返回撤销函数。
- ``bail`` / ``serial`` / ``waterfall`` 支持 ``timeout``，超时抛 :class:`EventTimeoutError`。
  一个卡死的监听器不允许拖垮整条工具链。
- ``emit`` 的异常**聚合后统一抛出**（:class:`EventDispatchError`）：一个坏监听器
  不会饿死其余监听器，但也不会被静默吞掉。
- ``waterfall`` 的监听器若**不调用** ``next``，则该返回值短路整条链——与 Cordis
  一致，是刻意保留的拦截语义。

已知差异（不假装等价）：Python 无 ``undefined``，``None`` 同时承担 null 与 undefined；
``bail``/``serial`` 在 Python 侧统一为 async（JS 侧 bail 可同步）。
"""

from __future__ import annotations

import asyncio
import inspect
import re
from typing import Any, Callable, Dict, List, Optional

from backend.application.kernel.effects import KernelError

EventHandler = Callable[..., Any]

_SEGMENT = r"[A-Za-z0-9_][A-Za-z0-9_.-]*"
_EVENT_NAME_RE = re.compile(rf"^{_SEGMENT}(/{_SEGMENT})*$")


class EventError(KernelError):
    """事件总线错误基类。"""


class EventNameError(EventError):
    """事件名非法。"""


class EventDispatchError(EventError):
    """``emit`` 期间至少一个监听器抛错（其余监听器已执行完毕）。"""

    def __init__(self, name: str, errors: List[BaseException]) -> None:
        self.name = name
        self.errors = list(errors)
        preview = "; ".join(f"{type(e).__name__}: {e}" for e in self.errors[:3])
        super().__init__(
            f"事件 {name!r} 派发时出现 {len(self.errors)} 个错误: {preview}"
        )


class EventTimeoutError(EventError):
    """监听链超时。"""

    def __init__(self, name: str, timeout: float) -> None:
        self.name = name
        self.timeout = timeout
        super().__init__(f"事件 {name!r} 在 {timeout:.3f}s 内未完成")


def validate_event_name(name: str) -> str:
    """校验事件名（``namespace/action`` 或单段名），返回原值。"""
    if not isinstance(name, str) or not name:
        raise EventNameError("事件名必须是非空字符串")
    if not _EVENT_NAME_RE.match(name):
        raise EventNameError(f"事件名非法: {name!r}（期望 namespace/action）")
    return name


class _Subscription:
    """一条监听注册（priority 越大越先执行，同优先级按注册顺序）。"""

    __slots__ = ("handler", "priority", "seq")

    def __init__(self, handler: EventHandler, priority: int, seq: int) -> None:
        self.handler = handler
        self.priority = priority
        self.seq = seq

    def sort_key(self) -> Any:
        return (-self.priority, self.seq)


class EventBus:
    """实现 :class:`backend.ports.plugin.EventBusPort` 的内存事件总线。"""

    __slots__ = ("_handlers", "_seq")

    def __init__(self) -> None:
        self._handlers: Dict[str, List[_Subscription]] = {}
        self._seq = 0

    # ------------------------------------------------------------------ #
    # 注册 / 撤销
    # ------------------------------------------------------------------ #

    def on(self, name: str, handler: EventHandler, priority: int = 0) -> Callable[[], None]:
        """注册监听器，返回撤销函数（可交给 ``EffectScope.add``）。"""
        validate_event_name(name)
        if not callable(handler):
            raise TypeError("handler 必须可调用")
        self._seq += 1
        sub = _Subscription(handler, int(priority), self._seq)
        self._handlers.setdefault(name, []).append(sub)

        def _off() -> None:
            bucket = self._handlers.get(name)
            if not bucket:
                return
            try:
                bucket.remove(sub)
            except ValueError:
                return
            if not bucket:
                self._handlers.pop(name, None)

        return _off

    def off(self, name: str, handler: EventHandler) -> int:
        """按函数对象移除监听器，返回移除数量。"""
        bucket = list(self._handlers.get(name, ()))
        removed = 0
        for sub in bucket:
            if sub.handler is handler:
                self._handlers[name].remove(sub)
                removed += 1
        if name in self._handlers and not self._handlers[name]:
            self._handlers.pop(name, None)
        return removed

    def handler_count(self, name: str) -> int:
        """某事件上的监听器数量（诊断/断言用）。"""
        return len(self._handlers.get(name, ()))

    def event_names(self) -> List[str]:
        """已注册监听的稳定排序事件名列表。"""
        return sorted(self._handlers)

    def clear(self) -> None:
        """清空全部监听（仅测试/关停路径使用）。"""
        self._handlers.clear()

    # ------------------------------------------------------------------ #
    # 派发
    # ------------------------------------------------------------------ #

    def _ordered(self, name: str) -> List[EventHandler]:
        subs = self._handlers.get(name)
        if not subs:
            return []
        return [s.handler for s in sorted(subs, key=_Subscription.sort_key)]

    def emit(self, name: str, *args: Any) -> None:
        """同步广播，忽略返回值；异常聚合后抛 :class:`EventDispatchError`。

        异步 handler 不支持 ``emit``（会记录 ``TypeError`` 并关闭协程），
        需要 await 的场合请用 ``serial`` / ``waterfall``。
        """
        errors: List[BaseException] = []
        for handler in self._ordered(name):
            try:
                result = handler(*args)
            except BaseException as exc:  # noqa: BLE001 - 聚合后统一抛出
                errors.append(exc)
                continue
            if result is not None and inspect.isawaitable(result):
                _close_awaitable(result)
                errors.append(
                    TypeError(
                        "emit 只支持同步 handler；异步 handler 请改用 serial/waterfall"
                    )
                )
        if errors:
            raise EventDispatchError(name, errors)

    async def bail(
        self,
        name: str,
        *args: Any,
        default: Any = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """顺序执行，首个非 ``None`` / ``False`` 返回值即结果。"""
        handlers = self._ordered(name)
        if not handlers:
            return default

        async def _run() -> Any:
            for handler in handlers:
                value = handler(*args)
                if inspect.isawaitable(value):
                    value = await value
                if value is not None and value is not False:
                    return value
            return default

        return await self._with_timeout(name, _run(), timeout)

    async def serial(
        self,
        name: str,
        *args: Any,
        default: Any = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """``bail`` 的异步语义别名（首个有效返回值终止链）。

        保留两个名字是为了与 Cordis 的 ABI 一一对应：JS 侧 bail 不 await，
        Python 侧两者都必须 await，行为以本方法为准。
        """
        return await self.bail(name, *args, default=default, timeout=timeout)

    async def waterfall(
        self,
        name: str,
        *args: Any,
        initial: Any = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """中间件链：每个监听器形如 ``handler(*args, next)``。

        监听器必须 ``await next()``（或调用 ``next()`` 拿到下游结果）才能继续；
        不调用则其返回值即最终结果（刻意的短路能力）。
        """
        handlers = self._ordered(name)

        async def _call(index: int) -> Any:
            if index >= len(handlers):
                return initial

            async def _next() -> Any:
                return await _call(index + 1)

            value = handlers[index](*args, _next)
            if inspect.isawaitable(value):
                value = await value
            return value

        return await self._with_timeout(name, _call(0), timeout)

    @staticmethod
    async def _with_timeout(name: str, coro: Any, timeout: Optional[float]) -> Any:
        if timeout is None:
            return await coro
        try:
            return await asyncio.wait_for(coro, timeout)
        # py3.8(win7 线) 下 asyncio.TimeoutError 与内建 TimeoutError 不是同一个类，
        # 必须保留 asyncio 别名，因此不采纳 UP041。
        except asyncio.TimeoutError as exc:  # noqa: UP041
            raise EventTimeoutError(name, timeout) from exc


def _close_awaitable(value: Any) -> None:
    """关闭未被 await 的协程，避免 ``RuntimeWarning`` 噪音。"""
    close = getattr(value, "close", None)
    if callable(close):
        close()


__all__ = [
    "EventBus",
    "EventDispatchError",
    "EventError",
    "EventNameError",
    "EventHandler",
    "EventTimeoutError",
    "validate_event_name",
]
