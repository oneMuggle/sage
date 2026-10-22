# ruff: noqa: UP006, UP007, UP035, UP045
"""插件实例的运行时（Fiber）与宿主（PluginHost）。

对应 Cordis 的 Fiber 状态机与依赖驱动加载：

    PENDING --(依赖就绪 + start)--> LOADING --> ACTIVE
                                        \\--> FAILED
    ACTIVE  --(必需服务消失)------> UNLOADING --> DISPOSED
    DISPOSED --(服务恢复 + refresh)--> LOADING --> ACTIVE

三条关键语义：

1. **依赖未就绪不执行 ``apply``**——插件声明 ``inject``，缺任一项就停在 PENDING；
   这消除了"插件初始化顺序"这类隐性耦合。
2. **服务消失即卸载、恢复即重载**——通过 ``ServiceRegistry.on_change`` 驱动，
   运行期热替换提供方不会留下半死不活的插件。
3. **子插件随父级联卸载**——``ctx.plugin(...)`` 创建的子 fiber 逆序先于父级释放。

本轮（R78）只提供运行时骨架，**不接入任何现有 hook/tool**——接线在 R79/R80。
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from backend.application.kernel.effects import Disposer, EffectScope, KernelError
from backend.application.kernel.events import EventBus, EventHandler
from backend.application.kernel.services import ServiceRegistry
from backend.domain.plugin import FiberState, validate_plugin_id

PluginApply = Callable[["FiberContext"], Union[None, Awaitable[None]]]
StateChangeCallback = Callable[[str, FiberState], None]


class FiberError(KernelError):
    """Fiber 生命周期错误基类。"""


class FiberStateError(FiberError):
    """状态机不允许的迁移（如重复装载同一 plugin_id）。"""


class FiberContext:
    """传给插件 ``apply`` 的最小上下文（对应 Cordis 的 ``ctx``）。

    只暴露四类能力：可逆副作用、事件、服务查询、子插件。
    **不暴露**文件系统 / 网络 / 子进程——那些必须经由 sage 的端口与审批闸口。
    """

    __slots__ = ("_fiber",)

    def __init__(self, fiber: Fiber) -> None:
        self._fiber = fiber

    @property
    def plugin_id(self) -> str:
        return self._fiber.plugin_id

    @property
    def state(self) -> FiberState:
        return self._fiber.state

    @property
    def services(self) -> ServiceRegistry:
        return self._fiber.services

    @property
    def events(self) -> EventBus:
        return self._fiber.events

    def effect(self, factory: Callable[[], Disposer]) -> Disposer:
        """登记可逆副作用（卸载时自动回收）。"""
        return self._fiber.scope.effect(factory)

    def on(self, name: str, handler: EventHandler, priority: int = 0) -> Disposer:
        """注册事件监听；撤销函数同时挂到副作用作用域，卸载即移除。"""
        off = self.events.on(name, handler, priority=priority)
        self._fiber.scope.add(off)
        return off

    def emit(self, name: str, *args: Any) -> None:
        """同步广播事件。"""
        self.events.emit(name, *args)

    def get(self, service: str) -> Optional[Any]:
        """可选依赖读取。"""
        return self.services.get(service)

    def require(self, service: str) -> Any:
        """必需依赖读取（缺失抛错）。"""
        return self.services.require(service)

    def plugin(
        self,
        plugin_id: str,
        apply: PluginApply,
        inject: Optional[List[str]] = None,
    ) -> Fiber:
        """装载子插件（随父级联卸载）。"""
        return self._fiber.host.load(plugin_id, apply, inject=inject, parent=self._fiber)


class Fiber:
    """单个插件实例的运行时句柄。"""

    __slots__ = (
        "_host",
        "_plugin_id",
        "_apply",
        "_inject",
        "_scope",
        "_ctx",
        "_state",
        "_error",
        "_children",
        "_detach",
        "_refreshing",
        "_auto_restart_on_failure",
    )

    def __init__(
        self,
        host: PluginHost,
        plugin_id: str,
        apply: PluginApply,
        inject: Optional[List[str]] = None,
        *,
        parent: Optional[Fiber] = None,
        auto_restart_on_failure: bool = False,
    ) -> None:
        validate_plugin_id(plugin_id)
        if not callable(apply):
            raise TypeError("apply 必须可调用")
        self._host = host
        self._plugin_id = plugin_id
        self._apply = apply
        self._inject: List[str] = list(inject or ())
        self._scope = EffectScope(label=plugin_id)
        self._ctx = FiberContext(self)
        self._state = FiberState.PENDING
        self._error: Optional[BaseException] = None
        self._children: List[Fiber] = []
        self._detach: Optional[Callable[[], None]] = None
        self._refreshing = False
        self._auto_restart_on_failure = auto_restart_on_failure
        self._detach = host.services.on_change(self._on_service_change)

    # ------------------------------------------------------------------ #
    # 只读属性
    # ------------------------------------------------------------------ #

    @property
    def plugin_id(self) -> str:
        return self._plugin_id

    @property
    def host(self) -> PluginHost:
        return self._host

    @property
    def services(self) -> ServiceRegistry:
        return self._host.services

    @property
    def events(self) -> EventBus:
        return self._host.events

    @property
    def scope(self) -> EffectScope:
        return self._scope

    @property
    def context(self) -> FiberContext:
        return self._ctx

    @property
    def state(self) -> FiberState:
        return self._state

    @property
    def error(self) -> Optional[BaseException]:
        return self._error

    @property
    def children(self) -> List[Fiber]:
        return list(self._children)

    def missing_dependencies(self) -> List[str]:
        """尚未就绪的必需服务（保持声明顺序）。"""
        return self.services.missing(self._inject)

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        """依赖就绪则执行 ``apply``；否则停在 PENDING。"""
        if self._state.is_running:
            return
        missing = self.missing_dependencies()
        if missing:
            self._set_state(FiberState.PENDING)
            return

        # 自动重载时上一次的作用域已释放，必须换一个新的，否则 ctx.effect 会抛
        # ScopeDisposedError。
        if self._scope.disposed:
            self._scope = EffectScope(label=self._plugin_id)

        self._set_state(FiberState.LOADING)
        try:
            result = self._apply(self._ctx)
            if inspect.isawaitable(result):
                await result
        except BaseException as exc:  # noqa: BLE001 - 失败要落到状态机里
            self._error = exc
            self._set_state(FiberState.FAILED)
            return

        self._error = None
        self._set_state(FiberState.ACTIVE)

    async def dispose(self) -> None:
        """卸载：子插件先释放，然后回收本作用域全部副作用。"""
        if self._state is FiberState.DISPOSED:
            return
        self._set_state(FiberState.UNLOADING)
        errors: List[BaseException] = []

        for child in reversed(self._children):
            try:
                await child.dispose()
            except BaseException as exc:  # noqa: BLE001 - 汇总
                errors.append(exc)
        self._children.clear()

        try:
            await self._scope.dispose()
        except BaseException as exc:  # noqa: BLE001 - 汇总
            errors.append(exc)

        self._set_state(FiberState.DISPOSED)
        if errors:
            raise FiberError(
                "插件 {!r} 卸载时出现 {} 个错误: {}".format(
                    self._plugin_id,
                    len(errors),
                    "; ".join(type(e).__name__ for e in errors),
                )
            )

    async def refresh(self) -> None:
        """按当前服务可用性对齐状态：消失则卸载，恢复则重新加载。"""
        if self._refreshing or self._state is FiberState.UNLOADING:
            return
        self._refreshing = True
        try:
            missing = self.missing_dependencies()
            if self._state.is_running and missing:
                await self.dispose()
                return
            if not missing and self._state is not FiberState.ACTIVE:
                if self._state is FiberState.FAILED and not self._auto_restart_on_failure:
                    return
                await self.start()
        finally:
            self._refreshing = False

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #

    def _detach_service_watch(self) -> None:
        """解除服务变更监听（宿主移除插件时调用，避免僵尸订阅）。"""
        if self._detach is not None:
            self._detach()
            self._detach = None

    def _on_service_change(self, name: str, present: bool) -> None:
        if name not in self._inject:
            return
        # on_change 是同步回调；用后台任务执行异步对齐，避免阻塞注册表操作。
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # 无事件循环（同步装配阶段）：交由显式 refresh 驱动
        loop.create_task(self.refresh())

    def _set_state(self, state: FiberState) -> None:
        if state is self._state:
            return
        self._state = state
        self._host._notify_state(self._plugin_id, state)


class PluginHost:
    """插件宿主：装载 / 卸载 / 状态查询 / 关停。"""

    __slots__ = ("_services", "_events", "_fibers", "_state_listeners")

    def __init__(
        self,
        services: Optional[ServiceRegistry] = None,
        events: Optional[EventBus] = None,
    ) -> None:
        self._services = services if services is not None else ServiceRegistry()
        self._events = events if events is not None else EventBus()
        self._fibers: Dict[str, Fiber] = {}
        self._state_listeners: List[StateChangeCallback] = []

    @property
    def services(self) -> ServiceRegistry:
        return self._services

    @property
    def events(self) -> EventBus:
        return self._events

    def load(
        self,
        plugin_id: str,
        apply: PluginApply,
        inject: Optional[List[str]] = None,
        *,
        parent: Optional[Fiber] = None,
        auto_restart_on_failure: bool = False,
    ) -> Fiber:
        """装载插件定义，返回**未启动**的 fiber（调用 ``start`` 或 ``start_all``）。"""
        validate_plugin_id(plugin_id)
        if plugin_id in self._fibers:
            raise FiberStateError(f"插件 {plugin_id!r} 已装载，不能重复 load")
        fiber = Fiber(
            host=self,
            plugin_id=plugin_id,
            apply=apply,
            inject=inject,
            parent=parent,
            auto_restart_on_failure=auto_restart_on_failure,
        )
        self._fibers[plugin_id] = fiber
        if parent is not None:
            parent._children.append(fiber)
        return fiber

    def get(self, plugin_id: str) -> Optional[Fiber]:
        """按 id 取 fiber。"""
        return self._fibers.get(plugin_id)

    async def start_all(self) -> List[str]:
        """启动全部 fiber，返回进入 FAILED 的插件 id 列表。"""
        failed: List[str] = []
        for fiber in list(self._fibers.values()):
            await fiber.start()
            if fiber.state is FiberState.FAILED:
                failed.append(fiber.plugin_id)
        return failed

    async def unload(self, plugin_id: str) -> None:
        """卸载并移除。"""
        fiber = self._fibers.pop(plugin_id, None)
        if fiber is None:
            return
        try:
            await fiber.dispose()
        finally:
            fiber._detach_service_watch()

    def states(self) -> Dict[str, FiberState]:
        """全部插件的状态快照。"""
        return {plugin_id: fiber.state for plugin_id, fiber in self._fibers.items()}

    def active_plugins(self) -> List[str]:
        """处于 ACTIVE 的插件 id（稳定排序）。"""
        return sorted(
            plugin_id for plugin_id, fiber in self._fibers.items() if fiber.state is FiberState.ACTIVE
        )

    def on_state_change(self, callback: StateChangeCallback) -> Callable[[], None]:
        """订阅 fiber 状态变更，返回退订函数。"""
        if not callable(callback):
            raise TypeError("callback 必须可调用")
        self._state_listeners.append(callback)

        def _off() -> None:
            try:
                self._state_listeners.remove(callback)
            except ValueError:
                return

        return _off

    async def shutdown(self) -> None:
        """逆序卸载全部插件（父级负责其子级）。"""
        roots = list(self._fibers.values())
        for fiber in reversed(roots):
            try:
                if fiber.state is not FiberState.DISPOSED:
                    await fiber.dispose()
            except FiberError:
                continue
            finally:
                fiber._detach_service_watch()
        self._fibers.clear()

    def _notify_state(self, plugin_id: str, state: FiberState) -> None:
        for callback in list(self._state_listeners):
            try:
                callback(plugin_id, state)
            except BaseException:  # noqa: BLE001 - 订阅者故障隔离
                continue


__all__ = [
    "Fiber",
    "FiberContext",
    "FiberError",
    "FiberStateError",
    "PluginApply",
    "PluginHost",
]
