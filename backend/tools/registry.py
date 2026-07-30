"""
工具注册表
管理所有可用工具的注册和获取
"""

from __future__ import annotations

import builtins
import logging
from typing import Any, Dict, List, Optional

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
    """

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """
        注册工具

        Args:
            tool: BaseTool 实例
        """
        tool_name = tool.name
        if tool_name in self._tools:
            logger.warning(f"工具 {tool_name} 已存在，将被覆盖")

        self._tools[tool_name] = tool
        logger.info(f"注册工具: {tool_name}")

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

    def clear(self) -> None:
        """清空所有已注册工具"""
        self._tools.clear()
        logger.info("清空所有已注册工具")
