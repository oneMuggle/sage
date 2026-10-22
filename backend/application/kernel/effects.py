# ruff: noqa: UP006, UP007, UP035, UP045
"""可逆副作用作用域（EffectScope）。

插件系统真正的难点不是加载，而是**卸载**：插件在运行期注册的监听器、定时器、
连接、缓存，必须在卸载时**一个不剩**地回收。``EffectScope`` 把这些注册统一成
"释放器"，并在 scope 释放时逆序回收。

语义（对齐 Cordis ``ctx.effect``）：

1. **逆序释放**——后注册的先释放；子作用域整体先于父作用域释放。
2. **异步并发**——同步释放器按逆序立即执行；异步释放器收集后 ``asyncio.gather``
   并发执行（Cordis 文档明确：多个异步 disposer 并发、不保证逐个完成）。
   若清理之间有顺序依赖，应放进**同一个**释放器内部串行等待。
3. **已释放即拒绝**——在已释放 / 正在释放的 scope 上注册副作用立即抛
   :class:`ScopeDisposedError`；这是杜绝"插件在异步回调里注册、而它已被卸载"的关键。
4. **幂等**——重复调用 ``dispose()`` 只执行一次。
5. **异常不吞**——单个释放器抛错不阻断其余释放器，最终统一抛
   :class:`EffectDisposalError` 汇总全部错误。

本模块只依赖标准库，不含业务判断。
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Awaitable, Callable, List, Union

Disposer = Callable[[], Union[None, Awaitable[None]]]


class KernelError(RuntimeError):
    """内核错误基类。"""


class ScopeDisposedError(KernelError):
    """在已释放的作用域上注册副作用。"""


class EffectDisposalError(KernelError):
    """释放过程中至少一个释放器抛错（其余释放器仍已执行）。"""

    def __init__(self, label: str, errors: List[BaseException]) -> None:
        self.label = label
        self.errors = list(errors)
        preview = "; ".join(f"{type(e).__name__}: {e}" for e in self.errors[:3])
        super().__init__(
            f"作用域 {label!r} 释放时出现 {len(self.errors)} 个错误: {preview}"
        )


class EffectScope:
    """可逆副作用集合，实现 :class:`backend.ports.plugin.EffectScopePort`。"""

    __slots__ = ("_label", "_disposers", "_children", "_disposed", "_disposing")

    def __init__(self, label: str = "") -> None:
        self._label = label
        self._disposers: List[Disposer] = []
        self._children: List[EffectScope] = []
        self._disposed = False
        self._disposing = False

    # ------------------------------------------------------------------ #
    # 只读属性
    # ------------------------------------------------------------------ #

    @property
    def label(self) -> str:
        return self._label

    @property
    def disposed(self) -> bool:
        return self._disposed

    @property
    def size(self) -> int:
        """当前登记的副作用数量（含子作用域，用于诊断/断言）。"""
        return len(self._disposers) + len(self._children)

    # ------------------------------------------------------------------ #
    # 注册
    # ------------------------------------------------------------------ #

    def effect(self, factory: Callable[[], Disposer]) -> Disposer:
        """执行 ``factory`` 并登记其返回的释放器。

        ``factory`` 负责"建立资源并返回如何销毁它"，等价于：:

            scope.effect(lambda: make_conn_and_return_close)

        已释放 / 正在释放时抛 :class:`ScopeDisposedError`。
        """
        self._assert_active()
        if not callable(factory):
            raise TypeError("effect() 需要可调用的 factory")
        disposer = factory()
        return self.add(disposer)

    def add(self, disposer: Disposer) -> Disposer:
        """登记一个已构造好的释放器。"""
        self._assert_active()
        if disposer is None or not callable(disposer):
            raise TypeError("effect factory 必须返回可调用的释放器")
        self._disposers.append(disposer)
        return disposer

    def child(self, label: str = "") -> EffectScope:
        """创建子作用域；父级释放时子级先释放。"""
        self._assert_active()
        child = EffectScope(label=label or self._label)
        self._children.append(child)
        return child

    def _assert_active(self) -> None:
        if self._disposed or self._disposing:
            raise ScopeDisposedError(f"作用域 {self._label!r} 已释放，禁止再注册副作用")

    # ------------------------------------------------------------------ #
    # 释放
    # ------------------------------------------------------------------ #

    async def dispose(self) -> None:
        """逆序释放全部副作用；幂等；异常聚合后统一抛出。"""
        if self._disposed or self._disposing:
            return
        self._disposing = True
        errors: List[BaseException] = []
        try:
            # 1) 子作用域先释放（逆序）
            for child in reversed(self._children):
                try:
                    await child.dispose()
                except BaseException as exc:  # noqa: BLE001 - 汇总后统一抛出
                    errors.append(exc)

            # 2) 本作用域释放器：同步立即按逆序执行，异步收集后并发执行
            pending: List[Awaitable[Any]] = []
            for disposer in reversed(self._disposers):
                try:
                    result = disposer()
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)
                    continue
                if result is not None and inspect.isawaitable(result):
                    pending.append(result)

            if pending:
                results = await asyncio.gather(*pending, return_exceptions=True)
                errors.extend(r for r in results if isinstance(r, BaseException))
        finally:
            self._disposers.clear()
            self._children.clear()
            self._disposing = False
            self._disposed = True

        if errors:
            raise EffectDisposalError(self._label, errors)

    async def __aenter__(self) -> EffectScope:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.dispose()


__all__ = [
    "Disposer",
    "EffectDisposalError",
    "EffectScope",
    "KernelError",
    "ScopeDisposedError",
]
