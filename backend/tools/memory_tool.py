"""
Memory 工具 - 记忆系统操作
"""

from typing import TYPE_CHECKING, Optional, Tuple

from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy

from .base import BaseTool, ToolResult, ToolSchema

# 避免循环导入
if TYPE_CHECKING:
    pass

#: 内部记忆工具类型元组。production 注入点（``SageAgent`` 构造器、
#: ``InprocToolAdapter`` 构造器）和回归测试都从这一处导入，避免
#: 在多个文件里写重复的 ``(MemorySearchTool, MemorySaveTool)`` 字面量。
#: 实际取值在文件末尾赋值（这两个类在下方定义）。
MEMORY_TOOL_TYPES: Tuple[type, ...] = ()


def inject_memory_manager(registry, memory_manager) -> int:
    """遍历 registry，把 ``memory_manager`` 灌进所有记忆工具。

    仅通过 ``ToolRegistry`` 的公开 API（``list_names()`` + ``get(name)``）
    访问工具实例，不触碰私有字典。这是 ``SageAgent`` 构造器、
    ``InprocToolAdapter`` 默认构造路径共享的注入点。

    Args:
        registry: ``ToolRegistry`` 实例。
        memory_manager: ``MemoryManager``（或测试用 fake）。可空但通常
            非空——调用方需自己决定是否在 manager 缺失时跳过。

    Returns:
        实际被注入的工具数（== ``MEMORY_TOOL_TYPES`` 命中数）。
    """
    injected = 0
    for name in registry.list_names():
        tool = registry.get(name)
        if isinstance(tool, MEMORY_TOOL_TYPES):
            tool.set_memory_manager(memory_manager)
            injected += 1
    return injected


class MemorySearchTool(BaseTool):
    """记忆搜索工具"""

    def __init__(self, memory_manager=None, policy: Optional[ToolPolicy] = None) -> None:
        super().__init__(policy=policy)
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
            import asyncio

            loop = asyncio.new_event_loop()
            try:
                results = loop.run_until_complete(
                    self.memory.remember(query=query, context={"memory_type_filter": memory_type})
                )
            finally:
                loop.close()

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

    # A1: 修改本地记忆存储 — 模式门禁（无 path 参数，不做路径受限）
    risk = RiskClass.WRITE_LOCAL

    def __init__(self, memory_manager=None, policy: Optional[ToolPolicy] = None) -> None:
        super().__init__(policy=policy)
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
            import asyncio

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(
                    self.memory.remember(
                        content, {"importance": importance, "memory_type": memory_type}
                    )
                )
            finally:
                loop.close()

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


# ``MEMORY_TOOL_TYPES`` 必须在两个类定义之后填充——上面的类还未声明就
# 引用会触发 NameError。把元组重新绑定到现有名称是 Python 推荐的
# "forward reference" 替代方案，避免在类体里写字符串注解。
MEMORY_TOOL_TYPES = (MemorySearchTool, MemorySaveTool)
