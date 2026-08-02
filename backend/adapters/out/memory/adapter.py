"""Memory Adapter - 记忆端口适配器

将 MemoryPort 协议适配到现有的 MemoryManager 实现。
集成向量检索：store() 自动生成 embedding，retrieve() 包含向量搜索结果。
"""

from __future__ import annotations

import logging
from typing import List, Optional

from backend.domain.memory import MemoryContext
from backend.memory import ConsolidationPipeline, MemoryManager
from backend.memory.embedder import HashEmbedder
from backend.memory.manager import classify_memory_type
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

    def __init__(self, memory_manager: MemoryManager, user_profile=None):
        """初始化记忆适配器

        Args:
            memory_manager: MemoryManager 实例,提供三层记忆的管理功能
            user_profile: 可选 UserProfileStore 实例;缺省用全局单例
                ``get_user_profile()``（与 get_memory_manager 同模式）。
        """
        self.memory_manager = memory_manager
        self.consolidation = ConsolidationPipeline()
        self.embedder = HashEmbedder(dimensions=256)
        # 用户画像（USER.md 概念）: 缺省惰性取全局单例,失败时降级为 None
        self.user_profile = user_profile
        if self.user_profile is None:
            try:
                from backend.memory.user_profile import get_user_profile

                self.user_profile = get_user_profile()
            except Exception as exc:  # pragma: no cover - 防御性兜底
                logger.warning(f"UserProfileStore 初始化失败: {exc}")
                self.user_profile = None

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

        多路检索 + RRF 融合：
        1. MemoryManager.recall() — 关键词检索（episodic + semantic）
        2. VectorStore.search() — 向量检索
        3. 两路结果用 RRF 融合，按融合分数排序
        4. 高重要性事实（importance >= 8）提升为核心记忆（core）

        Args:
            query: 查询文本,用于匹配相关记忆
            session_id: 会话 ID,透传给 recall 用于工作记忆的会话级过滤
            limit: 每种记忆类型的返回数量限制,默认 5

        Returns:
            MemoryContext: 包含分层记忆的上下文对象
        """
        from backend.memory.fusion import reciprocal_rank_fusion

        logger.debug(f"Retrieving memories for query: {query[:50]}...")

        # 1. 关键词检索（MemoryManager，工作记忆按 session 隔离）
        keyword_results = self.memory_manager.recall(query, limit=limit, session_id=session_id)
        keyword_items = keyword_results.get("episodic", []) + keyword_results.get("semantic", [])

        # 2. 向量检索（VectorStore）
        vector_items: List[dict] = []
        if self.vector_store is not None:
            vec_results = self.vector_store.search(query, top_k=limit)
            for vr in vec_results:
                mem_id = vr["memory_id"]
                mem = self.memory_manager.episodic.get_by_id(mem_id)
                if mem is None:
                    mem = self.memory_manager.semantic.get_by_id(mem_id)
                if mem is not None:
                    mem["rrf_score"] = 1.0 / (60 + vr.get("distance", 0) * 100)
                    vector_items.append(mem)

        # 3. RRF 融合两路结果
        fused = reciprocal_rank_fusion(
            [keyword_items, vector_items],
            weights=[0.4, 0.6],  # 向量检索权重更高
            k=60,
        )

        # 4. 分层：用户画像（始终注入）+ 高重要性 → core，其余 → episodic/semantic
        # core 槽位按画像 / 检索命中**独立预算**（画像 3 + 检索 2 = 5），
        # 避免画像条目挤掉本轮检索到的高重要性事实（review MEDIUM）。
        _CORE_PROFILE_LIMIT = 3
        _CORE_RETRIEVED_LIMIT = 2
        core_profile: List[dict] = []
        core_retrieved: List[dict] = []
        episodic: List[dict] = []
        semantic: List[dict] = []
        # 4.1 持久用户画像（USER.md 概念）——冻结快照条目（char 受限），
        #     不依赖本轮检索命中（hermes 冻结快照语义）
        if self.user_profile is not None:
            core_profile = self.user_profile.get_core_items()
        # 4.2 检索命中中的高重要性事实补入 core（独立预算）
        for item in fused[: limit * 2]:
            importance = item.get("importance", 5)
            if importance >= 8:
                core_retrieved.append(item)
            elif item.get("memory_type") == "semantic" or item.get("category") == "fact":
                semantic.append(item)
            else:
                episodic.append(item)

        core = core_profile[:_CORE_PROFILE_LIMIT] + core_retrieved[:_CORE_RETRIEVED_LIMIT]

        return MemoryContext(
            working=keyword_results.get("working", []),
            episodic=episodic[:limit],
            semantic=semantic[:limit],
            core=core[: _CORE_PROFILE_LIMIT + _CORE_RETRIEVED_LIMIT],
        )

    async def store(
        self, content: str, session_id: str, importance: int = 5, tags: Optional[List[str]] = None
    ) -> str:
        """存储记忆

        调用 MemoryManager.memorize() 存储记忆到合适的记忆层。
        同时将记忆内容向量化存入 VectorStore，供后续向量检索使用。
        写入前进行安全扫描（Hermes 风格），阻止可疑内容。

        Args:
            content: 要存储的记忆内容
            session_id: 关联的会话 ID
            importance: 重要性评分 (1-10),默认 5
            tags: 可选的标签列表,用于分类和检索

        Returns:
            str: 生成的记忆 ID。episodic/semantic 为持久 ID;
            工作记忆为合成 ID ``wm:<session>:<seq>``;memorize 返回 None 时返回空字符串
        """
        from backend.memory.safety import get_scanner

        logger.debug(f"Storing memory: {content[:50]}...")

        # 安全扫描（Hermes 风格）
        scan_result = get_scanner().scan_write(content)
        if scan_result.blocked:
            logger.warning(
                f"Memory write blocked: {scan_result.reason} "
                f"(threat_level={scan_result.threat_level})"
            )
            return ""

        # 统一分类（与 MemoryManager 共用模块级 classify_memory_type,消除规则漂移）
        memory_type = classify_memory_type("auto", importance, content)

        # 构建元数据
        metadata = {"session_id": session_id, "tags": tags or []}

        # 调用 MemoryManager.memorize() 存储记忆（透传分类结果与会话 ID）
        memory_id = self.memory_manager.memorize(
            content=content,
            memory_type=memory_type,
            importance=importance,
            metadata=metadata,
            session_id=session_id,
        )

        # 向量化存储（仅持久层记忆:工作记忆合成 id 不入向量库）
        if self.vector_store is not None and memory_id and memory_type in ("episodic", "semantic"):
            self.vector_store.add(memory_id, content, memory_type=memory_type)

        return memory_id or ""

    async def store_profile(
        self,
        content: str,
        category: str = "preference",
        importance: int = 5,
        session_id: Optional[str] = None,
    ) -> str:
        """存储用户画像（USER.md 概念, MemoryPort 协议外的扩展方法）。

        把"关于用户的知识"写入持久画像库, 而非通用三层记忆。
        ``extract_and_store_memory`` 通过结构性探测（``getattr``）调用本方法;
        未实现时自动降级到 ``store()``（向后兼容）。

        画像库**不可用**（init 失败）时也降级到 ``store()``——偏好事实
        不因画像库故障而丢失（review MEDIUM）。

        Args:
            content: 画像内容（一句话）。
            category: 类别, 见 ``UserProfileStore.VALID_CATEGORIES``。
            importance: 重要性 1-10。
            session_id: 可选会话 ID（降级到 store() 时透传）。

        Returns:
            画像 ID；写入被跳过（重复/安全拦截）时返回空串；
            画像库不可用降级到 store() 时返回通用记忆 ID。
        """
        if self.user_profile is None:
            logger.warning("UserProfileStore 不可用, 降级到通用记忆 store()")
            return await self.store(
                content=content,
                session_id=session_id or "",
                importance=importance,
                tags=[category],
            )
        try:
            pid = self.user_profile.add(content, category=category, importance=importance)
            return pid or ""
        except Exception as exc:  # noqa: BLE001 - best-effort 契约
            logger.warning(f"User profile store failed: {exc}")
            return await self.store(
                content=content,
                session_id=session_id or "",
                importance=importance,
                tags=[category],
            )

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
            如果该会话 Token 数量未超过阈值,则不执行任何操作。
        """
        # 检查指定会话工作记忆的 Token 数量（按 session 隔离）
        session_tokens = self.memory_manager.working.total_tokens_for(session_id)
        if session_tokens > 3000:
            logger.info(f"Compressing working memory for session: {session_id}")

            # 调用 ConsolidationPipeline.consolidate() 压缩记忆
            # consolidate() 会:
            # 1. 获取该会话工作记忆中的所有消息
            # 2. 使用 LLM 或简单策略生成摘要
            # 3. 将摘要存储到情景记忆
            # 4. 清空该会话的工作记忆
            self.consolidation.consolidate(self.memory_manager, session_id=session_id)
        else:
            logger.debug(f"Skipping compression: tokens={session_tokens} <= 3000")
