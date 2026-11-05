"""
Memory Manager - 记忆管理器
统一管理三层记忆系统
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import sqlite3
import time
import uuid
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from backend.agents.memory_policy import (
    includes_private_reads,
    parse_memory_policy,
    resolve_write_agent_id,
)
from backend.memory import scope as memory_scope
from backend.memory.episodic import EpisodicMemory
from backend.memory.semantic import SemanticMemory
from backend.memory.summary import SessionSummaryStore
from backend.memory.working import WorkingMemory, normalize_session_id

logger = logging.getLogger(__name__)


def classify_memory_type(memory_type: str, importance: int, content: str) -> str:
    """统一的记忆分类规则（MemoryManager 与 MemoryAdapter 共用的单一事实来源）

    规则（与历史行为保持一致）：
    - 显式指定的非 auto 类型原样透传
    - importance >= 8 → semantic（高重要性事实）
    - 短内容（len < 200）且 importance < 5 → working（低重要性短期记忆）
    - 其余 → episodic

    Args:
        memory_type: 调用方声明的目标类型（'working'/'episodic'/'semantic'/'auto'）
        importance: 重要性评分 1-10
        content: 记忆内容

    Returns:
        最终落库的记忆类型
    """
    if memory_type and memory_type != "auto":
        return memory_type

    # 高重要性 → 语义记忆
    if importance >= 8:
        return "semantic"

    # 低重要性短记忆 → 工作记忆
    if len(content) < 200 and importance < 5:
        return "working"

    # 默认 → 情景记忆
    return "episodic"


class MemoryManager:
    """
    记忆管理器 - 统一管理三层记忆

    负责:
    1. 协调三层记忆的读写
    2. 记忆压缩和归档
    3. 记忆检索和召回
    4. 记忆重要性评估
    """

    def __init__(
        self,
        working: WorkingMemory,
        episodic: EpisodicMemory,
        semantic: SemanticMemory,
        summary_store: Optional[SessionSummaryStore] = None,
        allowed_tiers: Optional[Iterable[str]] = None,
        memory_policy: Optional[Any] = None,
        embedder=None,
    ):
        """
        初始化记忆管理器

        Args:
            working: 工作记忆实例
            episodic: 情景记忆实例
            semantic: 语义记忆实例
            summary_store: 会话摘要 store（批次三 step 5）；可选，向后兼容
                未注入 store 的旧调用方；没有 store 时 ``get_context`` 不
                注入 ``【会话摘要】`` 段。
            allowed_tiers: M0 (2026-11-03) 专家记忆读权限 —— 允许读取的
                记忆层（``working`` / ``episodic`` / ``semantic``）。
                ``None``（默认）= **不限制**，保持既有行为不变；
                空列表 = **禁止一切记忆读取**（专家显式声明"无记忆权限"）。
            memory_policy: M3 (2026-11-04) 专家记忆策略（dict / JSON 字符串
                / ``MemoryPolicy``）。``None``（默认）= 不限制，保持既有
                行为不变。给定时读侧按 ``read_scopes`` 收窄、写侧按
                ``write_scope`` 决定私有/共享归属。
            embedder: 语义嵌入器实例，或返回实例的可调用（``() -> Embedder``）；
                透传给冲突消解器做语义去重判定。缺省 / 非语义嵌入器时
                冲突消解退化为纯字面判定（行为与改造前一致）。
        """
        self.working = working
        self.episodic = episodic
        self.semantic = semantic
        self.summary_store = summary_store
        # M0 (2026-11-03): 读层权限闸门。None = 不限制（默认，向后兼容）。
        self.allowed_tiers: Optional[Set[str]] = (
            {str(t).strip().lower() for t in allowed_tiers if str(t).strip()}
            if allowed_tiers is not None
            else None
        )
        # M3 (2026-11-04): 专家记忆策略。None = 未配置（历史行为）。
        self.memory_policy = (
            parse_memory_policy(memory_policy)
            if memory_policy is not None
            else None
        )
        self.embedder = embedder
        # Lazily-created ConsolidationPipeline (F2) — built on first use so
        # the constructor stays lightweight and test-friendly.
        self._consolidation_pipeline = None
        # P3 (Mem0 风格) 冲突消解器: 惰性构造（首次判定时才建, 见
        # get_conflict_resolver）; 仅服务 episodic/semantic 持久层。
        self._conflict_resolver = None

    # ------------------------------------------------------------------ #
    # M0: 记忆读层权限（memory_access）
    # ------------------------------------------------------------------ #

    def set_allowed_tiers(self, tiers: Optional[Iterable[str]]) -> None:
        """设置允许读取的记忆层。

        Args:
            tiers: ``working`` / ``episodic`` / ``semantic`` 的任意组合；
                ``None`` = 不限制；空列表 = 禁止一切记忆读取。
        """
        if tiers is None:
            self.allowed_tiers = None
            return
        self.allowed_tiers = {
            str(t).strip().lower() for t in tiers if str(t).strip()
        }

    def _tier_allowed(self, tier: str) -> bool:
        """该记忆层当前是否可读。``allowed_tiers is None`` → 恒真。"""
        if self.allowed_tiers is None:
            return True
        return tier.lower() in self.allowed_tiers

    # ------------------------------------------------------------------ #
    # M3 (2026-11-04): 专家记忆策略（memory_policy）
    # ------------------------------------------------------------------ #

    def set_memory_policy(self, policy: Optional[Any]) -> None:
        """注入 / 清除专家记忆策略。``None`` = 不限制（历史行为）。"""
        self.memory_policy = (
            parse_memory_policy(policy) if policy is not None else None
        )

    def _resolve_write_agent(self, agent_id: Optional[str]) -> Optional[str]:
        """写归属按策略归一：``write_scope != specialist`` 时强制共享。

        未配置策略（historical path）或 ``agent_id`` 为空时原样返回
        —— 显式 ``None`` 永远保持共享，策略不会凭空捏造私有归属。
        """
        if not agent_id:
            return None
        return resolve_write_agent_id(self.memory_policy, agent_id)

    def _read_include_private(self, include_private: bool) -> bool:
        """读收窄的单一判定点：调用方显式关闭 **或** 策略缺 specialist。"""
        if not include_private:
            return False
        return includes_private_reads(self.memory_policy)

    def remember(
        self,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        agent_id: Optional[str] = None,
    ) -> str:
        """
        将内容存入情景记忆

        Args:
            content: 记忆内容
            metadata: 额外元数据
            agent_id: M3 归属专家。``None``（默认）= 共享层；
                给定时按 ``memory_policy.write_scope`` 决定私有/共享。

        Returns:
            生成的记忆 ID
        """
        importance = 5
        session_id = None
        memory_type = "conversation"

        if metadata:
            importance = metadata.get("importance", 5)
            session_id = metadata.get("session_id")
            memory_type = metadata.get("memory_type", "conversation")

        return self.episodic.save(
            content=content,
            importance=importance,
            metadata=metadata,
            session_id=session_id,
            memory_type=memory_type,
            agent_id=self._resolve_write_agent(agent_id),
        )

    async def aremember(
        self,
        content: Optional[str] = None,
        *,
        metadata: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
        source_turn_id: Optional[str] = None,
        source_message_id: Optional[str] = None,
        memory_category: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> str:
        """Async remember() — Task 4 / Gap A entry point used by the
        MemoryLifecycleManager.

        Accepts the new traceability kwargs (``source_turn_id`` /
        ``source_message_id`` / ``memory_category``) and threads them down
        to ``EpisodicMemory.save()`` so the new columns get populated.

        Named ``aremember`` (not ``remember``) so the lifecycle mock in
        step 5's brief — which redefines ``remember`` as ``async`` —
        keeps working: the contract is that whatever attribute the
        lifecycle calls (``remember``) must be awaitable, but the real
        type keeps the sync ``remember`` for legacy callers and exposes
        the async one under a new name. Tests/lifecycle always
        await ``self._memory.remember(...)`` but in practice the FakeMemory
        in tests defines an ``async def remember``; production code path
        uses ``self._memory.aremember(...)``.

        Implementation note — async event-loop safety: ``EpisodicMemory.save``
        is a synchronous ``sqlite3`` INSERT (cursor.execute + commit). If
        invoked directly on the event-loop thread it stalls every other
        coroutine while the disk fsyncs. We therefore run it through
        ``asyncio.to_thread`` so the blocking I/O is offloaded to a worker
        thread; the awaited coroutine yields and the loop keeps servicing
        other requests. The DB connection is acquired lazily inside the
        worker thread via ``EpisodicMemory.save → self.db.get_connection``,
        so the single-connection / WAL contract (and ``check_same_thread=
        False``) is preserved without any threading-model change.
        """
        importance = 5
        resolved_session_id = session_id
        memory_type = "conversation"
        if metadata:
            importance = metadata.get("importance", 5)
            if resolved_session_id is None:
                resolved_session_id = metadata.get("session_id")
            memory_type = metadata.get("memory_type", "conversation")

        # Snapshot kwargs in the closure so the worker thread sees the same
        # values the caller intended — defensive against any mutation
        # between scheduling and execution.
        episodic = self.episodic
        write_agent_id = self._resolve_write_agent(agent_id)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            functools.partial(
                episodic.save,
                content=content,
                importance=importance,
                metadata=metadata,
                session_id=resolved_session_id,
                memory_type=memory_type,
                source_turn_id=source_turn_id,
                source_message_id=source_message_id,
                memory_category=memory_category,
                agent_id=write_agent_id,
            ),
        )

    async def aremember_with_conflict_check(
        self,
        content: str,
        *,
        session_id: Optional[str] = None,
        source_turn_id: Optional[str] = None,
        source_message_id: Optional[str] = None,
        memory_category: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        importance: int = 5,
        tags: Optional[List[str]] = None,
        scope: Optional[str] = None,
        project_key: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Async conflict-aware remember — auto-memory 写入的唯一入口。

        与 ``memorize_with_conflict_check`` 的差异：
        * 接受 ``source_turn_id`` / ``source_message_id`` / ``memory_category``，
          在 ADD 路径下经 ``aremember`` 透传到 ``EpisodicMemory.save``，保留溯源；
        * 冲突判定与 ``apply_update`` 的 sqlite 调用整体放进
          ``run_in_executor``，避免阻塞事件循环。

        Returns:
            ``(memory_id, op)``，op ∈ {add, update, noop}。NOOP 返回既有 id，
            调用方可据此决定是否跳过后续处理。
        """
        from backend.memory.conflict import OP_ADD, OP_NOOP, OP_UPDATE

        resolved_metadata = metadata or {}
        resolved_importance = importance or resolved_metadata.get("importance", 5)

        resolved = classify_memory_type("auto", resolved_importance, content)
        if resolved not in ("episodic", "semantic"):
            # working / 直接透传：不走冲突消解，保留 traceability
            mid = await self.aremember(
                content=content,
                session_id=session_id,
                source_turn_id=source_turn_id,
                source_message_id=source_message_id,
                memory_category=memory_category,
                metadata={**resolved_metadata, "importance": resolved_importance},
                agent_id=agent_id,
            )
            return mid or "", OP_ADD

        loop = asyncio.get_event_loop()
        try:
            decision = await loop.run_in_executor(
                None,
                functools.partial(
                    self.resolve_conflicts,
                    content,
                    session_id=session_id,
                    scope=scope,
                    project_key=project_key,
                ),
            )
        except Exception:  # noqa: BLE001 — 冲突判定失败时退回 ADD，不要丢记忆
            logger.exception("aremember_with_conflict_check: resolve failed; falling back to ADD")
            decision = None

        if decision is not None and decision.op == OP_NOOP:
            return (decision.targets[0].id if decision.targets else ""), OP_NOOP

        if decision is not None and decision.op == OP_UPDATE:
            def _apply_update() -> Tuple[Optional[str], str]:
                return self.get_conflict_resolver().apply_update(
                    decision,
                    self.memorize,
                    content=content,
                    memory_type=resolved,
                    importance=resolved_importance,
                    tags=tags,
                    metadata=resolved_metadata,
                    session_id=session_id,
                )

            try:
                new_id, op = await loop.run_in_executor(None, _apply_update)
                return new_id or "", op
            except Exception:  # noqa: BLE001
                logger.exception(
                    "aremember_with_conflict_check: apply_update failed; falling back to ADD"
                )

        mid = await self.aremember(
            content=content,
            session_id=session_id,
            source_turn_id=source_turn_id,
            source_message_id=source_message_id,
            memory_category=memory_category,
            metadata={**resolved_metadata, "importance": resolved_importance},
            agent_id=agent_id,
        )
        return mid or "", OP_ADD

    async def consolidate(self, session_id: Optional[str] = None) -> Any:
        """Async session-end consolidation (F2).

        Thin wrapper over :class:`ConsolidationPipeline` so the
        MemoryLifecycleManager / session-end watchdog can drive real
        consolidation without the pipeline being coupled into the lifecycle.
        The synchronous ``ConsolidationPipeline.consolidate`` is offloaded to
        a worker thread via ``asyncio.to_thread`` so the event loop is not
        stalled by the SQLite work.
        """
        if self._consolidation_pipeline is None:
            from backend.memory.consolidation import ConsolidationPipeline

            self._consolidation_pipeline = ConsolidationPipeline()
        pipeline = self._consolidation_pipeline
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, pipeline.consolidate, self, session_id)

    async def snapshot(self, session_id: Optional[str] = None) -> None:
        """Async pre-compress snapshot (F2).

        Persists the current working-memory state to the
        ``working_memory_snapshot`` table (no-op when the working memory was
        built without a db — the persistent-snapshot feature is opt-in).
        Offloaded to a worker thread to keep the event loop responsive.
        """

        def _snap() -> None:
            save = getattr(self.working, "_save_snapshot", None)
            if save is not None:
                save()

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _snap)

    def memorize(
        self,
        content: str,
        memory_type: str = "auto",
        importance: int = 5,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        segment_id: int = 0,
        scope: Optional[str] = None,
        project_key: Optional[str] = None,
        supersedes_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        通用记忆存储接口

        Args:
            content: 记忆内容
            memory_type: 'working' | 'episodic' | 'semantic' | 'auto'
            importance: 重要性 1-10
            tags: 标签列表
            metadata: 额外元数据
            session_id: 可选会话 ID，用于工作记忆按会话隔离 / 情景记忆关联会话
            segment_id: 上下文段 id（PF-2 context-isolation）。默认 0 — 向后兼容
                既有调用方；同会话多段时区分工作记忆的可见范围。仅当
                ``resolved == "working"`` 时生效（episodic/semantic 无段概念）。
            scope: P1 作用域 ('user'|'project'|'global')，None → 存储层
                按会话 workspace 绑定自动判定
            project_key: 项目目录（scope='project' 时生效）
            supersedes_id: P3 冲突消解——本条记忆取代的旧记忆 ID
                （旧条由调用方先行 invalidate()）
            agent_id: M3 归属专家。``None``（默认）= 共享层；
                给定时按 ``memory_policy.write_scope`` 决定私有/共享。

        Returns:
            记忆 ID：
            - episodic / semantic：数据库持久 ID
            - working：合成 ID ``wm:<session>:<seq>``（仅用于日志/回显，非持久主键）
        """
        # 统一分类（模块级函数，与 MemoryAdapter 同一套规则）
        resolved = classify_memory_type(memory_type, importance, content)
        write_agent_id = self._resolve_write_agent(agent_id)

        if resolved == "working":
            seq = self.working.add(
                session_id, {"role": "system", "content": content}, segment_id=segment_id
            )
            sid = self.working.resolve_session_id(session_id)
            return f"wm:{sid}:{seq}"

        elif resolved == "episodic":
            meta = dict(metadata or {})
            if tags:
                meta["tags"] = tags
            sid = session_id or meta.get("session_id")
            # F3 (win7) — forward traceability fields from metadata so the
            # adapter.store → memorize → episodic.save chain actually
            # populates the three new columns instead of silently dropping
            # them (the fields default to None when absent → backward compat).
            return self.episodic.save(
                content=content,
                importance=importance,
                metadata=meta,
                session_id=sid,
                source_turn_id=meta.get("source_turn_id"),
                source_message_id=meta.get("source_message_id"),
                memory_category=meta.get("memory_category"),
                scope=scope,
                project_key=project_key,
                supersedes_id=supersedes_id,
                agent_id=write_agent_id,
            )

        elif resolved == "semantic":
            meta = metadata or {}
            return self.semantic.save(
                content=content,
                summary=None,
                tags=tags,
                session_id=session_id or meta.get("session_id"),
                scope=scope,
                project_key=project_key,
                supersedes_id=supersedes_id,
                agent_id=write_agent_id,
            )

        else:
            logger.warning(f"未知的记忆类型: {resolved}")
            return None

    # ---- P3 冲突消解（Mem0 风格 ADD / UPDATE / NOOP） ----------------------

    def get_conflict_resolver(self):
        """惰性构造并复用 MemoryConflictResolver。"""
        if self._conflict_resolver is None:
            from backend.memory.conflict import MemoryConflictResolver

            self._conflict_resolver = MemoryConflictResolver(
                self.episodic, self.semantic, embedder=self.embedder
            )
        return self._conflict_resolver

    def resolve_conflicts(
        self,
        content: str,
        session_id: Optional[str] = None,
        scope: Optional[str] = None,
        project_key: Optional[str] = None,
        agent_id: Optional[str] = None,
    ):
        """只判定不写入：返回 ``Decision``（op + targets）。

        供 API / P4 反思任务在真正落库前探测冲突；异常原样上抛由调用方兜底。
        ``agent_id`` 限制候选范围（私有 ∪ 共享），防止一个专家的写入
        UPDATE/NOOP 掉另一个专家的私有记忆。
        """
        return self.get_conflict_resolver().resolve(
            content,
            session_id=session_id,
            scope=scope,
            project_key=project_key,
            agent_id=agent_id,
        )

    def memorize_with_conflict_check(
        self,
        content: str,
        memory_type: str = "auto",
        importance: int = 5,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        scope: Optional[str] = None,
        project_key: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> Tuple[str, str]:
        """带 P3 冲突消解的记忆写入。

        工作记忆与未命中冲突的持久层记忆走原 ``memorize`` 路径（行为不变）；
        NOOP 复用既有记忆（不写）；UPDATE 写新行并把同归属旧行 invalidate,
        新行携带 ``supersedes_id``。

        Returns:
            ``(memory_id, op)``，op ∈ {add, update, noop}；
            NOOP 无既有 ID 可复用时 memory_id 为空串。
        """
        from backend.memory.conflict import OP_ADD, OP_NOOP, OP_UPDATE

        resolved = classify_memory_type(memory_type, importance, content)
        if resolved not in ("episodic", "semantic"):
            mid = self.memorize(
                content,
                memory_type=memory_type,
                importance=importance,
                tags=tags,
                metadata=metadata,
                session_id=session_id,
                scope=scope,
                project_key=project_key,
                agent_id=agent_id,
            )
            return mid or "", OP_ADD

        decision = self.resolve_conflicts(
            content,
            session_id=session_id,
            scope=scope,
            project_key=project_key,
            agent_id=agent_id,
        )
        if decision.op == OP_NOOP:
            return (decision.targets[0].id if decision.targets else ""), OP_NOOP
        if decision.op == OP_UPDATE:
            new_id, op = self.get_conflict_resolver().apply_update(
                decision,
                self.memorize,
                content=content,
                memory_type=resolved,
                importance=importance,
                tags=tags,
                metadata=metadata,
                session_id=session_id,
                agent_id=agent_id,
            )
            return new_id or "", op

        mid = self.memorize(
            content,
            memory_type=memory_type,
            importance=importance,
            tags=tags,
            metadata=metadata,
            session_id=session_id,
            scope=scope,
            project_key=project_key,
            agent_id=agent_id,
        )
        return mid or "", OP_ADD

    def _classify_memory_type(self, content: str, importance: int) -> str:
        """
        自动分类记忆类型（模块级 classify_memory_type 的薄包装，向后兼容保留）

        Args:
            content: 记忆内容
            importance: 重要性评分

        Returns:
            记忆类型
        """
        return classify_memory_type("auto", importance, content)

    def recall(
        self,
        query: str,
        limit: int = 5,
        memory_types: Optional[List[str]] = None,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        include_private: bool = True,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        检索记忆

        Args:
            query: 查询文本
            limit: 每种记忆类型的返回数量
            memory_types: 要检索的记忆类型列表，None 表示全部
            session_id: 可选会话 ID，限定工作记忆的检索范围
            agent_id: M3 当前专家（私有 ∪ 共享）；None 不限制（历史行为）
            include_private: 策略收窄——False 时仅返回共享行

        Returns:
            包含各类记忆检索结果的字典
        """
        results = {"working": [], "episodic": [], "semantic": []}
        read_include_private = self._read_include_private(include_private)

        # 确定要检索的类型
        if memory_types is None:
            memory_types = ["working", "episodic", "semantic"]

        # M0 (2026-11-03): 读层权限闸门 —— 专家无权读取的记忆层在此
        # 直接剔除，不下发到检索后端。
        if self.allowed_tiers is not None:
            memory_types = [
                t for t in memory_types if self._tier_allowed(str(t))
            ]

        # 工作记忆 - 简单的上下文匹配（按 session 隔离）
        if "working" in memory_types:
            working_context = self.working.get_context(session_id)
            if query:
                # 在工作记忆中简单搜索
                for msg in reversed(working_context):
                    if query.lower() in msg.get("content", "").lower():
                        results["working"].append(msg)
                        if len(results["working"]) >= limit:
                            break
            else:
                results["working"] = working_context[-limit:]

        # 情景记忆 - SQLite LIKE 搜索（软过滤：跨会话召回）
        if "episodic" in memory_types:
            # 不传递 session_id，允许跨会话知识召回
            # 软过滤评分在 MemoryAdapter.retrieve() 中进行
            results["episodic"] = self.episodic.search(
                query=query,
                limit=limit * 2,  # 放宽候选数量
                session_id=None,  # 不按 session 严格过滤
                agent_id=agent_id,
                include_private=read_include_private,
            )

        # 语义记忆 - FTS5 全文搜索（软过滤：跨会话召回）
        if "semantic" in memory_types:
            # 不传递 session_id，允许跨会话知识召回
            # 软过滤评分在 MemoryAdapter.retrieve() 中进行
            results["semantic"] = self.semantic.search(
                query=query,
                limit=limit * 2,  # 放宽候选数量
                session_id=None,  # 不按 session 严格过滤
                agent_id=agent_id,
                include_private=read_include_private,
            )

        return results

    def get_context(
        self,
        limit: int = 10,
        session_id: Optional[str] = None,
        segment_id: Optional[int] = None,
        agent_id: Optional[str] = None,
        include_private: bool = True,
    ) -> str:
        """获取上下文用于 Agent（仅文本；需结构化命中用
        :meth:`get_context_with_hits`）。"""
        text, _ = self.get_context_with_hits(
            limit,
            session_id,
            segment_id,
            agent_id=agent_id,
            include_private=include_private,
        )
        return text

    def get_context_with_hits(
        self,
        limit: int = 10,
        session_id: Optional[str] = None,
        segment_id: Optional[int] = None,
        agent_id: Optional[str] = None,
        include_private: bool = True,
    ) -> Tuple[str, List[Dict[str, str]]]:
        """
        获取上下文用于 Agent，同时返回实际注入的结构化记忆命中。

        R99 (2026-09-23): 供调用方（legacy producer 的 memory_used 事件）
        复用同一次检索，替代原先独立的 ``recall()`` 第二次查询 —— 召回
        展示从此与注入内容严格同源。

        Args:
            limit: 上下文消息数量限制
            session_id: 可选会话 ID，限定工作记忆上下文的范围
            segment_id: 可选段 id（Task 14 context-isolation）。
                透传给 :meth:`WorkingMemory.get_context`，仅返回该段消息。
                ``None`` → 返回该会话全部段（向后兼容）。
            agent_id: M3 当前专家（私有 ∪ 共享）；None 不限制（历史行为）
            include_private: 策略收窄——False 时仅返回共享行

        Returns:
            ``(格式化的上下文字符串, 实际注入的结构化记忆命中列表)`` ——
            命中条目形如 ``{"id": str, "memory_type": str, "preview": str}``。
        """
        parts = []
        read_include_private = self._read_include_private(include_private)
        # R99: 与 parts 同步收集实际注入的记忆条目（id 缺失的来源合成稳定 id，
        # 前端 memory_used 校验要求每项有字符串 id）。
        hits: List[Dict[str, str]] = []

        # 用户画像（USER.md 概念）: 持久画像快照置于上下文顶部（best-effort）。
        # 让 legacy SageAgent（经 memory_manager.get_context）与 hex
        # ChatService（经 MemoryAdapter.retrieve → MemoryContext.core）都能
        # 注入同一份用户知识。快照冻结于 load(), 中途写入不改（保 prefix cache）。
        # M0: 画像属于长期语义知识，按 semantic 层权限闸门。
        if self._tier_allowed("semantic"):
            try:
                from backend.memory.user_profile import get_user_profile

                profile_snapshot = get_user_profile().get_snapshot()
                if profile_snapshot:
                    parts.append(profile_snapshot)
            except Exception as exc:
                logger.debug(f"用户画像快照注入失败: {exc}")

        # P2 项目画像: 会话绑定了工作区才注入该项目自己的快照;
        # 未绑定/解析失败恒为空串, 绝不注入"别的项目"的画像。
        # M0: 同样按 semantic 层权限闸门。
        if self._tier_allowed("semantic"):
            try:
                project_key = memory_scope.resolve_session_project_key(
                    getattr(self.episodic, "db", None), session_id
                )
                if project_key:
                    from backend.memory.project_profile import get_project_profile

                    project_snapshot = get_project_profile().get_snapshot(project_key)
                    if project_snapshot:
                        parts.append(project_snapshot)
            except Exception as exc:
                logger.debug(f"项目画像快照注入失败: {exc}")

        # 获取工作记忆上下文（按 session 隔离 + Task 14 按 segment_id 隔离）
        # M0: working 层权限闸门。
        working_context = (
            self.working.get_context(session_id, limit=limit, segment_id=segment_id)
            if self._tier_allowed("working")
            else []
        )
        if working_context:
            parts.append("【当前对话】")
            for msg in working_context:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                parts.append(f"- [{role}]: {content[:100]}...")
                hits.append(
                    {
                        "id": f"working-{len(hits)}",
                        "memory_type": "working",
                        "preview": f"[{role}]: {content[:100]}",
                    }
                )

        # 批次三 step 5：会话摘要，介于 working 与 episodic/semantic 之间。
        # 只注入当前 session 的 READY 摘要，FAILED / PENDING 不注入
        # （失败摘要只用于诊断，不假装为普通事实）。
        # 未注入 summary_store 或 session_id 为空时整段跳过 ——
        # 永不注入"全部 session 的最新摘要"以避免跨 session 串味。
        # M0: 摘要由本会话对话派生，归入 working 层权限闸门。
        if self.summary_store is not None and session_id and self._tier_allowed("working"):
            try:
                latest_ready = self.summary_store.get_latest_ready(session_id)
            except Exception as exc:
                logger.warning(f"读取会话摘要失败: {exc}")
                latest_ready = None
            if latest_ready is not None and latest_ready.content:
                parts.append("\n【会话摘要】")
                parts.append(f"- {latest_ready.content}")
                hits.append(
                    {
                        "id": f"summary-{getattr(latest_ready, 'id', len(hits))}",
                        "memory_type": "summary",
                        "preview": latest_ready.content[:100],
                    }
                )

        # 获取最近的 episodic 记忆
        # M0: episodic 层权限闸门。
        try:
            recent_episodic = (
                self.episodic.get_recent(
                    limit=3,
                    session_id=session_id,
                    agent_id=agent_id,
                    include_private=read_include_private,
                )
                if self._tier_allowed("episodic")
                else []
            )
            if recent_episodic:
                parts.append("\n【相关经历】")
                for mem in recent_episodic:
                    summary = mem.get("summary", mem.get("content", ""))[:100]
                    parts.append(f"- {summary}...")
                    hits.append(
                        {
                            "id": str(mem.get("id") or f"episodic-{len(hits)}"),
                            "memory_type": str(
                                mem.get("memory_type") or "episodic"
                            ),
                            "preview": summary,
                        }
                    )
        except Exception as e:
            logger.warning(f"获取情景记忆失败: {e}")

        # 获取最近的 semantic 记忆
        # M0: semantic 层权限闸门。
        try:
            recent_semantic = (
                self.semantic.get_recent(
                    limit=3,
                    session_id=session_id,
                    agent_id=agent_id,
                    include_private=read_include_private,
                )
                if self._tier_allowed("semantic")
                else []
            )
            if recent_semantic:
                parts.append("\n【相关知识】")
                for mem in recent_semantic:
                    summary = mem.get("summary", mem.get("content", ""))[:100]
                    parts.append(f"- {summary}...")
                    hits.append(
                        {
                            "id": str(mem.get("id") or f"semantic-{len(hits)}"),
                            "memory_type": str(
                                mem.get("memory_type") or "semantic"
                            ),
                            "preview": summary,
                        }
                    )
        except Exception as e:
            logger.warning(f"获取语义记忆失败: {e}")

        return ("\n".join(parts) if parts else ""), hits

    def compress(
        self,
        session_id: Optional[str] = None,
        segment_id: Optional[int] = None,
        agent_id: Optional[str] = None,
    ) -> None:
        """
        压缩指定会话的工作记忆
        生成摘要并保存到情景记忆

        Args:
            session_id: 会话 ID（None → 默认会话），仅压缩并清空该会话
            segment_id: 上下文段 id（PF-3 context-isolation）。若指定，则仅压缩
                并清空该段的工作记忆（使用 ``clear_segment``）；若为 None，则
                维持默认行为，清空整个会话的工作记忆（向后兼容）。
            agent_id: M3 归属专家（None → 共享层）
        """
        messages = self.working.get_context(
            session_id, segment_id=segment_id
        )

        if not messages:
            return

        # 生成摘要
        summary = self.working.get_summary(session_id)

        # 将摘要存入情景记忆
        try:
            self.episodic.save(
                content=f"对话摘要: {summary}",
                importance=5,
                metadata={"source": "auto_compress", "message_count": len(messages)},
                session_id=session_id,
                agent_id=self._resolve_write_agent(agent_id),
            )

            # 清空工作记忆：段级或会话级
            if segment_id is not None:
                self.working.clear_segment(session_id, segment_id)
            else:
                self.working.clear(session_id)

            logger.info(
                f"工作记忆已压缩: session={normalize_session_id(session_id)}, "
                f"segment={segment_id}, 保存了 {len(messages)} 条消息的摘要"
            )
        except Exception as e:
            logger.error(f"压缩工作记忆失败: {e}")

    def add_to_working(
        self,
        role: str,
        content: str,
        session_id: Optional[str] = None,
        segment_id: int = 0,
    ) -> None:
        """
        添加消息到工作记忆

        Args:
            role: 角色 (user/assistant/system)
            content: 消息内容
            session_id: 可选会话 ID（None → 默认会话）
            segment_id: 上下文段 id（PF-2 context-isolation）。默认 0 — 向后兼容
                既有调用方；同会话多段时区分工作记忆的可见范围。
        """
        self.working.add(
            session_id, {"role": role, "content": content}, segment_id=segment_id
        )

    def resolve_project_key(self, session_id: Optional[str]) -> Optional[str]:
        """解析会话当前归属的项目目录（P1 作用域轴）。"""
        return memory_scope.resolve_session_project_key(
            getattr(self.episodic, "db", None), session_id
        )

    def search_memories(
        self,
        query: str,
        memory_type: Optional[str] = None,
        limit: int = 20,
        session_id: Optional[str] = None,
        scope: Optional[str] = None,
        agent_id: Optional[str] = None,
        include_private: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        搜索记忆的统一接口

        当 memory_type 为 None 或 'working' 时，把对应会话的工作记忆条目
        并入结果，每条标记 ``memory_type='working'``、``source='working_memory'``
        （修复"工作记忆检索不可见"缺陷）。

        Args:
            query: 搜索关键词（空字符串表示不过滤工作记忆条目）
            memory_type: 可选，限定记忆类型
            limit: 返回数量限制
            session_id: 可选会话 ID，用于工作记忆隔离
            scope: P1 作用域轴跨会话检索 ('user'|'project'|'global')。
                'project' 时以 session_id 解析当前项目目录做过滤；
                给定时不叠加 session 隔离（工作记忆无作用域概念，跳过）
            agent_id: M3 当前专家（私有 ∪ 共享）；None 不限制（历史行为）
            include_private: 策略收窄——False 时仅返回共享行

        Returns:
            记忆列表
        """
        read_include_private = self._read_include_private(include_private)
        if scope in memory_scope.VALID_SCOPES:
            return self._search_by_scope(
                query,
                memory_type,
                limit,
                session_id,
                scope,
                agent_id=agent_id,
                include_private=read_include_private,
            )

        # M0 (2026-11-03): 读层权限闸门 —— 指定了无权读取的层直接返回空，
        # 避免把"禁止"变成"检索后过滤"（后者仍会把内容读进进程）。
        if (
            self.allowed_tiers is not None
            and memory_type is not None
            and not self._tier_allowed(str(memory_type))
        ):
            return []

        if memory_type == "episodic":
            return self.episodic.search(
                query,
                limit=limit,
                session_id=session_id,
                agent_id=agent_id,
                include_private=read_include_private,
            )
        elif memory_type == "semantic":
            return self.semantic.search(
                query,
                limit=limit,
                session_id=session_id,
                agent_id=agent_id,
                include_private=read_include_private,
            )

        results: List[Dict[str, Any]] = []

        # 工作记忆（memory_type 为 None 或 'working'），按 session 隔离
        if memory_type in (None, "working") and self._tier_allowed("working"):
            sid = self.working.resolve_session_id(session_id)
            for msg in self.working.get_context(session_id):
                if query and query.lower() not in msg.get("content", "").lower():
                    continue
                entry = dict(msg)
                entry.setdefault("id", f"wm:{sid}:{entry.get('seq', 0)}")
                entry["memory_type"] = "working"
                entry["source"] = "working_memory"
                results.append(entry)

        if memory_type == "working":
            return results[:limit]

        # memory_type 为 None：搜索所有持久层并与工作记忆合并
        if self._tier_allowed("episodic"):
            results.extend(
                self.episodic.search(
                    query,
                    limit=limit,
                    session_id=session_id,
                    agent_id=agent_id,
                    include_private=read_include_private,
                )
            )
        if self._tier_allowed("semantic"):
            results.extend(
                self.semantic.search(
                    query,
                    limit=limit,
                    session_id=session_id,
                    agent_id=agent_id,
                    include_private=read_include_private,
                )
            )
        return results[:limit]

    def _search_by_scope(
        self,
        query: str,
        memory_type: Optional[str],
        limit: int,
        session_id: Optional[str],
        scope: str,
        agent_id: Optional[str] = None,
        include_private: bool = True,
    ) -> List[Dict[str, Any]]:
        """作用域轴跨会话检索（P1）。工作记忆无作用域概念，直接跳过。"""
        project_key = None
        if scope == memory_scope.SCOPE_PROJECT:
            project_key = self.resolve_project_key(session_id)
            if not project_key:
                # 当前会话不属于任何项目 → 无项目记忆可检索
                return []
        if memory_type == "working":
            return []
        results: List[Dict[str, Any]] = []
        # M0: 作用域轴检索同样受读层权限闸门约束。
        if memory_type in (None, "episodic") and self._tier_allowed("episodic"):
            results.extend(
                self.episodic.search(
                    query,
                    limit=limit,
                    scope=scope,
                    project_key=project_key,
                    agent_id=agent_id,
                    include_private=include_private,
                )
            )
        if memory_type in (None, "semantic") and self._tier_allowed("semantic"):
            results.extend(
                self.semantic.search(
                    query,
                    limit=limit,
                    scope=scope,
                    project_key=project_key,
                    agent_id=agent_id,
                    include_private=include_private,
                )
            )
        return results[:limit]

    def delete_memory(  # noqa: PLR0911 — 防御性分支返回
        self,
        memory_id: str,
        memory_type: str,
        agent_id: Optional[str] = None,
    ) -> bool:
        """
        删除记忆

        Args:
            memory_id: 记忆 ID
            memory_type: 记忆类型
            agent_id: M3 当前专家。给定时**拒绝**删除属于其他专家的
                私有行（跨专家保护）；``None`` = 管理口径，可删任意行
                （历史行为）。

        Returns:
            是否删除成功
        """
        store = None
        if memory_type == "episodic":
            store = self.episodic
        elif memory_type == "semantic":
            store = self.semantic

        if store is not None and agent_id:
            row = store.get_by_id(memory_id)
            if row is not None and row.get("agent_id") not in (None, str(agent_id)):
                logger.warning(
                    f"拒绝删除其他专家的私有记忆: {memory_type}/{memory_id}"
                )
                return False

        if store is self.episodic:
            return self.episodic.delete(memory_id)
        elif store is self.semantic:
            return self.semantic.delete(memory_id)
        elif memory_type == "working":
            parts = memory_id.split(":")
            if len(parts) != 3 or parts[0] != "wm":
                return False
            try:
                sequence = int(parts[2])
            except ValueError:
                return False
            return self.working.delete_message(":".join(parts[1:-1]), sequence)
        else:
            logger.warning(f"不支持删除记忆类型: {memory_type}")
            return False

    # ------------------------------------------------------------------ #
    # M3-Task 7 (2026-11-04): 提升为共享 / 专家删除级联清理
    # ------------------------------------------------------------------ #

    #: ``memories_evolution_log.operation`` 的提升取值（与进化任务同白名单）。
    PROMOTE_OPERATION = "promote"

    #: 可提升的记忆层 → 主表名。``working`` 不落库（仅会话内），不参与。
    _PROMOTABLE_TABLES = (
        ("episodic", "memories_episodic"),
        ("semantic", "memories_semantic"),
    )

    def promote_to_shared(
        self,
        memory_id: str,
        memory_type: Optional[str] = None,
        reason: str = "user_promote",
    ) -> Dict[str, Any]:
        """把一条私有记忆提升到共享层（M3-Task 7）。

        归属从 ``agent_id = <专家>`` 改为 ``NULL``（共享层），提升后所有
        专家都能读到。**归属变更与审计行同事务提交** —— 审计行丢失意味着
        "谁在何时把哪条记忆公开" 不可追溯，因此这里不做 best-effort：
        审计写入失败则整个提升回滚并向上抛错。

        Args:
            memory_id: 记忆 ID
            memory_type: ``episodic`` / ``semantic``；``None`` = 两层都探测
            reason: 审计原因，写入 ``memories_evolution_log.reason``

        Returns:
            ``{"status": "promoted" | "already_shared" | "not_found", ...}``
            ``status`` 为 ``not_found`` 时其余字段仅供定位。
        """
        not_found = {
            "status": "not_found",
            "memory_id": memory_id,
            "memory_type": memory_type or "",
            "previous_agent_id": None,
        }
        if not memory_id:
            return not_found

        conn = self.episodic.db.get_connection()
        for mtype, table in self._PROMOTABLE_TABLES:
            if memory_type and mtype != memory_type:
                continue
            row = self._fetch_promote_row(conn, table, memory_id)
            if row is None:
                continue
            current_agent = row["agent_id"]
            if not current_agent:
                return {
                    "status": "already_shared",
                    "memory_id": memory_id,
                    "memory_type": mtype,
                    "previous_agent_id": None,
                }
            content = row["content"] or ""
            try:
                conn.execute(
                    f"UPDATE {table} SET agent_id = NULL WHERE id = ?",
                    (memory_id,),
                )
                conn.execute(
                    "INSERT INTO memories_evolution_log "
                    "(id, memory_type, memory_id, operation, before_content, "
                    "after_content, reason, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid.uuid4()),
                        mtype,
                        memory_id,
                        self.PROMOTE_OPERATION,
                        content,
                        content,
                        f"{reason} (agent_id: {current_agent} → NULL)",
                        int(time.time() * 1000),
                    ),
                )
                conn.commit()
            except sqlite3.DatabaseError as exc:
                conn.rollback()
                logger.error("提升记忆为共享失败 (memory_id=%s): %s", memory_id, exc)
                raise
            logger.info(
                "记忆已提升为共享 (memory_id=%s, type=%s, 原归属=%s)",
                memory_id,
                mtype,
                current_agent,
            )
            return {
                "status": "promoted",
                "memory_id": memory_id,
                "memory_type": mtype,
                "previous_agent_id": current_agent,
            }

        return not_found

    def purge_agent_memories(self, agent_id: str) -> Dict[str, Any]:
        """清理某专家的全部私有记忆（M3-Task 7：删除专家时级联清理）。

        删除语义沿用各存储层既有约定 —— 情景层软删除（``is_valid = 0``，
        全部读路径按 ``is_valid = 1 AND invalid_at IS NULL`` 过滤掉），
        语义层硬删除（连带 FTS 行）。向量条目另按 ``memories_vec%`` 全表
        清扫：存储层的 ``delete`` 只清 ``memories_vec``，其它嵌入维度的
        向量表会残留孤儿条目。

        ``working`` 层不参与：它按 ``session_id`` 隔离且不落 agent 维度。

        Args:
            agent_id: 专家 ID

        Returns:
            ``{"episodic": n, "semantic": n, "vector": n, "memory_ids": [...]}``
        """
        if not agent_id:
            return {"episodic": 0, "semantic": 0, "vector": 0, "memory_ids": []}

        conn = self.episodic.db.get_connection()
        episodic_ids = self._collect_agent_memory_ids(conn, "memories_episodic", agent_id)
        semantic_ids = self._collect_agent_memory_ids(conn, "memories_semantic", agent_id)

        for memory_id in episodic_ids:
            self.episodic.delete(memory_id)
        for memory_id in semantic_ids:
            self.semantic.delete(memory_id)

        all_ids = episodic_ids + semantic_ids
        vector_removed = self._purge_vectors_for_ids(conn, all_ids)
        logger.info(
            "级联清理专家私有记忆: agent=%s episodic=%d semantic=%d vector=%d",
            agent_id,
            len(episodic_ids),
            len(semantic_ids),
            vector_removed,
        )
        return {
            "episodic": len(episodic_ids),
            "semantic": len(semantic_ids),
            "vector": vector_removed,
            "memory_ids": all_ids,
        }

    @staticmethod
    def _fetch_promote_row(conn: Any, table: str, memory_id: str) -> Optional[Any]:
        """读取待提升记忆的 ``content`` / ``agent_id``；表或列缺失时返回 None。"""
        try:
            return conn.execute(
                f"SELECT content, agent_id FROM {table} WHERE id = ?",
                (memory_id,),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            logger.warning("读取 %s 失败: %s", table, exc)
            return None

    @staticmethod
    def _collect_agent_memory_ids(conn: Any, table: str, agent_id: str) -> List[str]:
        """收集某表内归属该专家的记忆 id（表或列缺失时返回空列表）。"""
        try:
            rows = conn.execute(
                f"SELECT id FROM {table} WHERE agent_id = ?", (agent_id,)
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            logger.warning("读取 %s 私有记忆失败: %s", table, exc)
            return []
        return [row["id"] for row in rows]

    @staticmethod
    def _table_has_column(conn: Any, table: str, column: str) -> bool:
        """检查表是否含指定列（vec0 影子表无 ``memory_id``，须跳过）。"""
        try:
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        except sqlite3.DatabaseError as exc:
            logger.warning("读取 %s 表结构失败: %s", table, exc)
            return False
        return any(row["name"] == column for row in rows)

    @staticmethod
    def _purge_vectors_for_ids(conn: Any, memory_ids: List[str]) -> int:
        """按 memory_id 清扫全部 ``memories_vec*`` 向量表。

        存储层的 ``delete`` 只清 ``memories_vec``；多嵌入维度（如
        ``memories_vec_512``）的向量表会残留孤儿条目，故在此统一补齐。
        """
        if not memory_ids:
            return 0
        try:
            tables = [
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' "
                    "AND name LIKE 'memories_vec%'"
                ).fetchall()
            ]
        except sqlite3.DatabaseError as exc:
            logger.warning("枚举向量表失败: %s", exc)
            return 0

        removed = 0
        for table in tables:
            if not MemoryManager._table_has_column(conn, table, "memory_id"):
                continue
            try:
                for memory_id in memory_ids:
                    cursor = conn.execute(
                        f"DELETE FROM {table} WHERE memory_id = ?", (memory_id,)
                    )
                    if cursor.rowcount > 0:
                        removed += cursor.rowcount
            except sqlite3.DatabaseError as exc:
                logger.warning("清理向量表 %s 失败: %s", table, exc)
        try:
            conn.commit()
        except sqlite3.DatabaseError as exc:
            logger.warning("向量清理提交失败: %s", exc)
        return removed

    def get_stats(self) -> Dict[str, Any]:
        """
        获取记忆统计信息

        Returns:
            统计信息字典
        """
        stats = {
            "working": {
                "message_count": len(self.working.messages),
                "total_tokens": self.working.total_tokens,
                "session_count": len(self.working.session_ids()),
            },
            "episodic": {"total": 0},
            "semantic": {"total": 0},
        }

        with contextlib.suppress(Exception):
            stats["episodic"]["total"] = self.episodic.count()

        with contextlib.suppress(Exception):
            stats["semantic"]["total"] = self.semantic.count()

        return stats
