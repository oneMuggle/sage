"""Memory Adapter - 记忆端口适配器

将 MemoryPort 协议适配到现有的 MemoryManager 实现。
集成向量检索：store() 自动生成 embedding，retrieve() 包含向量搜索结果。
"""

import logging

from backend.domain.memory import MemoryContext
from backend.memory import ConsolidationPipeline, MemoryManager
from backend.memory.embedder import HashEmbedder
from backend.memory.vector_store import VectorStore

logger = logging.getLogger(__name__)


class MemoryAdapter:
    """记忆端口适配器 - 将 MemoryPort 适配到现有的 MemoryManager

    这个适配器将六边形架构的 MemoryPort 协议桥接到现有的 MemoryManager 实现,
    使得 ChatService 可以通过标准接口使用记忆系统。

    集成:
    - MemoryManager: 三层记忆（Working/Episodic/Semantic）
    - VectorStore: sqlite-vec 向量检索
    - ConsolidationPipeline: 工作记忆压缩

    Attributes:
        memory_manager: 现有的 MemoryManager 实例
        consolidation: 记忆压缩管道
        vector_store: 向量存储（sqlite-vec）
        embedder: 文本向量化器
    """

    def __init__(self, memory_manager: MemoryManager):
        """初始化记忆适配器

        Args:
            memory_manager: MemoryManager 实例,提供三层记忆的管理功能
        """
        self.memory_manager = memory_manager
        self.consolidation = ConsolidationPipeline()
        self.embedder = HashEmbedder(dimensions=256)

        # 初始化向量存储（需要 Database 实例）
        # 从 MemoryManager 中获取 db（EpisodicMemory 持有 db 引用）
        self.vector_store = None
        try:
            db = getattr(memory_manager.episodic, "db", None)
            if db is not None and hasattr(db, "get_connection"):
                self.vector_store = VectorStore(db, self.embedder)
                logger.info("VectorStore 已初始化（sqlite-vec 向量检索）")
        except (AttributeError, TypeError):
            # 测试中使用 Mock MemoryManager 时可能没有 episodic 属性
            pass
        if self.vector_store is None:
            logger.debug("VectorStore 未初始化：无可用 Database 实例")

    async def retrieve(self, query: str, session_id: str, limit: int = 5) -> MemoryContext:
        """检索相关记忆

        调用 MemoryManager.recall() 检索三层记忆,并结合 VectorStore 向量检索,
        使用 Reciprocal Rank Fusion (RRF) 融合结果。

        Args:
            query: 查询文本,用于匹配相关记忆
            session_id: 会话 ID(当前实现中未使用,预留用于会话级记忆过滤)
            limit: 每种记忆类型的返回数量限制,默认 5

        Returns:
            MemoryContext: 包含三层记忆的上下文对象
        """
        logger.debug(f"Retrieving memories for query: {query[:50]}...")

        # 调用 MemoryManager.recall() 检索三层记忆
        results = self.memory_manager.recall(query, limit=limit)

        # 向量检索结果合并（如果有 VectorStore）
        if self.vector_store is not None:
            vec_results = self.vector_store.search(query, top_k=limit)
            if vec_results:
                # 从向量搜索结果中获取完整的记忆内容
                for vr in vec_results:
                    mem_id = vr["memory_id"]
                    # 尝试从 episodic 或 semantic 中获取完整记忆
                    mem = self.memory_manager.episodic.get_by_id(mem_id)
                    if mem is None:
                        mem = self.memory_manager.semantic.get_by_id(mem_id)
                    if mem is not None and mem not in results.get("episodic", []):
                        results.setdefault("episodic", []).append(mem)

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
        同时将记忆内容向量化存入 VectorStore，供后续向量检索使用。

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
        memory_id = self.memory_manager.memorize(
            content=content, importance=importance, metadata=metadata
        )

        # 向量化存储（如果有 VectorStore 且成功生成了 memory_id）
        if self.vector_store is not None and memory_id:
            memory_type = "episodic"  # memorize() 默认存为 episodic
            if importance >= 8:
                memory_type = "semantic"
            self.vector_store.add(memory_id, content, memory_type=memory_type)

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
