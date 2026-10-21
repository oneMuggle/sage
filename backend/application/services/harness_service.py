"""HarnessService — harness 组件可观测性用例编排 (阶段 1)。

职责边界
--------

- **Phase 1（本模块）**：列出 / 查询 harness 组件、记录 usage 埋点。
- **Phase 2**：``update_component`` + ``harness:component_updated`` 事件
  （热替换 HMR）。

设计要点
--------

- **不依赖具体 adapter**：仅通过 ``backend.ports.harness_port.HarnessPort``
  交互；具体实现（``SqliteHarnessAdapter``）由 API 路由层注入。
- **埋点永不打断主路径**：``record_usage`` 捕获所有异常并降级为
  warning 日志——effectiveness 统计失败不应让工具/技能调用失败。
- **8 类组件白名单**：``type`` 必须是 8 类之一，非法值在 service 层
  就被拒绝（DB 的 CHECK 约束是最后一道防线）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from backend.domain.harness_component import HarnessComponent
from backend.ports.harness_port import HarnessPort

logger = logging.getLogger(__name__)

# 8 类 harness 组件（对齐 Google Harness 2）
HARNESS_COMPONENT_TYPES = (
    "system_prompt",
    "guardrails",
    "memory",
    "tool_guidance",
    "subagents",
    "skills",
    "scripts",
    "plugins",
)


class InvalidComponentTypeError(ValueError):
    """组件类型不在 8 类白名单内。"""


class HarnessService:
    """Harness 组件可观测性用例编排。"""

    def __init__(self, harness_port: HarnessPort) -> None:
        """初始化 service。

        Args:
            harness_port: harness 组件注册表端口（注入 adapter 实现）。
        """
        self._harness = harness_port

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    async def list_components(
        self,
        component_type: Optional[str] = None,
    ) -> List[HarnessComponent]:
        """列出 harness 组件。

        Args:
            component_type: 按类型过滤；``None`` 表示全部。

        Returns:
            组件列表（按 id 升序）。

        Raises:
            InvalidComponentTypeError: ``component_type`` 不在 8 类白名单内。
        """
        if component_type is not None and component_type not in HARNESS_COMPONENT_TYPES:
            raise InvalidComponentTypeError(
                f"未知组件类型: {component_type}（合法值: {', '.join(HARNESS_COMPONENT_TYPES)}）"
            )
        return await self._harness.list_components(component_type)

    async def get_component(self, component_id: str) -> Optional[HarnessComponent]:
        """按 ID 获取单个 harness 组件。"""
        return await self._harness.get_component(component_id)

    async def list_needing_improvement(self) -> List[HarnessComponent]:
        """列出效果不佳、需要改进的组件。

        判定依据见 ``HarnessComponent.needs_improvement()``：
        成功率 < 0.8 / 平均延迟 > 1000ms / 满意度 < 0.5。
        """
        components = await self._harness.list_components()
        return [c for c in components if c.needs_improvement()]

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    async def register_component(
        self,
        component_id: str,
        component_type: str,
        name: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> HarnessComponent:
        """注册 harness 组件（幂等）。

        Args:
            component_id: 组件唯一 ID。
            component_type: 8 类组件之一。
            name: 显示名称。
            config: 初始配置。

        Returns:
            注册后的组件。

        Raises:
            InvalidComponentTypeError: ``component_type`` 不在 8 类白名单内。
        """
        if component_type not in HARNESS_COMPONENT_TYPES:
            raise InvalidComponentTypeError(
                f"未知组件类型: {component_type}（合法值: {', '.join(HARNESS_COMPONENT_TYPES)}）"
            )
        return await self._harness.register_component(
            component_id, component_type, name, config or {}
        )

    async def record_usage(
        self,
        component_id: str,
        success: bool,
        latency_ms: float,
    ) -> None:
        """记录一次组件使用，累积 effectiveness 指标。

        **永不抛出异常**——埋点失败只记 warning 日志，不影响调用方主路径。
        """
        try:
            await self._harness.record_usage(component_id, success, latency_ms)
        except Exception as exc:  # noqa: BLE001 — 埋点绝不打断主路径
            logger.warning(
                "harness usage 埋点失败 component_id=%s: %s",
                component_id,
                exc,
            )
