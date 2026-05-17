"""
工具系统初始化

提供所有内置工具的注册函数
"""
from .base import BaseTool, ToolSchema, ToolResult
from .registry import ToolRegistry
from .terminal import TerminalTool
from .file_tool import ReadFileTool, WriteFileTool, ListDirTool
from .web_tool import WebSearchTool, WebFetchTool
from .calculator import CalculatorTool
from .memory_tool import MemorySearchTool, MemorySaveTool
from .skill import SkillHotLoader


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


__all__ = [
    'ToolRegistry',
    'BaseTool',
    'ToolSchema',
    'ToolResult',
    'TerminalTool',
    'ReadFileTool',
    'WriteFileTool',
    'ListDirTool',
    'WebSearchTool',
    'WebFetchTool',
    'CalculatorTool',
    'MemorySearchTool',
    'MemorySaveTool',
    'SkillHotLoader',
    'register_all_tools',
]
