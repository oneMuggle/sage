"""
工具注册表
管理所有可用工具的注册和获取
"""
import logging
from typing import Any, Dict, List, Optional

from .base import BaseTool, ToolSchema

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

    def get(self, name: str) -> Optional[BaseTool]:
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

    def list_names(self) -> List[str]:
        """
        列出所有已注册工具的名称
        
        Returns:
            工具名称列表
        """
        return list(self._tools.keys())

    def get_schemas_for_llm(self) -> List[Dict[str, Any]]:
        """
        获取适合 LLM 调用的工具 Schema 列表
        
        Returns:
            包含 name, description, parameters 的字典列表
        """
        result = []
        for tool in self._tools.values():
            result.append({
                "name": tool.schema.name,
                "description": tool.schema.description,
                "parameters": tool.schema.parameters
            })
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
