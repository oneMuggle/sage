"""Memory Adapter - 记忆端口适配器

将 MemoryPort 协议适配到现有的 MemoryManager 实现。
"""

import logging

from backend.domain.memory import MemoryContext
from backend.memory import ConsolidationPipeline, MemoryManager

logger = logging.getLogger(__name__)


class MemoryAdapter:
    """记忆端口适配器 - 将 MemoryPort 适配到现有的 MemoryManager

    这个适配器将六边形架构的 MemoryPort 协议桥接到现有的 MemoryManager 实现,
    使得 ChatService 可以通过标准接口使用记忆系统。

    Attributes:
        memory_manager: 现有的 MemoryManager 实例
        consolidation: 记忆压缩管道

    Example:
        >>> from backend.memory import MemoryManager, WorkingMemory, EpisodicMemory, SemanticMemory
        >>> from backend.data.database import Database
        >>>
        >>> db = Database("data/sage.db")
        >>> memory_manager = MemoryManager(
        ...     working=WorkingMemory(),
        ...     episodic=EpisodicMemory(db),
        ...     semantic=SemanticMemory(db)
        ... )
        >>> adapter = MemoryAdapter(memory_manager)
        >>> context = await adapter.retrieve("火锅", "session-123")
    """

    def __init__(self, memory_manager: MemoryManager):
        """初始化记忆适配器

        Args:
            memory_manager: MemoryManager 实例,提供三层记忆的管理功能
        """
        self.memory_manager = memory_manager
        self.consolidation = ConsolidationPipeline()

    async def retrieve(self, query: str, session_id: str, limit: int = 5) -> MemoryContext:
        """检索相关记忆

        调用 MemoryManager.recall() 检索三层记忆,并封装为 MemoryContext。

        Args:
            query: 查询文本,用于匹配相关记忆
            session_id: 会话 ID(当前实现中未使用,预留用于会话级记忆过滤)
            limit: 每种记忆类型的返回数量限制,默认 5

        Returns:
            MemoryContext: 包含三层记忆的上下文对象
        """
        logger.debug(f"Retrieving memories for query: {query[:50]}...")

        # 调用 MemoryManager.recall() 检索记忆
        # recall() 返回字典: {"working": [...], "episodic": [...], "semantic": [...]}
        results = self.memory_manager.recall(query, limit=limit)

        return MemoryContext(
            working=results.get("working", []),
            episodic=results.get("episodic", []),
            semantic=results.get("semantic", []),
        )

    async def store(
        self, content: str, session_id: str, importance: int = 5, tags: list[str] | None = None
    ) -> str:
        """存储记忆

        调用 MemoryManager.memorize() 存储记忆到合适的记忆层。

        Args:
            content: 要存储的记忆内容
            session_id: 关联的会话 ID
            importance: 重要性评分 (1-10),默认 5
            tags: 可选的标签列表,用于分类和检索

        Returns:
            str: 生成的记忆 ID,对于工作记忆返回空字符串
        """
        logger.debug(f"Storing memory: {content[:50]}...")

        # 构建元数据
        metadata = {"session_id": session_id, "tags": tags or []}

        # 调用 MemoryManager.memorize() 存储记忆
        # memorize() 会根据 importance 自动选择记忆类型:
        # - importance >= 8: 语义记忆
        # - importance < 5 and len < 200: 工作记忆
        # - 其他: 情景记忆
        memory_id = self.memory_manager.memorize(
            content=content, importance=importance, metadata=metadata
        )

        return memory_id or ""

    async def compress(self, session_id: str) -> None:
        """压缩工作记忆

        当工作记忆的 Token 数量超过阈值(3000)时,调用 ConsolidationPipeline
        将其压缩为摘要,并存储到情景记忆中。

        Args:
            session_id: 会话 ID,用于关联压缩后的记忆

        Returns:
            None

        Note:
            此方法通常由 ChatService 在每次对话后自动调用。
            如果 Token 数量未超过阈值,则不执行任何操作。
        """
        # 检查工作记忆的 Token 数量
        if self.memory_manager.working.total_tokens > 3000:
            logger.info(f"Compressing working memory for session: {session_id}")

            # 调用 ConsolidationPipeline.consolidate() 压缩记忆
            # consolidate() 会:
            # 1. 获取工作记忆中的所有消息
            # 2. 使用 LLM 或简单策略生成摘要
            # 3. 将摘要存储到情景记忆
            # 4. 清空工作记忆
            self.consolidation.consolidate(self.memory_manager, session_id=session_id)
        else:
            logger.debug(
                f"Skipping compression: tokens={self.memory_manager.working.total_tokens} <= 3000"
            )
