# ruff: noqa: UP006, UP007, UP035, UP045
"""Hook 生命周期收编到插件内核（R79）。

**为什么放在 ``backend/hooks`` 而不是内核里**：内核只负责"挂载 / 依赖 / 服务 / 事件"
四件事（见 ``docs/plans/2026-10-21_plugin-kernel-r78.md`` §3 D1）。hooks 是**消费者**，
由它反向适配内核；一旦让内核 import hooks，内核就会长成第二个巨石。

本轮解决三件事：

1. **生命周期归属**——钩子列表不再由每个调用点自行 ``load_hooks()`` 拼装，而是由
   :class:`KernelHookProvider` 装载成一个内核插件：装载即可逆，卸载即整体撤销，
   热替换（``reload``）不会残留旧钩子。
2. **可观测的"当前生效钩子"**——``active_hooks()`` 是唯一事实源，替代 14 处调用点
   各自的临时变量。
3. **零语义变更**——执行仍委托给 ``backend.hooks.runner.run_event_hooks``，deny 短路、
   modify 首个生效、feedback 聚合、fail-open 全部沿用。内核路径与旧路径的**行为等价**
   由 ``test_hooks_kernel_provider.py::TestParity`` 逐字段断言。

迁移策略：调用点只需把「``load_hooks()`` + ``run_event_hooks()``」换成
:func:`fire_hooks`，由 ``SAGE_KERNEL_HOOKS`` 开关决定走内核还是旧路径（默认旧路径）。
本轮**不改任何调用点**，避免与正在进行的 ``legacy_routes`` 拆分互相踩踏。
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Callable, Dict, List, Optional, Sequence

from backend.application.kernel.effects import Disposer
from backend.application.kernel.fiber import Fiber, PluginHost
from backend.hooks.config import HookConfig
from backend.hooks.runner import (
    DECISION_ALLOW,
    DECISION_NOOP,
    HookOutcome,
    run_event_hooks,
)

logger = logging.getLogger(__name__)

#: 环境开关：置 ``1`` / ``true`` 时 :func:`fire_hooks` 走内核路径；默认旧路径。
KERNEL_HOOKS_ENV = "SAGE_KERNEL_HOOKS"

#: 内核中代表"钩子集合"的插件 id 与服务名。
DEFAULT_PLUGIN_ID = "core-hooks"
HOOKS_SERVICE_NAME = "hooks"


def kernel_hooks_enabled() -> bool:
    """内核钩子路径是否启用（默认关闭，保证零行为变更）。"""
    raw = os.environ.get(KERNEL_HOOKS_ENV, "")
    return raw.strip().lower() in ("1", "true", "yes", "on")


class KernelHookProvider:
    """把一组 :class:`HookConfig` 装载为可逆的内核插件。

    典型用法::

        host = PluginHost()
        provider = KernelHookProvider(host)
        await provider.start(merge_hooks(project, user))
        outcome = await provider.dispatch("pre_tool_use", "bash", payload)
        await provider.shutdown()        # 钩子随之全部撤销

    语义约定：

    - 未装载 / 已卸载时 ``active_hooks()`` 为空，``dispatch`` 恒返回
      ``DECISION_ALLOW``（与"旧路径传入空列表"完全一致，便于对照）；
    - ``start`` 幂等：重复调用会先卸载再装载；
    - ``reload`` = 卸载 + 装载，用于配置热更新；
    - 装载期间把自身注册成命名服务 ``hooks``，其他组件经 ``ctx.get("hooks")`` 查询，
      卸载时该服务一并撤销（这就是 R78 的 EffectScope 在起作用）。
    """

    def __init__(
        self,
        host: Optional[PluginHost] = None,
        plugin_id: str = DEFAULT_PLUGIN_ID,
    ) -> None:
        self._host = host if host is not None else PluginHost()
        self._plugin_id = plugin_id
        self._hooks: List[HookConfig] = []
        self._fiber: Optional[Fiber] = None

    # ------------------------------------------------------------------ #
    # 只读视图
    # ------------------------------------------------------------------ #

    @property
    def host(self) -> PluginHost:
        return self._host

    @property
    def plugin_id(self) -> str:
        return self._plugin_id

    @property
    def fiber(self) -> Optional[Fiber]:
        return self._fiber

    @property
    def running(self) -> bool:
        """插件是否处于 ACTIVE（装载且依赖就绪）。"""
        return self._fiber is not None and self._fiber.state.value == "active"

    def active_hooks(self) -> List[HookConfig]:
        """当前生效的钩子（未装载时为空列表）。"""
        return list(self._hooks) if self.running else []

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #

    async def start(self, hooks: Sequence[HookConfig]) -> Fiber:
        """装载钩子集合；已装载则先卸载（热替换语义）。"""
        if self._fiber is not None:
            await self.stop()
        self._hooks = list(hooks)
        fiber = self._host.load(self._plugin_id, self._apply)
        self._fiber = fiber
        await fiber.start()
        return fiber

    async def reload(self, hooks: Sequence[HookConfig]) -> Fiber:
        """热替换钩子集合（等价于 ``start``，语义更明确）。"""
        return await self.start(hooks)

    async def stop(self) -> None:
        """卸载：撤销服务注册与全部副作用。"""
        fiber, self._fiber = self._fiber, None
        if fiber is None:
            return
        try:
            await self._host.unload(self._plugin_id)
        except Exception as exc:  # noqa: BLE001 - 卸载失败不应炸调用方
            logger.warning("hooks: 内核钩子卸载失败（已尽力回收）: %s", exc)

    async def shutdown(self) -> None:
        """宿主级关停（连同宿主里其他插件）。"""
        await self._host.shutdown()
        self._fiber = None

    def _apply(self, ctx: Any) -> None:
        """插件 apply：把"钩子集合"暴露为命名服务，并登记可逆副作用。"""
        # 服务注册本身就是可逆副作用；卸载时自动撤销。
        release: Disposer = ctx.services.provide(
            HOOKS_SERVICE_NAME, self, owner=self._plugin_id
        )
        ctx.effect(lambda: release)
        ctx.emit("hooks/loaded", len(self._hooks))

    # ------------------------------------------------------------------ #
    # 派发
    # ------------------------------------------------------------------ #

    async def dispatch(
        self,
        event: str,
        tool_name: str,
        payload: Dict[str, Any],
    ) -> HookOutcome:
        """异步派发一个事件（语义完全等价于 ``run_event_hooks``）。"""
        hooks = self.active_hooks()
        if not hooks:
            return HookOutcome(decision=DECISION_ALLOW)
        return await run_event_hooks(hooks, event, tool_name, payload)

    def dispatch_sync(
        self,
        event: str,
        tool_name: str,
        payload: Dict[str, Any],
    ) -> HookOutcome:
        """同步派发（线程内无运行循环时新建循环，否则 fail-open，与旧路径一致）。"""
        hooks = self.active_hooks()
        if not hooks:
            return HookOutcome(decision=DECISION_ALLOW)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            try:
                return asyncio.run(run_event_hooks(hooks, event, tool_name, payload))
            except Exception as exc:  # noqa: BLE001 - fail-open
                logger.warning("hooks: 内核同步派发失败（fail-open）: %s", exc)
                return HookOutcome(
                    decision=DECISION_NOOP, reason=f"kernel sync dispatch error: {exc}"
                )
        logger.debug("hooks: 内核同步派发跳过 —— 事件循环已在运行（fail-open）")
        return HookOutcome(decision=DECISION_NOOP, reason="event loop running")


HooksLoader = Callable[[], List[HookConfig]]


async def fire_hooks(
    event: str,
    tool_name: str,
    payload: Dict[str, Any],
    *,
    hooks_loader: HooksLoader,
    provider: Optional[KernelHookProvider] = None,
) -> HookOutcome:
    """统一触发入口（供调用点迁移用）。

    - ``SAGE_KERNEL_HOOKS`` 关闭（默认）或未提供 provider → 旧路径：
      ``run_event_hooks(hooks_loader(), ...)``，**逐字节等价于今天的调用点**；
    - 开启且提供 provider → 内核路径：``provider.dispatch(...)``。

    两条路径的等价性由对照测试保证；开关默认关闭，因此迁移调用点不会改变行为。
    """
    if provider is not None and kernel_hooks_enabled():
        return await provider.dispatch(event, tool_name, payload)
    return await run_event_hooks(hooks_loader(), event, tool_name, payload)


__all__ = [
    "DEFAULT_PLUGIN_ID",
    "HOOKS_SERVICE_NAME",
    "KERNEL_HOOKS_ENV",
    "HooksLoader",
    "KernelHookProvider",
    "fire_hooks",
    "kernel_hooks_enabled",
]
