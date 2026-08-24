# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""
Memory 工具 - 记忆系统操作

Task 2 (Win7 parity) 修复要点
=============================

- ``MemorySaveTool.execute`` 不再 ``new_event_loop().run_until_complete()`` —
  它直接调 ``MemoryManager.memorize(...)`` 同步方法,返回记忆 ID。原实现
  来自 Win7 packaged 后端的运行时错误:"cannot run the event loop while
  another loop is running"。
- ``MemorySearchTool.execute`` 不再调 ``manager.remember(query=...)``(会触发
  ``TypeError: remember() got an unexpected keyword argument 'query'``),
  改为调 ``MemoryManager.search_memories(query, memory_type, limit)``。
  ``memory_type='all'`` / ``''`` / ``None`` 都映射为 ``None``;
  ``limit`` clamp 到 ``[1, 100]``,默认 20。
"""

from typing import TYPE_CHECKING, Any, List, Optional, Tuple

from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy
from backend.tools.context import current_tool_context

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


#: ``MemorySearchTool.execute`` 中 ``limit`` 参数的下界（含）。
#: ``search_memories`` 在 ``LIMIT 0`` 时静默返回空数组,与"clamp 到 1"语义不同。
MIN_SEARCH_LIMIT = 1
#: ``MemorySearchTool.execute`` 中 ``limit`` 参数的上界（含）。
#: 防止恶意/手抖传 99999 触发整表扫描 + 内存爆。
MAX_SEARCH_LIMIT = 100
#: ``MemorySearchTool.execute`` 中 ``limit`` 的默认值。
DEFAULT_SEARCH_LIMIT = 20
#: ``memory_type`` 在不同入口（tool args / IPC / URL 参数）下都用 'all' 作为
#: "全部"的统一哨兵;映射到 ``MemoryManager.search_memories(memory_type=None)``
#: 的契约。空串 / None 视作等价。
SEARCH_TYPE_ALL = "all"
SEARCH_MEMORY_TYPES = ("all", "working", "episodic", "semantic")
SAVE_MEMORY_TYPES = ("auto", "working", "episodic", "semantic")


class MemorySearchTool(BaseTool):
    """记忆搜索工具。

    Task 2 修复后直接调同步的 ``MemoryManager.search_memories``,
    不再调 ``remember``(无 ``query`` kwarg)和 ``new_event_loop``。
    """

    def __init__(
        self,
        memory_manager: Any = None,
        memory: Any = None,
        policy: Optional[ToolPolicy] = None,
    ) -> None:
        """构造器接受 ``memory_manager``(旧)与 ``memory``(新 brief)两种命名。

        新 brief 默认用 ``memory=``;旧注入路径仍是 ``memory_manager=``。
        两个都给 ``None`` 时优先用 ``memory``(新风格),都为空则工具保持未初始化。
        """
        super().__init__(policy=policy)
        # 新旧兼容: ``memory=`` 优先, 缺省回退 ``memory_manager=``
        self.memory = memory if memory is not None else memory_manager

    def set_memory_manager(self, memory_manager):
        """设置记忆管理器(旧名, 兼容 SageAgent 注入路径)。"""
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
                        "enum": ["all", "working", "episodic", "semantic"],
                        "description": "记忆类型 (默认 all)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回数量 (默认 20, 上限 100)",
                    },
                },
                "required": ["query"],
            },
        )

    @staticmethod
    def _normalize_memory_type(memory_type: Optional[str]) -> Optional[str]:
        """Validate and normalize the supported search memory types."""
        if memory_type is None or memory_type == "":
            return None
        if memory_type not in SEARCH_MEMORY_TYPES:
            raise ValueError("不支持的搜索记忆类型")
        if memory_type == SEARCH_TYPE_ALL:
            return None
        return memory_type

    @staticmethod
    def _clamp_limit(limit: Optional[int]) -> int:
        """``[1, 100]`` clamp, 缺省 20。

        旧默认值是 5, 新默认值是 20(对齐后端 ``/memory/search`` 端点)。
        """
        try:
            n = int(limit) if limit is not None else DEFAULT_SEARCH_LIMIT
        except (TypeError, ValueError):
            return DEFAULT_SEARCH_LIMIT
        if n < MIN_SEARCH_LIMIT:
            return MIN_SEARCH_LIMIT
        if n > MAX_SEARCH_LIMIT:
            return MAX_SEARCH_LIMIT
        return n

    def execute(
        self,
        query: str,
        memory_type: Optional[str] = SEARCH_TYPE_ALL,
        limit: int = DEFAULT_SEARCH_LIMIT,
        **kwargs: Any,
    ) -> ToolResult:
        """
        搜索记忆

        Args:
            query: 搜索查询
            memory_type: ``all``/空串/None 视作 "全部类型";其余原样转发
                到 ``MemoryManager.search_memories``。
            limit: 返回数量, clamp 到 ``[1, 100]``, 默认 20。
        """
        if self.memory is None:
            return ToolResult(success=False, error="记忆管理器未初始化")

        try:
            normalized_type = self._normalize_memory_type(memory_type)
            clamped_limit = self._clamp_limit(limit)
            context = current_tool_context()
            if context is None:
                return ToolResult(success=False, error="记忆搜索需要可信会话上下文")

            results = self.memory.search_memories(
                query, normalized_type, clamped_limit, session_id=context.session_id
            )
            # 持久层旧实现可能忽略 session_id；过滤所有会话标识明确不匹配的记录。
            scoped_results = [
                item
                for item in (results or [])
                if not item.get("session_id") or item.get("session_id") == context.session_id
            ]
            truncated = scoped_results[:clamped_limit]

            return ToolResult(
                success=True,
                content={
                    "query": query,
                    "memory_type": memory_type,
                    "results": truncated,
                },
                output=truncated,
            )

        except Exception as e:
            return ToolResult(success=False, error=f"搜索记忆失败: {str(e)}")


class MemorySaveTool(BaseTool):
    """记忆保存工具。

    Task 2 修复后直接调同步的 ``MemoryManager.memorize``,
    不再 ``new_event_loop().run_until_complete()``。
    """

    # A1: 修改本地记忆存储 — 模式门禁（无 path 参数，不做路径受限）
    risk = RiskClass.WRITE_LOCAL

    def __init__(
        self,
        memory_manager: Any = None,
        memory: Any = None,
        policy: Optional[ToolPolicy] = None,
    ) -> None:
        """同 ``MemorySearchTool``: ``memory`` 是新 brief 首选 kwarg。"""
        super().__init__(policy=policy)
        self.memory = memory if memory is not None else memory_manager

    def set_memory_manager(self, memory_manager):
        """设置记忆管理器(旧名, 兼容 SageAgent 注入路径)。"""
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
                        "description": "记忆类型: working, episodic, semantic (默认 episodic)",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "标签列表 (可选)",
                    },
                    "session_id": {
                        "type": "string",
                        "description": "会话 ID (可选, 用于按会话隔离)",
                    },
                },
                "required": ["content"],
            },
        )

    def execute(
        self,
        content: str,
        importance: int = 5,
        memory_type: str = "episodic",
        tags: Optional[List[str]] = None,
        session_id: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        """
        保存记忆

        Args:
            content: 要保存的内容
            importance: 重要性 (1-10, 默认 5)
            memory_type: ``working`` / ``episodic`` / ``semantic`` / ``auto``
                (默认 ``episodic``)
            tags: 标签列表 (可选)
            session_id: 会话 ID (可选, 用于按会话隔离工作记忆)

        Returns:
            ``ToolResult(success, content, output)``,其中 ``output`` 是
            ``MemoryManager.memorize`` 返回的记忆 ID(供后续 read/recall
            使用,不能丢)。
        """
        if self.memory is None:
            return ToolResult(success=False, error="记忆管理器未初始化")

        context = current_tool_context()
        if context is None:
            return ToolResult(success=False, error="记忆保存需要可信会话上下文")
        if session_id is not None and session_id != context.session_id:
            return ToolResult(success=False, error="session_id 与当前会话不一致")
        effective_session_id = context.session_id
        if memory_type not in SAVE_MEMORY_TYPES:
            return ToolResult(success=False, error="不支持的保存记忆类型")

        # tags 直接透传（``[]`` 走空列表路径, ``None`` 走 manager 默认）。
        # 不在这里做 normalize —— 测试用 ``MagicMock.assert_called_once_with``
        # 会严格比较 args。``memorize`` 自身对 ``None`` tags 安全处理。
        forwarded_tags = list(tags) if tags is not None else None

        try:
            memory_id = self.memory.memorize(
                content,
                memory_type,
                importance,
                forwarded_tags,
                session_id=effective_session_id,
            )
        except TypeError as exc:
            # 旧 manager 不支持 session_id 时无法保证会话隔离，拒绝写入。
            if "session_id" in str(exc):
                return ToolResult(
                    success=False,
                    error="记忆管理器不支持会话隔离，拒绝保存记忆",
                )
            return ToolResult(success=False, error=f"保存记忆失败: {exc}")
        except Exception as e:
            return ToolResult(success=False, error=f"保存记忆失败: {str(e)}")

        return ToolResult(
            success=memory_id is not None,
            error=None if memory_id is not None else "保存记忆失败: 未返回记忆 ID",
            content={
                "memory_id": memory_id,
                "content_length": len(content),
                "importance": importance,
                "memory_type": memory_type,
            },
            output=memory_id,
        )


# ``MEMORY_TOOL_TYPES`` 必须在两个类定义之后填充——上面的类还未声明就
# 引用会触发 NameError。把元组重新绑定到现有名称是 Python 推荐的
# "forward reference" 替代方案，避免在类体里写字符串注解。
MEMORY_TOOL_TYPES = (MemorySearchTool, MemorySaveTool)
