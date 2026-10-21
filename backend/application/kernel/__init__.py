# ruff: noqa: UP006, UP007, UP035, UP045
"""插件内核（R78 骨架）。

对外只暴露四件东西：

- :class:`~backend.application.kernel.effects.EffectScope` —— 可逆副作用作用域
- :class:`~backend.application.kernel.events.EventBus` —— 四模式事件总线
- :class:`~backend.application.kernel.services.ServiceRegistry` —— 命名服务注册表
- :class:`~backend.application.kernel.fiber.PluginHost` —— 插件宿主与状态机

本轮**不接线**：现有 hooks / tools / skills 仍走原路径，内核只被测试引用。
接线顺序见 ``docs/plans/2026-10-21_plugin-kernel-r78.md`` §9（R79 hooks → R80 tools）。
"""

from __future__ import annotations

from backend.application.kernel.effects import (
    Disposer,
    EffectDisposalError,
    EffectScope,
    KernelError,
    ScopeDisposedError,
)
from backend.application.kernel.events import (
    EventBus,
    EventDispatchError,
    EventError,
    EventNameError,
    EventTimeoutError,
    validate_event_name,
)
from backend.application.kernel.fiber import (
    Fiber,
    FiberContext,
    FiberError,
    FiberStateError,
    PluginHost,
)
from backend.application.kernel.services import (
    ServiceConflictError,
    ServiceError,
    ServiceNotFoundError,
    ServiceRegistry,
)

__all__ = [
    "Disposer",
    "EffectDisposalError",
    "EffectScope",
    "EventBus",
    "EventDispatchError",
    "EventError",
    "EventNameError",
    "EventTimeoutError",
    "Fiber",
    "FiberContext",
    "FiberError",
    "FiberStateError",
    "KernelError",
    "PluginHost",
    "ScopeDisposedError",
    "ServiceConflictError",
    "ServiceError",
    "ServiceNotFoundError",
    "ServiceRegistry",
    "validate_event_name",
]
