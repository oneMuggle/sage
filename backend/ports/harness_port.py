"""Harness 组件管理端口。

Harness 是围绕 LLM 模型的运行时脚手架（Agent = Model + Harness）。
本端口定义 harness 组件的注册、发现、配置更新与 usage 记账的抽象接口。

对标：
- DeepSeek Harness 的 capability seam（Service Definition 角色）
- Google Harness 2 的 8 个可编辑组件

实现侧为 ``backend.adapters.out.harness.sqlite_adapter.SqliteHarnessAdapter``。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol

from backend.domain.harness_component import HarnessComponent


class HarnessPort(Protocol):
    """Harness 组件注册表端口。

    全部方法为 async：SQLite 访问经 ``to_thread`` 卸载到线程池，
    避免阻塞事件循环（与 ``StoragePort`` 一致）。
    """

    async def list_components(
        self,
        component_type: Optional[str] = None,
    ) -> List[HarnessComponent]:
        """列出已注册的 harness 组件。

        Args:
            component_type: 按类型过滤（8 类之一）；``None`` 表示全部。

        Returns:
            组件列表，按 id 升序。
        """
        ...

    async def get_component(self, component_id: str) -> Optional[HarnessComponent]:
        """按 ID 获取单个组件。

        Args:
            component_id: 组件唯一 ID（如 ``"skill:academic-search"``）。

        Returns:
            组件；不存在时返回 ``None``。
        """
        ...

    async def register_component(
        self,
        component_id: str,
        component_type: str,
        name: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> HarnessComponent:
        """注册一个新组件（幂等：已存在则更新配置）。

        Args:
            component_id: 组件唯一 ID。
            component_type: 组件类型（8 类之一）。
            name: 组件显示名称。
            config: 初始配置。

        Returns:
            注册后的组件。
        """
        ...

    async def update_component(
        self,
        component_id: str,
        config: Dict[str, Any],
    ) -> Optional[HarnessComponent]:
        """热更新组件配置（不重启后端）。

        Args:
            component_id: 组件唯一 ID。
            config: 新配置（整体替换，非 merge）。

        Returns:
            更新后的组件；组件不存在时返回 ``None``。
        """
        ...

    async def record_usage(
        self,
        component_id: str,
        success: bool,
        latency_ms: float,
    ) -> None:
        """记录一次组件使用，累积 effectiveness 指标。

        组件不存在时静默忽略（埋点不应影响主路径）。

        Args:
            component_id: 组件唯一 ID。
            success: 本次使用是否成功。
            latency_ms: 本次使用耗时（毫秒）。
        """
        ...
