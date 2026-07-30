"""
工具注册表
管理所有可用工具的注册和获取
"""

from __future__ import annotations

import builtins
import logging
from typing import Any, Dict, List, Optional

from backend.domain.risk import RiskClass, RiskOverrides, classify as classify_risk

from .base import BaseTool, ToolSchema
from .context import ToolExecutionContext, current_tool_context

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    工具注册表

    负责:
    - 注册和取消注册工具
    - 根据名称获取工具
    - 列出所有可用工具
    - A1: 注册时收集工具声明的 ``risk``，供权限引擎数据化门禁
    """

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        # A1: 每个工具注册时声明的风险类别（BaseTool.risk，缺省 READ）
        self._risks: Dict[str, RiskClass] = {}

    def register(self, tool: BaseTool) -> None:
        """
        注册工具

        Args:
            tool: BaseTool 实例（通过类属性 ``risk`` 声明风险类别）
        """
        tool_name = tool.name
        if tool_name in self._tools:
            logger.warning(f"工具 {tool_name} 已存在，将被覆盖")

        self._tools[tool_name] = tool
        risk = getattr(tool, "risk", RiskClass.READ)
<<<<<<< HEAD
        # A1: 防御子类误设非法 risk（如 None）— 回退 READ 并告警
        if not isinstance(risk, RiskClass):
            logger.warning(
                f"工具 {tool_name} 声明的 risk 非法 ({risk!r})，回退 READ"
            )
            risk = RiskClass.READ
=======
>>>>>>> 2a006d4f (feat(permission): add RiskClass data-driven permissions (A1))
        self._risks[tool_name] = risk
        logger.info(f"注册工具: {tool_name} (risk={risk.value})")

    def unregister(self, name: str) -> bool:
        """
        取消注册工具

        Args:
            name: 工具名称

        Returns:
            是否成功取消
        """
        if name in self._tools:
            del self._tools[name]
            self._risks.pop(name, None)
            logger.info(f"取消注册工具: {name}")
            return True
        return False

    def get(self, name: str) -> BaseTool | None:
        """
        获取工具

        Args:
            name: 工具名称

        Returns:
            工具实例，不存在返回 None
        """
        return self._tools.get(name)

    def list(self) -> List[ToolSchema]:
        """
        列出所有已注册工具的 Schema

        Returns:
            工具 Schema 列表
        """
        return [tool.schema for tool in self._tools.values()]

    def list_names(self) -> builtins.list[str]:
        """
        列出所有已注册工具的名称

        Returns:
            工具名称列表
        """
        return list(self._tools.keys())

    def get_schemas_for_llm(
        self,
        context: Optional[ToolExecutionContext] = None,
        allowed_tools: Optional[List[str]] = None,
    ) -> builtins.list[Dict[str, Any]]:
        """
        获取适合 LLM 调用的工具 Schema 列表

        Tools marked ``requires_tool_context = True`` are filtered out
        unless an active ``ToolExecutionContext`` is in scope. Normal
        tools are never hidden by an active context.

        Args:
            context: Explicit context override. When ``None`` (default),
                falls back to ``current_tool_context()`` so the agent loop
                can pull the per-request context without threading it
                through every helper signature. Pass ``None`` explicitly
                to opt out of the ContextVar lookup and force the
                "no context" filter behavior.
            allowed_tools: Whitelist from the active agent profile's
                ``profile.tools`` field. ``None`` (default) means
                "no whitelist" -- every tool passing the context filter
                is exposed (legacy behavior, used when ``SageAgent`` has
                no profile loaded). An explicit list filters the result
                to those names only; pass ``[]`` to expose nothing.

        Returns:
            包含 name, description, parameters 的字典列表
        """
        # Resolve the effective context: explicit ``context`` arg wins,
        # otherwise consult the ContextVar. ``current_tool_context()``
        # returns ``None`` outside any set_tool_context() block.
        effective_context = context if context is not None else current_tool_context()

        result = []
        for tool in self._tools.values():
            # Hide office-only tools when there's no context to bind them
            # to. Normal tools are always visible -- an active context
            # widens the set, never narrows it.
            if tool.requires_tool_context and effective_context is None:
                continue
            # profile.tools 白名单:仅当 allowed_tools 显式给出时才过滤
            if allowed_tools is not None and tool.schema.name not in allowed_tools:
                continue
            result.append(
                {
                    "name": tool.schema.name,
                    "description": tool.schema.description,
                    "parameters": tool.schema.parameters,
                }
            )
        return result

    def exists(self, name: str) -> bool:
        """
        检查工具是否已注册

        Args:
            name: 工具名称

        Returns:
            是否存在
        """
        return name in self._tools

    def risk_of(self, name: str) -> RiskClass:
        """
        获取工具注册时声明的风险类别（A1）

        Args:
            name: 工具名称

        Returns:
            声明的 ``RiskClass``；未注册或未声明时按 ``READ`` 处理
        """
        return self._risks.get(name, RiskClass.READ)

    def declared_risks(self) -> Dict[str, RiskClass]:
        """
        返回 {工具名: 声明风险} 的快照副本（A1）

        供 ``PermissionEngine`` 经 ``declared_risks`` 参数注入，实现
        数据化权限门禁。返回副本，调用方修改不影响注册表内部状态。
        """
        return dict(self._risks)

    def classify(
        self,
        name: str,
        metadata: Any = None,
<<<<<<< HEAD
        overrides: Optional[RiskOverrides] = None,
=======
        overrides: Optional[Any] = None,
>>>>>>> 2a006d4f (feat(permission): add RiskClass data-driven permissions (A1))
    ) -> RiskClass:
        """
        解析工具的有效风险（A1）

        以本注册表收集的工具声明为 ``declared`` 来源，委托
        ``backend.domain.risk.classify`` 按优先级解析：
        用户覆盖 > 注册声明 > 按名兜底表 > 元数据启发式 > READ。

        Args:
            name:      工具名称
            metadata:  工具元数据（对象或 dict）
            overrides: 用户级覆盖解析器（A19，缺省 None）

        Returns:
            有效 ``RiskClass``
        """
        return classify_risk(
            name, metadata=metadata, overrides=overrides, declared=self._risks
        )

    def clear(self) -> None:
        """清空所有已注册工具"""
        self._tools.clear()
        self._risks.clear()
        logger.info("清空所有已注册工具")
