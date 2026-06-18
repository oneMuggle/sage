"""
工具系统初始化

提供所有内置工具的注册函数
"""

from .base import BaseTool, ToolResult, ToolSchema
from .calculator import CalculatorTool
from .file_tool import ListDirTool, ReadFileTool, WriteFileTool
from .memory_tool import MemorySaveTool, MemorySearchTool
from .registry import ToolRegistry
from .skill import SkillHotLoader
from .terminal import TerminalTool
from .web_tool import WebFetchTool, WebSearchTool


def register_all_tools(registry: ToolRegistry) -> None:
    """
    注册所有内置工具到注册表

    Args:
        registry: 工具注册表
    """
    registry.register(TerminalTool())
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(ListDirTool())
    registry.register(WebSearchTool())
    registry.register(WebFetchTool())
    registry.register(CalculatorTool())
    registry.register(MemorySearchTool())
    registry.register(MemorySaveTool())

    # Register MCP tools (from external MCP servers like draw.io)
    try:
        from backend.mcp import register_mcp_tools

        register_mcp_tools(registry)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning(f"Failed to register MCP tools: {exc}")


__all__ = [
    "ToolRegistry",
    "BaseTool",
    "ToolSchema",
    "ToolResult",
    "TerminalTool",
    "ReadFileTool",
    "WriteFileTool",
    "ListDirTool",
    "WebSearchTool",
    "WebFetchTool",
    "CalculatorTool",
    "MemorySearchTool",
    "MemorySaveTool",
    "SkillHotLoader",
    "register_all_tools",
]
