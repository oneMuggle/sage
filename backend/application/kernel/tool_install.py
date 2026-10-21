# ruff: noqa: UP006, UP007, UP035
"""工具装配机制：平铺 register 收编为具名 bundle（R80）。

本模块**只做编排**，不认识任何具体工具 —— 具体清单在
``backend/tools/tool_bundles.py`` 声明。依赖方向
``backend.tools`` → ``backend.application.kernel``，与 R79 的
``backend.hooks`` → ``backend.application.kernel`` 一致：内核不认识 tools。

四条契约：

1. **顺序保真**：按 ``bundles`` 声明顺序安装，bundle 内按函数体顺序。
   「声明顺序 = 注册顺序」因此是可直接断言的属性，而不是口头约定。
2. **能力门控**：``requires`` 里的能力键任一为假则整包跳过 —— 取代原先
   散落在装配体里的 ``if network_policy.search_enabled():`` 分支。
3. **失败策略**：默认 ``strict=True``，首个异常向上抛（等价旧实现的
   "崩就崩"）；``critical=False`` 的 bundle 无论 ``strict`` 与否都只记录，
   对应旧实现里 MCP 注册那圈 ``try/except``。
4. **报告可核对**：``installed`` 取自注册前后 ``list_names()`` 的差集，
   反映真实落库结果；拼错类名 / 忘写 register 都会被它戳穿。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Sequence, Tuple

logger = logging.getLogger(__name__)

#: 环境开关：置 ``1`` / ``true`` 时 ``register_all_tools`` 走 bundle 路径。
#: 默认关闭 —— 与 R79 的 ``SAGE_KERNEL_HOOKS`` 同一策略，保证生产路径零变更。
TOOL_BUNDLES_ENV = "SAGE_KERNEL_TOOL_BUNDLES"

_TRUTHY = ("1", "true", "yes", "on")


def tool_bundles_enabled() -> bool:
    """bundle 装配路径是否启用（默认关闭）。"""
    raw = os.environ.get(TOOL_BUNDLES_ENV, "")
    return raw.strip().lower() in _TRUTHY


@dataclass(frozen=True)
class ToolBundle:
    """一组工具及其安装函数。

    Attributes:
        name:     具名 bundle，出现在 :class:`InstallReport` 与日志里。
        install:  安装函数，接收 :class:`ToolInstallContext`，向 registry 注册。
        requires: 能力键集合（如 ``("network.search",)``）；任一为假则整包跳过。
        critical: ``True``（默认）时失败按 ``strict`` 处理；``False`` 时只记录，
                  用于「注册不上也不该拖垮启动」的可选集成（MCP）。
    """

    name: str
    install: Callable[[ToolInstallContext], None]
    requires: Tuple[str, ...] = ()
    critical: bool = True

    def enabled(self, capabilities: Dict[str, bool]) -> bool:
        """能力齐备才算启用；``requires`` 为空恒为 ``True``。"""
        return all(capabilities.get(key, False) for key in self.requires)


@dataclass
class ToolInstallContext:
    """安装期上下文 —— 与 ``register_all_tools`` 的入参一一对应，外加能力表。"""

    registry: Any
    policy: Any = None
    network_policy: Any = None
    scheduler_service_getter: Any = None
    todo_service_getter: Any = None
    capabilities: Dict[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class InstallReport:
    """一次安装的结果快照。"""

    installed: Tuple[str, ...] = ()
    skipped: Tuple[str, ...] = ()
    failed: Tuple[Tuple[str, str], ...] = ()

    @property
    def ok(self) -> bool:
        return not self.failed


def install_bundles(
    ctx: ToolInstallContext,
    bundles: Sequence[ToolBundle],
    *,
    strict: bool = True,
) -> InstallReport:
    """按顺序安装 ``bundles``，返回安装报告。

    Args:
        ctx:     安装上下文（registry / policy / 服务 getter / 能力表）。
        bundles: 有序 bundle 序列。
        strict:  首个 critical bundle 抛异常时是否立即向上抛。

    Returns:
        :class:`InstallReport`。``strict=True`` 且抛异常时不会返回。
    """
    before = set(ctx.registry.list_names())
    skipped: List[str] = []
    failed: List[Tuple[str, str]] = []

    for bundle in bundles:
        if not bundle.enabled(ctx.capabilities):
            skipped.append(bundle.name)
            logger.debug("tool bundle %s 跳过：requires=%s", bundle.name, bundle.requires)
            continue
        try:
            bundle.install(ctx)
        except Exception as exc:  # noqa: BLE001 —— 失败策略由 strict/critical 决定
            detail = f"{type(exc).__name__}: {exc}"
            failed.append((bundle.name, detail))
            logger.warning("tool bundle %s 安装失败：%s", bundle.name, detail)
            if strict and bundle.critical:
                raise

    after = ctx.registry.list_names()
    installed = tuple(name for name in after if name not in before)
    return InstallReport(installed=installed, skipped=tuple(skipped), failed=tuple(failed))
