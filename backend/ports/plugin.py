# ruff: noqa: UP006, UP007, UP035, UP045
"""插件内核端口（Protocol 契约）。

应用层只依赖这里的抽象，具体实现由 ``backend.application.kernel`` 提供，
未来可由 ``backend.adapters.out.plugin`` 替换为进程外实现（R83）。

约定：

- 所有 ``disposer`` 都是无参可调用对象，返回 ``None`` 或可 await 的协程；
- 端口只定义签名，不定义异常类型（异常语义由实现模块给出）；
- 与 Cordis 的差异：Python 无 ``undefined``，``None`` 同时承担 null/undefined 语义。
"""

from __future__ import annotations

from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Protocol,
    Union,
    runtime_checkable,
)

from backend.domain.plugin import FiberState

# 释放器：同步返回 None，或返回可 await 对象（由内核调度）。
Disposer = Callable[[], Union[None, Awaitable[None]]]

# 事件处理函数：同步或异步皆可；waterfall 形态额外接收 ``next`` 回调。
EventHandler = Callable[..., Any]

# 服务可用性变更回调：``(service_name, present)``。
ServiceChangeCallback = Callable[[str, bool], None]


@runtime_checkable
class EffectScopePort(Protocol):
    """作用域化的可逆副作用集合。"""

    @property
    def label(self) -> str:
        """作用域标签（用于诊断日志）。"""
        ...

    @property
    def disposed(self) -> bool:
        """是否已释放。"""
        ...

    def effect(self, factory: Callable[[], Disposer]) -> Disposer:
        """执行 ``factory`` 拿到释放器并登记；已释放的 scope 上调用即抛错。"""
        ...

    def add(self, disposer: Disposer) -> Disposer:
        """直接登记一个已构造好的释放器。"""
        ...

    def child(self, label: str = "") -> EffectScopePort:
        """创建子作用域；父级释放时先释放子级。"""
        ...

    async def dispose(self) -> None:
        """逆序释放全部副作用（异步释放器并发执行），幂等。"""
        ...


@runtime_checkable
class ServiceRegistryPort(Protocol):
    """命名服务注册表：插件之间互相提供/消费能力的最小单位。"""

    def provide(self, name: str, instance: Any, owner: str = "") -> Disposer:
        """登记一个命名服务；同名冲突抛错。"""
        ...

    def get(self, name: str) -> Optional[Any]:
        """取服务实例，不存在返回 ``None``。"""
        ...

    def require(self, name: str) -> Any:
        """取服务实例，不存在抛错。"""
        ...

    def names(self) -> List[str]:
        """当前已提供的服务名（稳定排序）。"""
        ...

    def on_change(self, callback: ServiceChangeCallback) -> Disposer:
        """订阅服务增减通知。"""
        ...


@runtime_checkable
class EventBusPort(Protocol):
    """四模式事件总线（emit / bail / serial / waterfall）。"""

    def on(self, name: str, handler: EventHandler, priority: int = 0) -> Disposer:
        """注册监听器，返回撤销函数。"""
        ...

    def emit(self, name: str, *args: Any) -> None:
        """同步广播，忽略返回值。"""
        ...

    async def bail(
        self,
        name: str,
        *args: Any,
        default: Any = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """顺序执行，首个非 ``None``/``False`` 返回值即结果（守卫/拦截）。"""
        ...

    async def serial(
        self,
        name: str,
        *args: Any,
        default: Any = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """顺序 await，首个有效返回值终止链（多级审批）。"""
        ...

    async def waterfall(
        self,
        name: str,
        *args: Any,
        initial: Any = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """中间件链：每个监听器包装下游结果，必须消费 ``next``。"""
        ...


@runtime_checkable
class FiberPort(Protocol):
    """单个插件实例的运行时句柄。"""

    @property
    def plugin_id(self) -> str:
        ...

    @property
    def state(self) -> FiberState:
        ...

    @property
    def error(self) -> Optional[BaseException]:
        ...

    async def start(self) -> None:
        """依赖就绪则加载，否则停在 PENDING。"""
        ...

    async def dispose(self) -> None:
        """卸载并回收全部注册。"""
        ...

    async def refresh(self) -> None:
        """按当前服务可用性对齐状态（消失则卸载，恢复则重载）。"""
        ...


@runtime_checkable
class PluginHostPort(Protocol):
    """插件宿主：装载、卸载、状态查询。"""

    def load(
        self,
        plugin_id: str,
        apply: Callable[..., Any],
        inject: Optional[List[str]] = None,
    ) -> FiberPort:
        """装载一个插件定义，返回未启动的 fiber。"""
        ...

    def get(self, plugin_id: str) -> Optional[FiberPort]:
        """按 id 取 fiber。"""
        ...

    async def unload(self, plugin_id: str) -> None:
        """卸载并移除。"""
        ...

    def states(self) -> Dict[str, FiberState]:
        """全部插件的状态快照。"""
        ...

    async def shutdown(self) -> None:
        """卸载全部插件。"""
        ...


__all__ = [
    "Disposer",
    "EffectScopePort",
    "EventHandler",
    "EventBusPort",
    "FiberPort",
    "PluginHostPort",
    "ServiceChangeCallback",
    "ServiceRegistryPort",
]
