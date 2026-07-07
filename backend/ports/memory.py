"""Memory Port Protocol

六边形架构中的记忆端口协议,定义记忆系统的接口。
"""

from __future__ import annotations

from typing import List, Optional, Protocol

from backend.domain.memory import MemoryContext


class MemoryPort(Protocol):
    """记忆端口协议 - 六边形架构的记忆接口

    定义记忆系统的标准接口,允许不同的记忆实现(如 SQLite、向量数据库等)
    通过适配器模式接入六边形架构。

    Example:
        >>> class MemoryAdapter(MemoryPort):
        ...     async def retrieve(self, query, session_id, limit=5):
        ...         return MemoryContext(
        ...             working=[{"role": "user", "content": "你好"}],
        ...             episodic=[{"content": "用户偏好"}],
        ...             semantic=[]
        ...         )
    """

    async def retrieve(self, query: str, session_id: str, limit: int = 5) -> MemoryContext:
        """检索相关记忆

        根据查询文本和会话 ID,从三层记忆中检索相关内容。

        Args:
            query: 查询文本,用于匹配相关记忆
            session_id: 会话 ID,用于获取会话相关的记忆
            limit: 每种记忆类型的返回数量限制,默认 5

        Returns:
            MemoryContext: 包含三层记忆的上下文对象
                - working: 工作记忆 (当前对话上下文)
                - episodic: 情景记忆 (对话历史和事件)
                - semantic: 语义记忆 (知识和概念)

        Example:
            >>> context = await memory_port.retrieve("火锅", "session-123")
            >>> context.has_memories
            True
        """
        ...

    async def store(
        self, content: str, session_id: str, importance: int = 5, tags: Optional[List[str]] = None
    ) -> str:
        """存储记忆

        将内容存储到记忆系统中。根据内容的重要性和类型,
        自动决定存储到哪一层记忆。

        Args:
            content: 要存储的记忆内容
            session_id: 关联的会话 ID
            importance: 重要性评分 (1-10),默认 5
                - 1-3: 低重要性,临时信息
                - 4-6: 中等重要性,一般对话
                - 7-10: 高重要性,关键信息
            tags: 可选的标签列表,用于分类和检索

        Returns:
            str: 生成的记忆 ID,可用于后续检索或删除

        Example:
            >>> memory_id = await memory_port.store(
            ...     content="用户喜欢吃火锅",
            ...     session_id="session-123",
            ...     importance=7,
            ...     tags=["preference", "food"]
            ... )
        """
        ...

    async def compress(self, session_id: str) -> None:
        """压缩工作记忆

        当工作记忆的 Token 数量超过阈值时,将其压缩为摘要,
        并存储到情景记忆中,以释放工作记忆空间。

        Args:
            session_id: 会话 ID,用于关联压缩后的记忆

        Returns:
            None

        Note:
            此方法通常由 ChatService 在每次对话后自动调用,
            无需手动调用。

        Example:
            >>> await memory_port.compress("session-123")
        """
        ...
