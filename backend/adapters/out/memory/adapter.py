"""Memory Adapter - 记忆端口适配器

将 MemoryPort 协议适配到现有的 MemoryManager 实现。
集成向量检索：store() 自动生成 embedding，retrieve() 包含向量搜索结果。
"""

from __future__ import annotations

import asyncio
import functools
import logging
import os
import threading
from typing import Any, Dict, List, Optional

from backend.domain.memory import MemoryContext
from backend.memory import ConsolidationPipeline, MemoryManager, embedding_queue
from backend.memory.embedder_factory import create_embedder
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
        self.consolidation = ConsolidationPipeline(
            summary_store=getattr(memory_manager, "summary_store", None)
        )
        # E9-1 (P9): 嵌入器工厂 —— 缺省 HashEmbedder (零依赖);
        # SAGE_EMBEDDER=onnx 且模型文件就位时升级为语义嵌入 (512 维,
        # 独立向量表 memories_vec_512, 与 256 维 Hash 向量互不混用)。
        self.embedder = create_embedder()
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
                table_name = (
                    "memories_vec"
                    if self.embedder.dimensions == 256
                    else f"memories_vec_{self.embedder.dimensions}"
                )
                self.vector_store = VectorStore(
                    db, self.embedder, table_name=table_name
                )
                logger.info("VectorStore 已初始化（sqlite-vec 向量检索）")
        except (AttributeError, TypeError):
            # 测试中使用 Mock MemoryManager 时可能没有 episodic 属性
            pass
        if self.vector_store is None:
            logger.debug("VectorStore 未初始化：无可用 Database 实例")

    def reconfigure(self, embedder) -> None:
        """B1 (P11): 热重载嵌入器并按新维度重建向量虚拟表。

        Hash(256) 与 Onnx(512) 维度不同、各用独立表 —— 重配置后旧表的
        向量不迁移 (嵌入语义变更后旧向量无迁移价值), 新写入进新表。
        """
        self.embedder = embedder
        table_name = (
            "memories_vec"
            if embedder.dimensions == 256
            else f"memories_vec_{embedder.dimensions}"
        )
        try:
            db = getattr(self.memory_manager.episodic, "db", None)
        except AttributeError:
            db = None
        if db is not None and hasattr(db, "get_connection"):
            self.vector_store = VectorStore(db, embedder, table_name=table_name)
            logger.info(
                "MemoryAdapter 已重配置: embedder=%s table=%s dims=%s",
                type(embedder).__name__,
                table_name,
                embedder.dimensions,
            )
            self._maybe_start_backfill()
        else:
            logger.warning("MemoryAdapter 重配置: 无可用 db, 向量栈未重建")

    def _maybe_start_backfill(self) -> None:
        """存量记忆缺向量时启动一次性后台回填（守护线程，不阻塞启动）。

        触发条件：向量表条目数 < 主表（episodic+semantic）行数 —— 维度
        重建后或语义 Embedder 首次启用后必然成立。上限
        SAGE_VEC_BACKFILL_MAX（默认 500 条/次），剩余留给下次启动。
        """
        if self._backfill_started or self.vector_store is None:
            return
        try:
            if self.vector_store.pending_backfill_count() <= 0:
                return
        except Exception as e:  # noqa: BLE001 — 回填探测失败不影响主流程
            logger.debug(f"回填探测失败，跳过: {e}")
            return
        self._backfill_started = True
        try:
            max_backfill = int(os.getenv("SAGE_VEC_BACKFILL_MAX", "500"))
        except ValueError:
            max_backfill = 500

        def _run_backfill() -> None:
            try:
                self.vector_store.backfill_from_tables(limit=max_backfill)
            except Exception as e:  # noqa: BLE001 — best-effort
                logger.warning(f"向量回填线程异常: {e}")

        threading.Thread(
            target=_run_backfill, name="memory-vec-backfill", daemon=True
        ).start()
        logger.info("检测到存量记忆缺向量，已启动后台回填（上限 %d 条）", max_backfill)

    async def retrieve(self, query: str, session_id: str, limit: int = 5) -> MemoryContext:
        """检索相关记忆

        多路检索 + RRF 融合：
        1. MemoryManager.recall() — 关键词检索（episodic + semantic）
        2. VectorStore.search() — 向量检索
        3. 两路结果用 RRF 融合，按融合分数排序
        4. 高重要性事实（importance >= 8）提升为核心记忆（core）

        Args:
            query: 查询文本,用于匹配相关记忆
            session_id: 会话 ID(当前实现中未使用,预留用于会话级记忆过滤)
            limit: 每种记忆类型的返回数量限制,默认 5

        Returns:
            MemoryContext: 包含分层记忆的上下文对象
        """
        from backend.memory.fusion import reciprocal_rank_fusion

        logger.debug(f"Retrieving memories for query: {query[:50]}...")

        # 1. 关键词检索（MemoryManager）
        keyword_results = self.memory_manager.recall(query, limit=limit)
        keyword_items = keyword_results.get("episodic", []) + keyword_results.get("semantic", [])

        # 2. 向量检索（VectorStore,批次三 step 5 起按 session 隔离）
        vector_items: List[dict] = []
        if self.vector_store is not None:
            vec_results = self.vector_store.search(
                query, top_k=limit, session_id=session_id
            )
            for vr in vec_results:
                mem_id = vr["memory_id"]
                mem = self.memory_manager.episodic.get_by_id(mem_id)
                if mem is None:
                    mem = self.memory_manager.semantic.get_by_id(mem_id)
                if mem is not None:
                    mem["rrf_score"] = 1.0 / (60 + vr.get("distance", 0) * 100)
                    vector_items.append(mem)

        # 3. RRF 融合两路结果 (T1, P10): 权重按嵌入器能力重配 ——
        #    语义嵌入 (Onnx, 512 维) 向量路是真语义相似度, 权重压过关键词;
        #    字面哈希 (Hash, 256 维) 与关键词路高度重叠, 关键词路更可靠。
        base_weights = (
            [0.3, 0.7]
            if getattr(self.embedder, "is_semantic", False)
            else [0.6, 0.4]
        )
        # B4 (P11): A/B 权重变体 —— 按 query 稳定 hash 二分。
        # A = 嵌入器类型基线权重; B = 均权对照, 离线对比两组召回质量。
        import hashlib as _hl

        variant = (
            "A"
            if int(_hl.md5(query.encode("utf-8")).hexdigest()[:8], 16) % 2 == 0
            else "B"
        )
        if variant == "A":
            weights = list(base_weights)
        else:
            mid = (base_weights[0] + base_weights[1]) / 2
            weights = [mid, mid]
        fused = reciprocal_rank_fusion(
            [keyword_items, vector_items],
            weights=weights,
            k=60,
        )

        logger.info(
            "[retrieval] variant=%s weights=%s keyword_hits=%s vector_hits=%s fused=%s",
            variant,
            weights,
            len(keyword_items),
            len(vector_items),
            len(fused),
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
        self,
        content: str,
        session_id: str,
        importance: int = 5,
        tags: Optional[List[str]] = None,
        source_turn_id: Optional[str] = None,
        source_message_id: Optional[str] = None,
        memory_category: Optional[str] = None,
    ) -> str:
        """存储记忆

        调用 MemoryManager.memorize() 存储记忆到合适的记忆层。
        同时将记忆内容向量化存入 VectorStore，供后续向量检索使用。
        写入前进行安全扫描（Hermes 风格），阻止可疑内容。

        Task 4 / Gap A — ``source_turn_id`` / ``source_message_id`` /
        ``memory_category`` are forwarded through ``metadata`` so the
        MemoryManager → EpisodicMemory chain persists them in the new
        traceability columns.

        Args:
            content: 要存储的记忆内容
            session_id: 关联的会话 ID
            importance: 重要性评分 (1-10),默认 5
            tags: 可选的标签列表,用于分类和检索
            source_turn_id: 该事实来源的 turn ID
            source_message_id: 该事实来源的 message ID
            memory_category: 事实分类（user_pref / project_fact / task_summary /
                cross_session_pattern — 由调用方/extractor 决定）

        Returns:
            str: 生成的记忆 ID,对于工作记忆返回空字符串
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

        # 统一分类（消除规则漂移，与 MemoryManager.classify_memory_type 共用）
        from backend.memory.manager import classify_memory_type
        memory_type = classify_memory_type("auto", importance, content)

        # 构建元数据（含可追溯性字段）
        metadata = {
            "session_id": session_id,
            "tags": tags or [],
            "source_turn_id": source_turn_id,
            "source_message_id": source_message_id,
            "memory_category": memory_category,
            "memory_type": memory_type,
        }

        # 调用 MemoryManager.memorize() 存储记忆（透传 memory_type 以与 module-level classify 对齐）
        memory_id = self.memory_manager.memorize(
            content=content, memory_type=memory_type, importance=importance, metadata=metadata
        )

        # 向量化存储（仅持久层记忆:工作记忆合成 id 不入向量库）
        # T2 (P10): 语义嵌入 (Onnx) 的单条推理 ~10-50ms, 同步执行会阻塞
        # save 路径 (事件循环) —— 走后台编码队列异步落库 (best-effort);
        # 字面哈希编码 ~µs 级, 保持同步 (写入即见, 无队列延迟)。
        if self.vector_store is not None and memory_id and memory_type in ("episodic", "semantic"):
            if getattr(self.embedder, "is_semantic", False):
                embedding_queue.enqueue(
                    self.vector_store.add,
                    memory_id,
                    content,
                    memory_type=memory_type,
                    session_id=session_id,
                )
            else:
                self.vector_store.add(
                    memory_id, content, memory_type=memory_type, session_id=session_id
                )

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

    # ------------------------------------------------------------------ #
    # Task 5 / Gap E — traceability queries (by-turn / category / session)
    # ------------------------------------------------------------------ #
    # The underlying EpisodicMemory methods are synchronous SQLite calls;
    # they run in a worker thread via asyncio.to_thread so the event loop
    # stays responsive (consistent with commit a7baaf98's offload policy).

    async def find_by_turn(
        self, turn_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """返回 source_turn_id == turn_id 的所有记忆（最新在前）。"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            functools.partial(
                self.memory_manager.episodic.find_by_turn, turn_id, limit=limit
            ),
        )

    async def find_by_category(
        self, category: str, *, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """返回按 memory_category 过滤的记忆（最新在前）。"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            functools.partial(
                self.memory_manager.episodic.find_by_category,
                category,
                limit=limit,
            ),
        )

    async def find_by_category_and_session(
        self, category: str, session_id: str, *, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """返回按 category AND session_id 过滤的记忆（最新在前）。"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            functools.partial(
                self.memory_manager.episodic.find_by_category_and_session,
                category,
                session_id,
                limit=limit,
            ),
        )
