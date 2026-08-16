"""
工具系统初始化

提供所有内置工具的注册函数
"""
from typing import Optional

from backend.domain.tool_policy import ToolPolicy

from .ask_user_tool import AskUserQuestionTool
from .base import BaseTool, ToolResult, ToolSchema
from .calculator import CalculatorTool
from .edit_tool import EditTool
from .file_tool import ListDirTool, ReadFileTool, WriteFileTool
from .memory_tool import MemorySaveTool, MemorySearchTool
from .office_tool import OfficeListTool, OfficeReadTool
from .registry import ToolRegistry
from .repl_tool import ReplTool
from .search_tools import GlobSearchTool, GrepSearchTool
from .skill import SkillHotLoader
from .skill_tool import SkillTool
from .structured_output_tool import StructuredOutputTool
from .terminal import TerminalTool
from .todo_tool import TodoWriteTool
from .web_tool import WebFetchTool, WebSearchTool


def register_all_tools(registry: ToolRegistry, policy: Optional[ToolPolicy] = None) -> None:
    """
    注册所有内置工具到注册表

    Args:
        registry: 工具注册表
        policy:   M2 工具策略（缺省 ``ToolPolicy()``）；透传给每个内置工具。
    """
    policy = policy or ToolPolicy()
    registry.register(TerminalTool(policy=policy))
    registry.register(ReadFileTool(policy=policy))
    registry.register(WriteFileTool(policy=policy))
    registry.register(ListDirTool(policy=policy))
    registry.register(WebSearchTool(policy=policy))
    registry.register(WebFetchTool(policy=policy))
    registry.register(CalculatorTool(policy=policy))
    registry.register(MemorySearchTool(policy=policy))
    registry.register(MemorySaveTool(policy=policy))
    registry.register(OfficeListTool(policy=policy))
    registry.register(OfficeReadTool(policy=policy))
    # M2 agent 工具面扩展（移植 claw-code: edit/glob/grep/todo/structured/repl）
    registry.register(EditTool(policy=policy))
    registry.register(GlobSearchTool(policy=policy))
    registry.register(GrepSearchTool(policy=policy))
    registry.register(TodoWriteTool(policy=policy))
    registry.register(StructuredOutputTool(policy=policy))
    registry.register(ReplTool(policy=policy))
    # M2 part B: in-loop 技能调用（EXECUTE，M1 审批闸口按模式矩阵拦截）
    registry.register(SkillTool(policy=policy))
    # M2 part B: AskUserQuestion（READ，run_loop 分发前特判 + 提问闸口）
    registry.register(AskUserQuestionTool(policy=policy))

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
    "OfficeListTool",
    "OfficeReadTool",
    "EditTool",
    "GlobSearchTool",
    "GrepSearchTool",
    "TodoWriteTool",
    "StructuredOutputTool",
    "ReplTool",
    "SkillTool",
    "AskUserQuestionTool",
    "SkillHotLoader",
    "register_all_tools",
]
