"""
Memory 工具 - 记忆系统操作
"""

from typing import TYPE_CHECKING

from .base import BaseTool, ToolResult, ToolSchema

# 避免循环导入
if TYPE_CHECKING:
    pass


class MemorySearchTool(BaseTool):
    """记忆搜索工具"""

    def __init__(self, memory_manager=None):
        super().__init__()
        self.memory = memory_manager

    def set_memory_manager(self, memory_manager):
        """设置记忆管理器"""
        self.memory = memory_manager

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="memory_search",
            description="搜索记忆内容",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索查询"},
                    "memory_type": {
                        "type": "string",
                        "enum": ["all", "episodic", "semantic"],
                        "description": "记忆类型 (默认 all)",
                    },
                    "limit": {"type": "integer", "description": "返回数量 (默认 5)"},
                },
                "required": ["query"],
            },
        )

    def execute(self, query: str, memory_type: str = "all", limit: int = 5, **kwargs) -> ToolResult:
        """
        搜索记忆

        Args:
            query: 搜索查询
            memory_type: 记忆类型
            limit: 返回数量
        """
        if self.memory is None:
            return ToolResult(success=False, error="记忆管理器未初始化")

        try:
            # 调用记忆管理器的搜索功能
            results = self.memory.remember(query=query, context={"memory_type_filter": memory_type})

            return ToolResult(
                success=True,
                content={
                    "query": query,
                    "memory_type": memory_type,
                    "results": results[:limit] if results else [],
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=f"搜索记忆失败: {str(e)}")


class MemorySaveTool(BaseTool):
    """记忆保存工具"""

    def __init__(self, memory_manager=None):
        super().__init__()
        self.memory = memory_manager

    def set_memory_manager(self, memory_manager):
        """设置记忆管理器"""
        self.memory = memory_manager

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="memory_save",
            description="保存重要信息到记忆",
            parameters={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "要保存的内容"},
                    "importance": {"type": "integer", "description": "重要性 (1-10, 默认 5)"},
                    "memory_type": {
                        "type": "string",
                        "description": "记忆类型: episodic, semantic (默认 episodic)",
                    },
                },
                "required": ["content"],
            },
        )

    def execute(
        self, content: str, importance: int = 5, memory_type: str = "episodic", **kwargs
    ) -> ToolResult:
        """
        保存记忆

        Args:
            content: 要保存的内容
            importance: 重要性 (1-10)
            memory_type: 记忆类型
        """
        if self.memory is None:
            return ToolResult(success=False, error="记忆管理器未初始化")

        try:
            self.memory.remember(
                content, {"importance": importance, "memory_type": memory_type}
            )

            return ToolResult(
                success=True,
                content={
                    "content_length": len(content),
                    "importance": importance,
                    "memory_type": memory_type,
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=f"保存记忆失败: {str(e)}")
