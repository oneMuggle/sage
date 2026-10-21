# ruff: noqa: UP006, UP007, UP035, UP045
"""命名服务注册表（ServiceRegistry）。

对应 Cordis 的 ``ctx.tools`` / ``ctx.llm`` / ``ctx.metrics``：插件把自己提供的
能力以**稳定的名字**挂到上下文上，其他插件通过 ``inject`` 声明依赖。

三条纪律：

1. **同名冲突显式抛错**——不允许静默覆盖（覆盖会让"谁在提供"变得不可追溯）。
2. **注册即可逆**——``provide`` 返回释放器，可直接交给 ``EffectScope.add``；
   释放器只移除"自己那一个实例"，避免误删后续提供者的同名服务。
3. **变更可订阅**——``on_change`` 是 Fiber 依赖驱动重载的基础：服务消失则
   依赖方卸载，服务恢复则依赖方重新加载。

本模块不持有业务逻辑，也不做类型反射（纯名字 + duck typing）。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from backend.application.kernel.effects import KernelError
from backend.domain.plugin import validate_capability_name

ServiceChangeCallback = Callable[[str, bool], None]


class ServiceError(KernelError):
    """服务注册表错误基类。"""


class ServiceConflictError(ServiceError):
    """同名服务已存在。"""

    def __init__(self, name: str, existing_owner: str, new_owner: str) -> None:
        self.name = name
        self.existing_owner = existing_owner
        self.new_owner = new_owner
        super().__init__(
            "服务 {!r} 已被 {!r} 占用，无法由 {!r} 重复提供".format(
                name, existing_owner or "<unknown>", new_owner or "<unknown>"
            )
        )


class ServiceNotFoundError(ServiceError):
    """必需服务不存在。"""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"必需服务 {name!r} 尚未提供")


class ServiceRegistry:
    """实现 :class:`backend.ports.plugin.ServiceRegistryPort` 的内存注册表。"""

    __slots__ = ("_services", "_owners", "_listeners")

    def __init__(self) -> None:
        self._services: Dict[str, Any] = {}
        self._owners: Dict[str, str] = {}
        self._listeners: List[ServiceChangeCallback] = []

    # ------------------------------------------------------------------ #
    # 提供 / 撤销
    # ------------------------------------------------------------------ #

    def provide(self, name: str, instance: Any, owner: str = "") -> Callable[[], None]:
        """登记命名服务并返回释放器；同名冲突抛 :class:`ServiceConflictError`。"""
        validate_capability_name(name)
        if instance is None:
            raise ServiceError(f"服务 {name!r} 的实例不能为 None")
        if name in self._services:
            raise ServiceConflictError(name, self._owners.get(name, ""), owner)

        self._services[name] = instance
        self._owners[name] = owner
        self._notify(name, True)

        def _release() -> None:
            # 只移除"自己提供的那一个"，避免误删后来者的同名服务。
            if self._services.get(name) is instance:
                self._services.pop(name, None)
                self._owners.pop(name, None)
                self._notify(name, False)

        return _release

    def replace(self, name: str, instance: Any, owner: str = "") -> Callable[[], None]:
        """显式覆盖同名服务（热替换场景），返回释放器。

        与 ``provide`` 的差别：允许已存在，等价于"先撤销旧的再挂新的"。
        """
        validate_capability_name(name)
        if instance is None:
            raise ServiceError(f"服务 {name!r} 的实例不能为 None")
        previous = self._services.get(name)
        previous_owner = self._owners.get(name, "")
        self._services[name] = instance
        self._owners[name] = owner
        self._notify(name, True)

        def _release() -> None:
            if self._services.get(name) is not instance:
                return
            if previous is not None:
                self._services[name] = previous
                self._owners[name] = previous_owner
                self._notify(name, True)
            else:
                self._services.pop(name, None)
                self._owners.pop(name, None)
                self._notify(name, False)

        return _release

    # ------------------------------------------------------------------ #
    # 读取
    # ------------------------------------------------------------------ #

    def get(self, name: str) -> Optional[Any]:
        """取服务实例，不存在返回 ``None``（可选依赖用）。"""
        return self._services.get(name)

    def require(self, name: str) -> Any:
        """取服务实例，不存在抛 :class:`ServiceNotFoundError`（必需依赖用）。"""
        if name not in self._services:
            raise ServiceNotFoundError(name)
        return self._services[name]

    def has(self, name: str) -> bool:
        """服务是否存在。"""
        return name in self._services

    def names(self) -> List[str]:
        """已提供的服务名（稳定排序）。"""
        return sorted(self._services)

    def owner_of(self, name: str) -> Optional[str]:
        """服务提供者标识（插件 id），供诊断使用。"""
        return self._owners.get(name)

    def snapshot(self) -> Dict[str, str]:
        """``{服务名: 提供者}`` 快照，供状态面板/日志使用。"""
        return {name: self._owners.get(name, "") for name in sorted(self._services)}

    def missing(self, required: List[str]) -> List[str]:
        """返回 ``required`` 中尚未提供的服务名（保持输入顺序）。"""
        return [name for name in required if name not in self._services]

    # ------------------------------------------------------------------ #
    # 变更订阅
    # ------------------------------------------------------------------ #

    def on_change(self, callback: ServiceChangeCallback) -> Callable[[], None]:
        """订阅服务增减通知，返回退订函数。"""
        if not callable(callback):
            raise TypeError("callback 必须可调用")
        self._listeners.append(callback)

        def _off() -> None:
            try:
                self._listeners.remove(callback)
            except ValueError:
                return

        return _off

    def _notify(self, name: str, present: bool) -> None:
        # 监听器异常不应破坏注册表的原子性：逐个隔离，不让一个坏订阅者
        # 影响其他订阅者与当前注册操作。
        for callback in list(self._listeners):
            try:
                callback(name, present)
            except BaseException:  # noqa: BLE001 - 订阅者故障隔离
                continue

    def clear(self) -> None:
        """清空全部服务（仅测试/关停路径使用）。"""
        names = list(self._services)
        self._services.clear()
        self._owners.clear()
        for name in names:
            self._notify(name, False)


__all__ = [
    "ServiceConflictError",
    "ServiceError",
    "ServiceNotFoundError",
    "ServiceRegistry",
]
