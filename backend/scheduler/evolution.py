"""
进化任务实现
包含每日摘要、记忆修剪、偏好学习、重要性重评估等任务
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from backend.data.database import get_database
from backend.memory.episodic import sync_fts_row_for_id
from backend.memory.preference_labels import (
    PREFERENCE_DIMENSION_LABELS,
    PREFERENCE_VALUE_LABELS,
    format_preference,
)
from backend.memory.vector_store import prune_orphan_vectors
from backend.scheduler.evolution_log import elapsed_ms, record_evolution_log

logger = logging.getLogger(__name__)

# Wall-clock timeout for evolution tasks (default 30 minutes)
# Prevents APScheduler thread from hanging indefinitely if LLM call stalls
_EVOLUTION_TASK_TIMEOUT_S = float(
    os.environ.get("SAGE_EVOLUTION_TASK_TIMEOUT_S", "1800")
)


def _utcnow_iso() -> str:
    """ISO 8601 UTC now — for evolution_completed event timestamps."""
    return datetime.now(timezone.utc).isoformat()  # noqa: UP017 — py38: datetime.UTC is 3.11+


class BaseEvolutionTask:
    """进化任务基类

    Subclasses can:
    - set ``self._hooks`` to a ``HookRegistry`` instance to receive
      ``evolution_completed`` events after each successful run.
    - leave ``self._hooks`` unset; the helper will silently no-op so
      existing tests / callers don't need to be modified.
    """

    def __init__(self, db=None, memory_manager=None, hooks: Optional[Any] = None):
        # Optional — see ``_emit_evolution_completed``. Set externally
        # by ``create_evolution_tasks(hooks=...)`` or by the lifespan.
        self._hooks = hooks
        self.db = db or get_database()
        self.memory_manager = memory_manager

    async def run_async(self):
        """异步执行任务（子类实现）"""
        raise NotImplementedError

    def run(self):
        """同步执行任务（带 wall-clock 超时保护）"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                asyncio.wait_for(self.run_async(), timeout=_EVOLUTION_TASK_TIMEOUT_S)
            )
        except asyncio.TimeoutError:  # noqa: UP041 — py3.8 下 asyncio.TimeoutError 不等于内置 TimeoutError
            task_name = type(self).__name__
            logger.error(
                f"Evolution task {task_name} timed out after "
                f"{_EVOLUTION_TASK_TIMEOUT_S:.0f}s, forcing termination"
            )
            raise
        finally:
            loop.close()

    async def _emit_evolution_completed(
        self, items_processed: int, duration_ms: int = 0
    ) -> None:
        """Fire ``evolution_completed`` hook (Task 4 / Gap A).

        Best-effort: any exception in the hook registry is logged but does
        not propagate. If no ``_hooks`` is attached, this is a no-op.
        """
        hooks = getattr(self, "_hooks", None)
        if hooks is None:
            return
        try:
            await hooks.emit(
                "evolution_completed",
                {
                    "task_name": type(self).__name__,
                    "items_processed": items_processed,
                    "duration_ms": duration_ms,
                    "timestamp": _utcnow_iso(),
                },
            )
        except Exception as exc:  # noqa: BLE001 — must not break the task
            logger.warning("evolution_completed hook emit failed: %s", exc)


def _write_evolution_log(
    db,
    memory_type: str,
    memory_id: str,
    operation: str,
    before_content: str = None,
    after_content: str = None,
    reason: str = None,
) -> None:
    """
    写入一条记忆级进化日志 (memories_evolution_log)

    统一 INSERT 入口，供 MemoryConsolidationTask / ImportanceReevaluationTask /
    MemoryPruningTask 记录记忆级变更。采用 best-effort 语义：写入失败只
    logger.warning，不让进化任务整体失败（日志缺失可接受，进化中断不可接受）。

    表结构 (PRAGMA table_info 确认):
        id, memory_type, memory_id, operation,
        before_content, after_content, reason, created_at

    Args:
        db: Database 实例
        memory_type: 记忆类型 (episodic / semantic)
        memory_id: 记忆 ID（批量操作用 batch:<规则>:<时间戳> 合成 id）
        operation: 操作类型 (promote / importance_adjust / prune)
        before_content: 变更前内容或位置描述
        after_content: 变更后内容或位置描述
        reason: 变更原因（任务名；批量操作附带规则名）
    """
    try:
        conn = db.get_connection()
        conn.execute(
            """
            INSERT INTO memories_evolution_log
            (id, memory_type, memory_id, operation, before_content, after_content,
             reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                str(uuid.uuid4()),
                memory_type,
                memory_id,
                operation,
                before_content,
                after_content,
                reason,
                # 毫秒时间戳，与 memories_episodic/memories_semantic 仓储层一致
                int(time.time() * 1000),
            ),
        )
        conn.commit()
    except Exception as e:
        logger.warning(
            f"写入 memories_evolution_log 失败 (operation={operation}, "
            f"memory_id={memory_id}): {e}"
        )


class DailySummaryTask(BaseEvolutionTask):
    """
    每日摘要任务

    功能:
    1. 获取今日所有会话
    2. 对每个会话生成摘要（调用 LLM）
    3. 保存到情景记忆 (importance=6)
    """

    def __init__(
        self,
        db=None,
        memory_manager=None,
        llm_client=None,
        config: dict = None,
        hooks: Optional[Any] = None,
    ):
        super().__init__(db, memory_manager, hooks=hooks)
        self.llm = llm_client
        self.config = config or {}
        self.min_messages = self.config.get("min_messages", 3)

    async def run_async(self):
        """执行每日摘要"""
        start = time.monotonic()
        logger.info("开始执行每日摘要任务...")
        _started = time.monotonic()

        conn = self.db.get_connection()
        cursor = conn.cursor()

        # 获取今日时间范围
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_ts = int(today_start.timestamp())
        now_ts = int(time.time())

        # 1. 获取今日所有会话
        cursor.execute(
            """
            SELECT id, title, message_count
            FROM sessions
            WHERE created_at >= ? AND created_at < ?
            ORDER BY created_at DESC
        """,
            [today_start_ts, now_ts],
        )

        sessions = cursor.fetchall()
        logger.info(f"今日会话数量: {len(sessions)}")

        processed = 0

        for session in sessions:
            session_id = session["id"]
            message_count = session["message_count"]

            if message_count < self.min_messages:
                logger.debug(f"会话 {session_id} 消息数不足 ({message_count})，跳过")
                continue

            # 2. 获取会话消息
            cursor.execute(
                """
                SELECT role, content
                FROM messages
                WHERE session_id = ?
                ORDER BY created_at ASC
            """,
                [session_id],
            )

            messages = cursor.fetchall()

            if len(messages) < self.min_messages:
                continue

            # 3. 生成摘要
            summary = await self._generate_summary(messages)

            if not summary:
                continue

            # 4. 保存到情景记忆
            memory_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO memories_episodic
                (id, session_id, content, summary, memory_type, importance, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    memory_id,
                    session_id,
                    f"每日摘要: {summary}",
                    summary,
                    "daily_summary",
                    6,  # importance=6
                    "evolution",
                    now_ts,
                ),
            )

            # 4b. 同步 FTS 索引（绕开 EpisodicMemory.save() 直写时必须显式同步，
            # 否则新记忆必须等下次 _backfill_fts() 才能被 FTS 检索到）
            sync_fts_row_for_id(conn, memory_id)

            # 5. 标记会话已摘要
            cursor.execute(
                """
                UPDATE sessions
                SET metadata = json_set(COALESCE(metadata, '{}'), '$.summarized', 1)
                WHERE id = ?
            """,
                [session_id],
            )

            processed += 1
            logger.info(f"会话 {session_id} 摘要完成: {summary[:50]}...")

        conn.commit()
        logger.info(f"每日摘要完成，处理了 {processed} 个会话")

        # 记录进化日志
        record_evolution_log(
            self.db,
            evolution_type="daily_summary",
            description=f"每日摘要完成，处理了 {processed} 个会话",
            status="success",
            duration_ms=elapsed_ms(_started),
            metrics={
                "sessions_scanned": len(sessions),
                "sessions_summarized": processed,
            },
        )

        await self._emit_evolution_completed(
            items_processed=processed,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        return processed

    async def _generate_summary(self, messages: List[dict]) -> Optional[str]:
        """
        生成对话摘要

        Args:
            messages: 消息列表

        Returns:
            摘要内容
        """
        if not messages:
            return None

        # 构建消息文本
        messages_text = "\n".join(
            [
                f"[{msg['role']}]: {msg['content'][:200]}"
                for msg in messages[:20]  # 最多20条消息
            ]
        )

        # 如果有 LLM 客户端，使用 LLM 生成摘要
        if self.llm:
            try:
                prompt = f"""请总结以下对话的要点，生成一段简洁的摘要 (100字以内):

{messages_text}

摘要:"""

                result = await self.llm.complete(prompt)
                return result.strip() if result else None
            except Exception as e:
                logger.error(f"LLM 生成摘要失败: {e}")

        # 简单的备用摘要策略
        user_messages = [m["content"] for m in messages if m["role"] == "user"]
        if user_messages:
            # 取第一条和最后一条用户消息作为摘要
            first = user_messages[0][:50]
            user_messages[-1][:50] if len(user_messages) > 1 else ""
            return f"对话围绕 {first}... 等话题展开，共 {len(messages)} 条消息"

        return None


class MemoryPruningTask(BaseEvolutionTask):
    """
    记忆修剪任务

    功能:
    1. 删除 expires_at < now 的记忆
    2. 删除 importance<=1 且 30天未访问的记忆
    3. 超过上限(1000条)时删除最旧最不重要的
    4. 按质量分软失效长期未访问的低质量记忆（Task 3.4）

    前三条是"硬删除"（物理 DELETE），按固定门槛扫；第 4 条是"软失效"
    （invalid_at + is_valid=0），按写得好不好、有没有被用过、放了多久
    综合判定。软失效保留行，便于事后追溯与 supersedes 链完整性。
    """

    def __init__(
        self,
        db=None,
        memory_manager=None,
        config: dict = None,
        hooks: Optional[Any] = None,
    ):
        super().__init__(db, memory_manager, hooks=hooks)
        self.config = config or {}
        self.max_memories = self.config.get("max_memories", 1000)

    async def run_async(self):
        """执行记忆修剪"""
        start = time.monotonic()
        logger.info("开始执行记忆修剪任务...")
        _started = time.monotonic()

        conn = self.db.get_connection()
        cursor = conn.cursor()

        total_deleted = 0
        now_ts = int(time.time())
        thirty_days_ago = now_ts - 30 * 24 * 3600

        # 1. 删除过期记忆
        cursor.execute(
            """
            DELETE FROM memories_episodic
            WHERE expires_at IS NOT NULL AND expires_at < ?
        """,
            [now_ts],
        )
        expired_deleted = cursor.rowcount
        total_deleted += expired_deleted
        logger.info(f"删除过期记忆: {expired_deleted} 条")
        if expired_deleted > 0:
            _write_evolution_log(
                self.db,
                memory_type="episodic",
                memory_id=f"batch:expired:{now_ts}",
                operation="prune",
                before_content=str(expired_deleted),
                reason="memory_pruning:expired",
            )

        # 2. 删除极低价值且长期未访问的记忆
        # （environment 标签 = 本机工具链事实，豁免清理：环境记忆化 PR）
        cursor.execute(
            """
            DELETE FROM memories_episodic
            WHERE importance <= 1
            AND access_count = 0
            AND created_at < ?
            AND COALESCE(tags, '') NOT LIKE '%environment%'
        """,
            [thirty_days_ago],
        )
        low_value_deleted = cursor.rowcount
        total_deleted += low_value_deleted
        logger.info(f"删除低价值记忆: {low_value_deleted} 条")
        if low_value_deleted > 0:
            _write_evolution_log(
                self.db,
                memory_type="episodic",
                memory_id=f"batch:low_value:{now_ts}",
                operation="prune",
                before_content=str(low_value_deleted),
                reason="memory_pruning:low_value",
            )

        # 3. 删除孤儿记忆（无关联会话且无重要内容）
        cursor.execute(
            """
            DELETE FROM memories_episodic
            WHERE session_id IS NOT NULL
            AND importance <= 3
            AND access_count = 0
            AND created_at < ?
            AND COALESCE(tags, '') NOT LIKE '%environment%'
        """,
            [thirty_days_ago],
        )
        orphaned_deleted = cursor.rowcount
        total_deleted += orphaned_deleted
        logger.info(f"删除孤儿记忆: {orphaned_deleted} 条")
        if orphaned_deleted > 0:
            _write_evolution_log(
                self.db,
                memory_type="episodic",
                memory_id=f"batch:orphaned:{now_ts}",
                operation="prune",
                before_content=str(orphaned_deleted),
                reason="memory_pruning:orphaned",
            )

        # 4. 超过上限时删除最旧的
        cursor.execute("SELECT COUNT(*) FROM memories_episodic")
        current_count = cursor.fetchone()[0]

        if current_count > self.max_memories:
            excess = current_count - self.max_memories
            cursor.execute(
                """
                DELETE FROM memories_episodic
                WHERE id IN (
                    SELECT id FROM memories_episodic
                    WHERE COALESCE(tags, '') NOT LIKE '%environment%'
                    ORDER BY importance ASC, created_at ASC
                    LIMIT ?
                )
            """,
                [excess],
            )
            limit_deleted = cursor.rowcount
            total_deleted += limit_deleted
            logger.info(f"超过上限删除: {limit_deleted} 条")
            if limit_deleted > 0:
                _write_evolution_log(
                    self.db,
                    memory_type="episodic",
                    memory_id=f"batch:limit:{now_ts}",
                    operation="prune",
                    before_content=str(limit_deleted),
                    reason="memory_pruning:limit",
                )

        # 5. 质量分清理（软失效）：质量分低 **且** 90 天以上未被访问。
        #    与上面三条硬删除规则不重叠 —— 它们按固定门槛扫，这里按
        #    "写得差 + 从未有用过 + 已经放了很久" 综合判定。
        quality_pruned = await self._prune_low_quality_memories()
        if quality_pruned:
            logger.info(f"低质量记忆软失效: {quality_pruned} 条")

        conn.commit()

        # D1 (P6): 向量库补偿式对账 —— 上面的批量 DELETE 只写主表,
        # memories_vec 的对应条目由对账清扫, 避免已删记忆仍被向量检索命中。
        orphan_vectors = prune_orphan_vectors(self.db)

        logger.info(f"记忆修剪完成，共删除 {total_deleted} 条记忆")

        # 记录进化日志
        record_evolution_log(
            self.db,
            evolution_type="memory_pruning",
            description=(
                f"记忆修剪完成，删除了 {total_deleted} 条记忆，"
                f"当前记忆数: {current_count - total_deleted}，"
                f"低质量软失效: {quality_pruned} 条，"
                f"清理孤儿向量: {orphan_vectors} 条"
            ),
            status="success",
            duration_ms=elapsed_ms(_started),
            metrics={
                "memories_deleted": total_deleted,
                "memories_remaining": current_count - total_deleted,
                "memories_quality_pruned": quality_pruned,
                "orphan_vectors_cleaned": orphan_vectors,
            },
        )

        await self._emit_evolution_completed(
            items_processed=total_deleted,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        return total_deleted

    async def _prune_low_quality_memories(self) -> int:
        """按质量分软失效长期未访问的低质量记忆（不物理删除）。

        与上面三条硬删除规则的分工：这里只处理"质量分低 **且** 超过 90 天
        未被访问"的记忆，用软失效（``invalid_at`` + ``is_valid=0``）而非
        DELETE —— 物理删除会切断 ``supersedes`` 链，事后无法追溯。
        ``tags`` 含 ``environment`` 的记忆豁免（已验证的环境解决方案，
        往往是低频但高价值的）。

        Returns:
            本次软失效的记忆条数。
        """
        from backend.memory.quality_scorer import MemoryQualityScorer

        try:
            cursor = self.db.get_connection().execute(
                """
                SELECT id, content, importance, access_count, created_at,
                       accessed_at, tags
                FROM memories_episodic
                WHERE is_valid = 1 AND invalid_at IS NULL
                """
            )
            rows = [dict(row) for row in cursor.fetchall()]
        except Exception as exc:  # noqa: BLE001 — 读取失败不拖垮修剪任务
            logger.warning(f"低质量记忆读取失败: {exc}")
            return 0
        if not rows:
            return 0

        scorer = MemoryQualityScorer(corpus=rows)
        now_ms = int(time.time() * 1000)
        pruned = 0
        for row in rows:
            if "environment" in (row.get("tags") or ""):
                continue
            try:
                if not scorer.should_delete(row):
                    continue
                quality = scorer.calculate_quality_score(row)
            except Exception as exc:  # noqa: BLE001 — 单条评分失败跳过
                logger.debug(f"记忆质量评分失败({row.get('id')}): {exc}")
                continue
            if self._soft_invalidate_memory(row, now_ms, quality):
                pruned += 1
        return pruned

    def _soft_invalidate_memory(self, row: dict, now_ms: int, quality: float) -> bool:
        """软失效一条记忆，并同步清掉它的向量条目。"""
        memory_id = row.get("id")
        if not memory_id:
            return False
        conn = self.db.get_connection()
        try:
            cursor = conn.execute(
                """
                UPDATE memories_episodic
                SET invalid_at = ?, is_valid = 0
                WHERE id = ? AND is_valid = 1 AND invalid_at IS NULL
                """,
                (now_ms, memory_id),
            )
            if cursor.rowcount <= 0:
                return False
        except Exception as exc:  # noqa: BLE001 — 单条失效失败不影响其余
            logger.warning(f"低质量记忆失效失败({memory_id}): {exc}")
            return False
        # 主表行保留供审计，但失效记忆不应再被向量检索命中（best-effort）
        with suppress(sqlite3.DatabaseError):
            conn.execute("DELETE FROM memories_vec WHERE memory_id = ?", (memory_id,))
        conn.commit()
        _write_evolution_log(
            self.db,
            memory_type="episodic",
            memory_id=memory_id,
            operation="prune_quality",
            before_content=(row.get("content") or "")[:200],
            after_content=f"quality={quality:.2f}",
            reason="memory_pruning:low_quality",
        )
        return True


class PreferenceLearningTask(BaseEvolutionTask):
    """
    偏好学习任务

    功能:
    1. 获取用户反馈消息
    2. 分析偏好模式 (response_length, tone, detail_level)
    3. 保存到语义记忆
    """

    def __init__(
        self,
        db=None,
        memory_manager=None,
        llm_client=None,
        config: dict = None,
        hooks: Optional[Any] = None,
    ):
        super().__init__(db, memory_manager, hooks=hooks)
        self.llm = llm_client
        self.config = config or {}

    async def run_async(self):
        """执行偏好学习

        双路分析（对标 hermes-agent: 偏好应语义化理解而非关键词匹配）:
        1. 关键词路（零依赖兜底）: LIKE 扫描显式反馈关键词 → 规则映射
        2. LLM 路（配置了端点时）: 近 7 天用户消息采样 → LLM 抽取有明确
           证据的稳定偏好 JSON → 覆盖关键词基线
        持久化不变: semantic 记忆 + preferences 表 + evolution_log 审计。
        """
        start = time.monotonic()
        logger.info("开始执行偏好学习任务...")
        _started = time.monotonic()

        conn = self.db.get_connection()
        cursor = conn.cursor()

        # 1a. 关键词路: 获取近期反馈消息（包含反馈关键词的用户消息）
        cursor.execute("""
            SELECT id, session_id, content, created_at
            FROM messages
            WHERE role = 'user'
            AND (
                content LIKE '%反馈%' OR
                content LIKE '%评分%' OR
                content LIKE '%喜欢%' OR
                content LIKE '%不喜欢%' OR
                content LIKE '%太短%' OR
                content LIKE '%太长%' OR
                content LIKE '%详细%' OR
                content LIKE '%简单%'
            )
            ORDER BY created_at DESC
            LIMIT 50
        """)

        feedback_messages = cursor.fetchall()
        logger.info(f"找到 {len(feedback_messages)} 条关键词反馈消息")

        # 1b. LLM 路: 近 7 天用户消息采样（不受关键词预过滤, 语义化理解）
        llm = self._resolve_llm()
        llm_preferences: Dict[str, str] = {}
        llm_free_text: List[Dict[str, str]] = []
        if llm is not None:
            recent_messages = self._fetch_recent_user_messages(cursor)
            llm_preferences, llm_free_text = await self._analyze_preferences_with_llm(
                llm, recent_messages
            )
            if llm_preferences or llm_free_text:
                logger.info(
                    f"LLM 偏好抽取命中 {len(llm_preferences)} 个维度 / "
                    f"{len(llm_free_text)} 条自由文本"
                )
        else:
            logger.debug("LLM 不可用，偏好学习仅走关键词路径")

        # 2. 分析偏好模式: 关键词结果 + LLM 结果覆盖
        preferences = self._analyze_preferences(feedback_messages)
        preferences.update(llm_preferences)

        # 证据门槛: 关键词与 LLM 采样均无信号时不落库 ——
        # 关键词路径只返回**有命中**的维度（无证据也写入会用默认值
        # 覆盖用户此前学到的偏好，preferences 表是 ON CONFLICT DO UPDATE）。
        if not feedback_messages and not llm_preferences and not llm_free_text:
            logger.info("没有发现新的反馈（关键词与 LLM 采样均无信号），跳过")
            await self._emit_evolution_completed(
                items_processed=0,
                duration_ms=int((time.monotonic() - start) * 1000),
            )
            return 0

        if not preferences and not llm_free_text:
            logger.info("无法分析出明确偏好")
            await self._emit_evolution_completed(
                items_processed=0,
                duration_ms=int((time.monotonic() - start) * 1000),
            )
            return 0

        # 3. 保存到语义记忆
<<<<<<< HEAD
        profile_lines = [format_preference(k, v) for k, v in preferences.items()]
        profile_lines.extend(
            f"用户偏好{item['category']}: {item['preference']}" for item in llm_free_text
        )
        profile_text = "\n".join(profile_lines)
        memory_id = str(uuid.uuid4())
        now_ts = int(time.time())

=======
        profile_text = "\n".join(
            format_preference(k, v) for k, v in preferences.items()
        )
        memory_id = str(uuid.uuid4())
        now_ts = int(time.time())

        # 白名单从 PREFERENCE_VALUE_LABELS 派生 -- 维度与合法取值的
        # 单一真相源在 backend/memory/preference_labels.py,
        # 这里不再各写一份(曾因两处不同步漏掉新维度)。
>>>>>>> origin/main
        summary_parts = [
            f"{PREFERENCE_DIMENSION_LABELS.get(key, key)}="
            f"{PREFERENCE_VALUE_LABELS.get(key, {}).get(value, value)}"
            for key, value in preferences.items()
        ]
<<<<<<< HEAD
        summary_parts.extend(
            f"{item['category']}: {item['preference']}" for item in llm_free_text
        )
=======
        summary_text = ", ".join(summary_parts)
>>>>>>> origin/main

        cursor.execute(
            """
            INSERT INTO memories_semantic
            (id, content, summary, tags, created_at)
            VALUES (?, ?, ?, ?, ?)
        """,
            (
                memory_id,
                f"用户偏好总结:\n{profile_text}",
<<<<<<< HEAD
                "用户偏好: " + ", ".join(summary_parts),
=======
                "用户偏好: " + summary_text,
>>>>>>> origin/main
                '["user_preference", "evolution"]',
                now_ts,
            ),
        )

        # 同时更新用户偏好表
        for key, value in preferences.items():
            cursor.execute(
                """
                INSERT INTO preferences (key, value, value_type, category, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
            """,
                (f"pref_{key}", str(value), "string", "preference", now_ts, now_ts),
            )

        conn.commit()

        # P0-2：同步写入 user_profile，让学到的偏好真正进 system prompt
        # （hermes 冻结语义：add() 只更新 DB + 内存 _entries，不调 invalidate()，
        # 下次会话启动才刷新快照 —— 保 prefix cache）
        try:
            from backend.memory.user_profile import UserProfileStore

            profile_store = UserProfileStore(self.db)
            profile_store.load()
            for key, value in preferences.items():
                profile_store.add(
                    content=format_preference(key, value),
<<<<<<< HEAD
                    category="preference",
                    importance=6,
                )
            for item in llm_free_text:
                profile_store.add(
                    content=f"用户偏好{item['category']}: {item['preference']}",
=======
>>>>>>> origin/main
                    category="preference",
                    importance=6,
                )
        except Exception as exc:  # noqa: BLE001 — 偏好写 user_profile 是旁路，不阻断主流程
            logger.warning(f"偏好写入 user_profile 失败（旁路）: {exc}")

        logger.info(f"偏好学习完成: {preferences} + {len(llm_free_text)} 条自由文本")

        # 记录进化日志
        record_evolution_log(
            self.db,
            evolution_type="preference_learning",
            description=(
                f"偏好学习完成，分析出 {len(preferences)} 个偏好维度"
                f" / {len(llm_free_text)} 条自由文本偏好"
            ),
            status="success",
            after_state=profile_text,
            duration_ms=elapsed_ms(_started),
            metrics={
                "preferences_learned": len(preferences),
                "free_text_preferences": len(llm_free_text),
            },
        )

        return len(preferences) + len(llm_free_text)

    def _analyze_preferences(self, feedback_messages: List[dict]) -> Dict[str, str]:
        """关键词路径分析用户偏好。

        只返回**有证据**的维度 —— 没有命中关键词的维度不落库，避免用
        默认值覆盖用户此前学到的偏好（``preferences`` 表是
        ``ON CONFLICT(key) DO UPDATE``，写入即覆盖）。

        Args:
            feedback_messages: 反馈消息列表

        Returns:
            偏好字典（键 → 机器值），可能为空
        """
        preferences: Dict[str, str] = {}

        # 各维度独立关键词 → 取值映射
        length_prefs = {"太短": "long", "太长": "short", "简短": "short", "详细": "detailed"}
        tone_prefs = {
            "友好": "friendly",
            "专业": "professional",
            "幽默": "humorous",
            "严肃": "formal",
        }
        detail_prefs = {"详细": "detailed", "简单": "brief", "复杂": "comprehensive"}
        code_style_prefs = {
            "函数式": "functional",
            "面向对象": "oop",
            "OOP": "oop",
            "functional": "functional",
        }
        comment_prefs = {
            "别加注释": "none",
            "不用加注释": "none",
            "不要注释": "none",
            "加注释": "detailed",
            "详细注释": "detailed",
            "关键注释": "minimal",
        }
        explanation_prefs = {
            "详细推导": "detailed",
            "详细解释": "detailed",
            "直接给答案": "direct",
            "直接给结果": "direct",
            "简要说明": "brief",
        }

        for msg in feedback_messages:
            content = msg["content"]

            for keyword, pref in length_prefs.items():
                if keyword in content:
                    preferences["response_length"] = pref

            for keyword, pref in tone_prefs.items():
                if keyword in content:
                    preferences["tone"] = pref

            for keyword, pref in detail_prefs.items():
                if keyword in content:
                    preferences["detail_level"] = pref

            for keyword, pref in code_style_prefs.items():
                if keyword in content:
                    preferences["code_style"] = pref

            for keyword, pref in comment_prefs.items():
                if keyword in content:
                    preferences["comment_preference"] = pref

            for keyword, pref in explanation_prefs.items():
                if keyword in content:
                    preferences["explanation_depth"] = pref

        return preferences

    def _resolve_llm(self):
        """解析偏好学习用的 LLM 客户端（注入优先，settings 兜底）

        与 orchestration/llm_factory 同模式: 调用方可注入客户端（测试/
        编排链），缺省从 app_settings 解析用户配置的端点。不可用返回
        None —— 偏好学习降级为纯关键词路径，绝不抛异常。
        """
        if self.llm is not None:
            return self.llm
        try:
            from backend.core.legacy.llm_client import LLMClient, LLMConfig
            from backend.orchestration.llm_factory import load_llm_config_from_settings

            cfg = load_llm_config_from_settings()
            if cfg is None:
                return None
            return LLMClient(LLMConfig(**cfg))
        except Exception as exc:  # noqa: BLE001 — 降级路径, 不拖垮定时任务
            logger.warning(f"偏好学习 LLM 客户端解析失败，降级关键词路径: {exc}")
            return None

    def _fetch_recent_user_messages(self, cursor, days: int = 7):
        """取近 N 天用户消息采样（LLM 路输入, 不做关键词预过滤）"""
        try:
            sample_limit = int(self.config.get("llm_sample_limit", 100))
        except (TypeError, ValueError):
            sample_limit = 100
        cursor.execute(
            """
            SELECT id, session_id, content, created_at
            FROM messages
            WHERE role = 'user'
              AND created_at >= ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (int(time.time()) - days * 86400, sample_limit),
        )
        return cursor.fetchall()

    async def _analyze_preferences_with_llm(
        self, llm, recent_messages: List[dict]
    ) -> Tuple[Dict[str, str], List[Dict[str, str]]]:
        """LLM 抽取稳定偏好（只输出有明确证据的维度，宽容解析）

        Returns:
            ``(structured, free_text)``：
            * structured —— 形如 ``{"response_length": "short", ...}`` 的枚举维度；
            * free_text —— 形如 ``[{"category": "代码风格", "preference": "..."}]``
              的自由文本偏好（枚举维度覆盖不了的具体要求）。

            LLM 失败 / 输出不可解析 / 无证据时返回 ``({}, [])``。
        """
        if llm is None or not recent_messages:
            return {}, []

        # 消息截断: 单条 200 字符足够表达偏好, 控制提示词体积
        # （recent_messages 为 sqlite3.Row 或 dict, 统一用下标访问）
        lines = []
        for msg in recent_messages:
            try:
                content = msg["content"]
            except (KeyError, IndexError, TypeError):
                continue
            if content:
                lines.append(f"- {content[:200]}")
        if not lines:
            return {}, []

        prompt = (
            "以下是用户最近与 AI 助手的对话消息采样。请从中提取用户的稳定偏好，"
            "只关注以下维度（取值约定）:\n"
            "- response_length: short / medium / long / detailed（用户对回复长度的要求）\n"
            "- tone: friendly / professional / humorous / formal（用户期望的语气）\n"
            "- detail_level: brief / medium / comprehensive（用户期望的详细程度）\n"
            "- code_style: functional / oop / mixed（用户偏好的代码风格）\n"
            "- comment_preference: none / minimal / detailed（用户对代码注释的偏好）\n"
            "- explanation_depth: direct / brief / detailed（用户期望的解释深度）\n\n"
            "严格要求:\n"
            "1. 只输出用户**明确表达过**的偏好（例如『回答简短点』『用函数式风格』『别加注释』）；\n"
            "2. 没有证据的维度直接省略，不要猜测；\n"
            "3. 只输出 JSON 对象，无其他文字。\n\n"
            "输出格式:\n"
            '{"structured": {"response_length": "short"}, '
            '"free_text": [{"category": "代码风格", "preference": "偏好函数式编程，避免 class"}]}\n'
            "structured 放能归入上述枚举维度的偏好；free_text 放枚举维度覆盖不了的"
            "具体要求（例如『关键函数需要 docstring』『回复里先给结论再给推导』），"
            "没有就写空数组 []。\n\n"
            "用户消息采样:\n" + "\n".join(lines)
        )

        try:
            # 兼容 LLMPort 风格（Message 对象）与简单 chat() 接口 ——
            # 与 MemoryExtractor._extract_with_llm 同一适配模式
            try:
                from backend.domain.message import Message

                response_msg = await llm.chat(
                    messages=[Message(role="user", content=prompt)]
                )
                content = (
                    response_msg.content
                    if hasattr(response_msg, "content")
                    else str(response_msg)
                )
            except (ImportError, TypeError, AttributeError):
                response = await llm.chat(
                    messages=[{"role": "user", "content": prompt}]
                )
                content = (
                    response if isinstance(response, str) else response.get("content", "")
                )
        except Exception as exc:  # noqa: BLE001 — LLM 故障降级, 不抛出
            logger.warning(f"偏好学习 LLM 调用失败，忽略本轮 LLM 信号: {exc}")
            return {}, []

        return self._parse_preference_json(content if isinstance(content, str) else "")

    def _parse_preference_json(
        self, raw: str
    ) -> Tuple[Dict[str, str], List[Dict[str, str]]]:
        """宽容解析 LLM 输出的偏好 JSON（容忍代码围栏与多余文字）。

        兼容两种输出形态：
        * 嵌套式 ``{"structured": {...}, "free_text": [...]}``（当前 prompt）
        * 扁平式 ``{"response_length": "short"}``（旧 prompt / 保守模型）

        Returns:
            ``(structured, free_text)`` —— 结构化维度字典 + 自由文本偏好列表。
            解析失败时返回 ``({}, [])``。
        """
        import json

        if not raw:
            return {}, []
        text = raw.strip()
        # 剥离 ```json ... ``` 围栏
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        # 截取首个 { 到末个 } 之间
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return {}, []
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}, []
        if not isinstance(data, dict):
<<<<<<< HEAD
            return {}, []

        # 白名单从 PREFERENCE_VALUE_LABELS 派生 —— 维度与合法取值的
        # 单一真相源在 backend/memory/preference_labels.py，
        # 这里不再各写一份（曾因两处不同步漏掉新维度）。
        allowed = {key: set(values) for key, values in PREFERENCE_VALUE_LABELS.items()}

        # 嵌套式取 structured 子对象；扁平式整个对象就是结构化偏好
        raw_structured = data.get("structured")
        if not isinstance(raw_structured, dict):
            raw_structured = data

        structured: Dict[str, str] = {}
=======
            return {}
        allowed = {
            key: set(values) for key, values in PREFERENCE_VALUE_LABELS.items()
        }
        result: Dict[str, str] = {}
>>>>>>> origin/main
        for key, allowed_values in allowed.items():
            value = raw_structured.get(key)
            if isinstance(value, str) and value.lower() in allowed_values:
                structured[key] = value.lower()

        free_text: List[Dict[str, str]] = []
        raw_free_text = data.get("free_text")
        if isinstance(raw_free_text, list):
            for item in raw_free_text:
                if not isinstance(item, dict):
                    continue
                category = str(item.get("category", "")).strip()
                preference = str(item.get("preference", "")).strip()
                if not category or not preference:
                    continue
                free_text.append(
                    {"category": category[:20], "preference": preference[:120]}
                )

        return structured, free_text


class ImportanceReevaluationTask(BaseEvolutionTask):
    """
    重要性重评估任务

    功能:
    1. 高重要性(>=7)但长期未访问 -> 降低重要性
    2. 低重要性(<=4)但频繁访问 -> 提高重要性
    """

    def __init__(
        self,
        db=None,
        memory_manager=None,
        config: dict = None,
        hooks: Optional[Any] = None,
    ):
        super().__init__(db, memory_manager, hooks=hooks)
        self.config = config or {}

    async def run_async(self):
        """执行重要性重评估"""
        start = time.monotonic()
        logger.info("开始执行重要性重评估任务...")
        _started = time.monotonic()

        conn = self.db.get_connection()
        cursor = conn.cursor()

        now_ts = int(time.time())
        seven_days_ago = now_ts - 7 * 24 * 3600
        thirty_days_ago = now_ts - 30 * 24 * 3600

        total_adjusted = 0

        # 1. 重评估长期未访问的高重要性记忆
        # （environment 标签豁免：环境事实不因低频而降权）
        cursor.execute(
            """
            SELECT id, importance, access_count, content
            FROM memories_episodic
            WHERE importance >= 7
            AND access_count < 2
            AND created_at < ?
            AND COALESCE(tags, '') NOT LIKE '%environment%'
        """,
            [seven_days_ago],
        )

        high_importance = cursor.fetchall()
        logger.info(f"高重要性长期未访问记忆: {len(high_importance)} 条")

        for memory in high_importance:
            new_importance = max(5, memory["importance"] - 1)  # 最低降到5
            if new_importance != memory["importance"]:
                cursor.execute(
                    """
                    UPDATE memories_episodic
                    SET importance = ?
                    WHERE id = ?
                """,
                    [new_importance, memory["id"]],
                )
                total_adjusted += 1
                logger.debug(
                    f"降低记忆重要性: {memory['id']}, {memory['importance']} -> {new_importance}"
                )
                _write_evolution_log(
                    self.db,
                    memory_type="episodic",
                    memory_id=memory["id"],
                    operation="importance_adjust",
                    before_content=str(memory["importance"]),
                    after_content=str(new_importance),
                    reason="importance_reevaluation",
                )

        # 2. 重评估频繁访问的低重要性记忆
        cursor.execute(
            """
            SELECT id, importance, access_count, content
            FROM memories_episodic
            WHERE importance <= 4
            AND access_count >= 5
            AND created_at > ?
        """,
            [thirty_days_ago],
        )

        low_importance = cursor.fetchall()
        logger.info(f"低重要性频繁访问记忆: {len(low_importance)} 条")

        for memory in low_importance:
            new_importance = min(10, memory["importance"] + 1)  # 最高升到10
            if new_importance != memory["importance"]:
                cursor.execute(
                    """
                    UPDATE memories_episodic
                    SET importance = ?
                    WHERE id = ?
                """,
                    [new_importance, memory["id"]],
                )
                total_adjusted += 1
                logger.debug(
                    f"提高记忆重要性: {memory['id']}, {memory['importance']} -> {new_importance}"
                )
                _write_evolution_log(
                    self.db,
                    memory_type="episodic",
                    memory_id=memory["id"],
                    operation="importance_adjust",
                    before_content=str(memory["importance"]),
                    after_content=str(new_importance),
                    reason="importance_reevaluation",
                )

        conn.commit()
        logger.info(f"重要性重评估完成，调整了 {total_adjusted} 条记忆")

        # 记录进化日志
        record_evolution_log(
            self.db,
            evolution_type="importance_reevaluation",
            description=f"重要性重评估完成，调整了 {total_adjusted} 条记忆",
            status="success",
            duration_ms=elapsed_ms(_started),
            metrics={"memories_adjusted": total_adjusted},
        )

        await self._emit_evolution_completed(
            items_processed=total_adjusted,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        return total_adjusted


class MemoryConsolidationTask(BaseEvolutionTask):
    """
    记忆整合任务（"做梦"）— 借鉴 Letta 的 sleep-time compute

    功能（定期运行，例如每周日凌晨）:
    1. 识别高频访问的情景记忆 → 提升为语义记忆
    2. 识别重复/相似的记忆 → 合并为一条
    3. 降低长期未访问记忆的重要性

    类似人脑在睡眠期间整合记忆的过程。
    """

    def __init__(
        self,
        db=None,
        memory_manager=None,
        config: dict = None,
        hooks: Optional[Any] = None,
    ):
        super().__init__(db, memory_manager, hooks=hooks)
        self.config = config or {}
        self.promotion_threshold = self.config.get("promotion_access_count", 5)
        self.decay_days = self.config.get("decay_days", 30)

    async def run_async(self):
        """执行记忆整合"""
        start = time.monotonic()
        logger.info("开始执行记忆整合任务（做梦）...")

        conn = self.db.get_connection()
        cursor = conn.cursor()
        total_consolidated = 0

        # 1. 提升高频访问的情景记忆为语义记忆
        cursor.execute(
            """
            SELECT id, content, summary, tags, importance, scope, project_key
            FROM memories_episodic
            WHERE is_valid = 1
            AND access_count >= ?
            AND memory_type != 'summary'
        """,
            [self.promotion_threshold],
        )

        promoted = 0
        for row in cursor.fetchall():
            memory = dict(row)
            # 检查语义记忆中是否已有相似内容
            existing = self.memory_manager.semantic.search(query=memory["content"][:50], limit=3)
            already_exists = any(
                e.get("content", "")[:50] == memory["content"][:50] for e in existing
            )
            if already_exists:
                continue

            try:
                semantic_id = self.memory_manager.semantic.save(
                    content=memory["content"],
                    summary=memory.get("summary"),
                    tags=_safe_json_loads(memory.get("tags", "[]")),
                    # P1 作用域轴：晋升保留归属，项目级记忆不会因晋升
                    # 变成全局可见（scope 为空的存量行由存储层兜底为 user）
                    scope=memory.get("scope"),
                    project_key=memory.get("project_key"),
                )
                # 晋升软删：写入 semantic 成功后，把源 episodic 行 is_valid 置 0，
                # 避免检索出现重复事实。semantic.save 与本 UPDATE 复用同一连接，
                # 紧随其后 commit 使两者一起持久化；任一步失败则回滚并跳过该条，
                # 不留半完成状态（源行保持有效，下轮去重检查可识别已写入的语义行）。
                cursor.execute(
                    """
                    UPDATE memories_episodic
                    SET is_valid = 0
                    WHERE id = ?
                """,
                    [memory["id"]],
                )
                conn.commit()
                promoted += 1
            except Exception as e:
                conn.rollback()
                logger.warning(f"记忆晋升失败，已回滚并跳过: {memory['id']}: {e}")
                continue

            # 晋升记录落记忆进化日志（best-effort，失败只 warning）
            _write_evolution_log(
                self.db,
                memory_type="episodic",
                memory_id=memory["id"],
                operation="promote",
                before_content=f"episodic:{memory['id']}",
                after_content=f"semantic:{semantic_id}",
                reason="memory_consolidation",
            )

        total_consolidated += promoted
        logger.info(f"提升高频记忆到语义记忆: {promoted} 条")

        # 2. 降低长期未访问记忆的重要性
        decay_cutoff = int(time.time()) - self.decay_days * 24 * 3600
        cursor.execute(
            """
            UPDATE memories_episodic
            SET importance = MAX(1, importance - 1)
            WHERE is_valid = 1
            AND (accessed_at IS NULL OR accessed_at < ?)
            AND created_at < ?
            AND importance > 1
        """,
            [decay_cutoff, decay_cutoff],
        )
        decayed = cursor.rowcount
        total_consolidated += decayed
        logger.info(f"降低未访问记忆重要性: {decayed} 条")

        conn.commit()
        logger.info(f"记忆整合完成，共处理 {total_consolidated} 条记忆")

        # F5 — return an int (total items processed), matching the other
        # tasks, so the scheduler runner's ``int(result)`` conversion works.
        # main 侧调用方/测试还按 ``result["promoted"]`` 读取明细，故返回
        # ``ConsolidationResult``（int 子类 + 只读字典视图）同时满足两者。
        await self._emit_evolution_completed(
            items_processed=total_consolidated,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        return ConsolidationResult(
            total_consolidated, promoted=promoted, decayed=decayed
        )


class ConsolidationResult(int):
    """MemoryConsolidationTask 的返回值：既是 int（items_processed 总数，
    与其他 evolution task / scheduler ``int(result)`` 约定一致），又支持
    ``result["promoted"]`` / ``result["decayed"]`` / ``result["total"]``
    明细读取（main 侧约定）。"""

    def __new__(cls, total: int, *, promoted: int = 0, decayed: int = 0):
        obj = super().__new__(cls, total)
        obj._stats = {"promoted": promoted, "decayed": decayed, "total": total}
        return obj

    def __getitem__(self, key: str) -> int:
        return self._stats[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._stats.get(key, default)

    def keys(self):
        return self._stats.keys()

    def items(self):
        return self._stats.items()

    def as_dict(self) -> Dict[str, int]:
        return dict(self._stats)


def _safe_json_loads(s: str) -> list:
    """安全地解析 JSON 字符串"""
    import json

    try:
        return json.loads(s) if s else []
    except (json.JSONDecodeError, TypeError):
        return []


class SkillConsolidationTask(BaseEvolutionTask):
    """技能巡检任务 (Round 5/7, 对标 hermes curator consolidation review)

    每周用 LLM 审阅 active 技能清单，产出 merge/archive/revise 建议，
    追加进技能审计台账（consolidation_note，append-only，不动文件）。
    人工审阅建议后走既有 archive / draft-approve 流程收口。
    LLM/provider 不可用时静默跳过（no-op，不影响调度）。
    """

    def __init__(self, db=None, config: dict = None, hooks: Optional[Any] = None):
        super().__init__(db=db, hooks=hooks)
        self.config = config or {}

    async def run_async(self):
        start = time.monotonic()
        logger.info("开始执行技能巡检任务...")
        _started = time.monotonic()
        try:
            from backend.skills.consolidator import (
                collect_active_skills,
                get_consolidation_service,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("巡检模块导入失败，跳过: %s", exc)
            await self._emit_evolution_completed(
                items_processed=0,
                duration_ms=int((time.monotonic() - start) * 1000),
            )
            return 0

        service = get_consolidation_service()
        if service is None:
            logger.info("LLM provider 未装配，技能巡检跳过")
            await self._emit_evolution_completed(
                items_processed=0,
                duration_ms=int((time.monotonic() - start) * 1000),
            )
            return 0

        skills = collect_active_skills()
        if not skills:
            logger.info("无 active 技能，巡检跳过")
            await self._emit_evolution_completed(
                items_processed=0,
                duration_ms=int((time.monotonic() - start) * 1000),
            )
            return 0

        pinned = self._pinned_names()
        suggestions = await service.scan(skills, pinned_names=sorted(pinned))

        from backend.skills.audit import SkillAuditLog

        audit_log = SkillAuditLog(db=self.db)
        recorded = 0
        for suggestion in suggestions:
            ok = audit_log.record(
                "+".join(suggestion.get("skill_names", [])),
                "consolidation_note",
                actor="system",
                after_content=json.dumps(suggestion, ensure_ascii=False),
                source="consolidation_cron",
            )
            if ok:
                recorded += 1

        # Round 9: merge/revise 建议自动生成草稿（pending，走既有审批面）
        drafts_created = 0
        try:
            from backend.skills.consolidator import collect_skill_docs

            skill_docs = collect_skill_docs(
                sorted({n for s in suggestions for n in s.get("skill_names", [])})
            )
            from backend.skills.draft_store import get_skill_draft_store as _gds

            drafts_created = await service.generate_drafts(
                suggestions, skill_docs, _gds(), source="consolidation_cron"
            )
        except Exception as exc:  # noqa: BLE001 — 草稿生成失败不影响台账记录
            logger.warning("巡检草稿生成失败: %s", exc)

        record_evolution_log(
            self.db,
            evolution_type="skill_consolidation",
            description=f"技能巡检完成: {len(skills)} 个技能, {recorded} 条建议",
            status="success",
            duration_ms=elapsed_ms(_started),
            metrics={
                "skills_scanned": len(skills),
                "suggestions_recorded": recorded,
                "drafts_created": drafts_created,
            },
        )
        logger.info(f"技能巡检完成: {recorded} 条建议, {drafts_created} 个草稿")
        await self._emit_evolution_completed(
            items_processed=recorded + drafts_created,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        return recorded + drafts_created

    def _pinned_names(self):
        try:
            from backend.skills.lifecycle import get_lifecycle_store

            return get_lifecycle_store().get_pinned_names()
        except Exception:  # noqa: BLE001
            return set()


class MemoryReflectionTask(BaseEvolutionTask):
    """P4 每周反思（对标 Generative Agents reflection + Mem0 consolidation）。

    写入口的 P3 冲突消解只看"这一次写入"；时间一长仍会积累跨时间的
    近重复与相互矛盾的事实。反思任务每周把近窗口新增记忆按**归属**
    (scope + project_key) 分组整理：

    - 启发式路（恒执行，确定性）：组内近重复聚类（相似度 ≥0.97），
      保留最新一条，其余 ``invalidate()``；
    - LLM 路（best-effort）：编号事实交给模型，输出 MERGE（多条同主题
      精炼成一条）、KEEP（显式保留的独特记忆，优先于其余两种操作）与
      INVALIDATE（被新事实否定 = DELETE 型冲突）操作。
      模型不可用 / 输出不可解析 / 越界 id 一律忽略，绝不抛异常。
    - 主题簇巩固（Task 3.2）：同归属、同分类的记忆按相似度聚成主题簇，
      ≥3 条的簇由 LLM 归纳出一条主题摘要（importance=7），作为额外的
      "主题入口"写入情景层。原始记忆保持有效 —— 摘要可能丢细节，
      用它取代原始事实风险过高。

    绝不跨组整理（与 P3 冲突候选的归属对齐语义一致）；每个操作写
    ``memories_evolution_log`` 审计，任务级写 ``evolution_log``
    （``SELECT MAX(created_at) WHERE evolution_type='memory_reflection'``
    即"上次反思时间"，无需新表）。
    """

    DEFAULT_WINDOW_DAYS = 7
    DEFAULT_SAMPLE_LIMIT = 120
    #: 与 conflict.NOOP_THRESHOLD 同值：近重复判定
    DEDUPE_SIMILARITY = 0.97
    #: 单组送 LLM 的条数上限（控提示词体积）。80 条仍远低于上下文预算：
    #: 每条截断 300 字 ≈ 24k 字符，而分组本身已按归属（scope+project）切小。
    LLM_GROUP_LIMIT = 80
    #: 单条内容截断长度 —— 160 字会截掉长句后半段，模型据此判重/合并时
    #: 看不到关键限定语（"……不使用 ruff……"），合并产物容易丢约束。
    LLM_CONTENT_TRUNC = 300
    #: 主题簇聚类阈值（语义嵌入器可用时用余弦，否则退化为字面相似度）
    CLUSTER_SIMILARITY = 0.75
    #: 少于 3 条不生成主题摘要 —— 2 条同主题更接近重复，交给去重/MERGE
    MIN_CLUSTER_SIZE = 3

    def __init__(
        self, db=None, memory_manager=None, llm_client=None, config: dict = None
    ):
        super().__init__(db=db, memory_manager=memory_manager)
        self.llm = llm_client
        self.config = config or {}

    # ---- 数据收集 ----------------------------------------------------------

    def _collect_recent(self) -> List[dict]:
        """取反思窗口内的活跃记忆（两表, 带归属与层级标记）。"""
        try:
            window_days = int(self.config.get("window_days", self.DEFAULT_WINDOW_DAYS))
        except (TypeError, ValueError):
            window_days = self.DEFAULT_WINDOW_DAYS
        try:
            sample_limit = int(self.config.get("sample_limit", self.DEFAULT_SAMPLE_LIMIT))
        except (TypeError, ValueError):
            sample_limit = self.DEFAULT_SAMPLE_LIMIT
        cutoff_ms = int(time.time() * 1000) - window_days * 86_400_000

        conn = self.db.get_connection()
        rows: List[dict] = []
        # semantic 表没有 memory_category 列 —— 用 NULL 对齐结果形状，
        # 主题簇巩固只处理情景层（有分类轴的记忆）。
        for layer, table, extra, category_expr in (
            ("episodic", "memories_episodic", "AND is_valid = 1", "memory_category"),
            ("semantic", "memories_semantic", "", "NULL"),
        ):
            try:
                cursor = conn.execute(
                    f"SELECT id, content, created_at, scope, project_key, "
                    f"{category_expr} AS memory_category "
                    f"FROM {table} "
                    f"WHERE invalid_at IS NULL AND created_at >= ? {extra} "
                    f"ORDER BY created_at DESC LIMIT ?",
                    (cutoff_ms, sample_limit),
                )
            except Exception as exc:  # noqa: BLE001 — 表异常时按无候选处理
                logger.warning(f"反思候选读取失败({layer}): {exc}")
                continue
            for row in cursor.fetchall():
                d = dict(row)
                d["memory_layer"] = layer
                rows.append(d)
        return rows

    @staticmethod
    def _group_by_attribution(rows: List[dict]) -> Dict[tuple, List[dict]]:
        """按归属分组：scope + project_key 完全一致才可能互相整理。"""
        groups: Dict[tuple, List[dict]] = {}
        for r in rows:
            key = (r.get("scope") or "user", r.get("project_key"))
            groups.setdefault(key, []).append(r)
        return groups

    # ---- 启发式：组内近重复去重 ---------------------------------------------

    def _heuristic_dedupe(self, groups: Dict[tuple, List[dict]]) -> List[str]:
        from backend.memory.conflict import _similarity

        invalidated_ids: List[str] = []
        for rows in groups.values():
            if len(rows) < 2:
                continue
            # created_at 降序：第一条为"最新代表"，与其近重复的旧行失效
            ordered = sorted(rows, key=lambda r: r.get("created_at") or 0, reverse=True)
            reps: List[dict] = []
            for row in ordered:
                dup_of = next(
                    (
                        rep
                        for rep in reps
                        if _similarity(row.get("content") or "", rep.get("content") or "")
                        >= self.DEDUPE_SIMILARITY
                    ),
                    None,
                )
                if dup_of is not None:
                    if self._invalidate(row, f"duplicate of {dup_of['id']} (reflect dedupe)"):
                        invalidated_ids.append(row["id"])
                else:
                    reps.append(row)
        return invalidated_ids

    # ---- 主题簇巩固：同分类聚类 → 主题摘要 ----------------------------------

    def _resolve_semantic_embedder(self):
        """取语义嵌入器（manager 自带优先，其次进程共享单例）；没有返回 None。"""
        if self.memory_manager is None:
            return None
        candidates = []
        source = getattr(self.memory_manager, "embedder", None)
        if source is not None:
            candidates.append(source)
        try:
            from backend.memory.embedder_factory import get_shared_embedder

            candidates.append(get_shared_embedder())
        except Exception as exc:  # noqa: BLE001 — 共享嵌入器不可用按无语义处理
            logger.debug(f"共享嵌入器解析失败，主题簇退化字面相似度: {exc}")
        for candidate in candidates:
            try:
                embedder = candidate if hasattr(candidate, "encode") else candidate()
            except Exception:  # noqa: BLE001 — 工厂异常按不可用处理
                continue
            if embedder is not None and getattr(embedder, "is_semantic", False):
                return embedder
        return None

    def _similarity_fn(self, rows: List[dict]):
        """返回 ``(a_row, b_row) -> 相似度``；语义余弦优先，失败退化字面。"""
        from backend.memory.conflict import _cosine_similarity, _similarity

        embedder = self._resolve_semantic_embedder()
        if embedder is not None and rows:
            try:
                vectors = embedder.encode_batch(
                    [r.get("content") or "" for r in rows]
                )
            except Exception as exc:  # noqa: BLE001 — 编码失败退化字面
                logger.debug(f"主题簇语义编码失败，退化为字面相似度: {exc}")
                vectors = None
            if vectors and len(vectors) == len(rows):
                by_id = {r["id"]: v for r, v in zip(rows, vectors)}
                return lambda a, b: _cosine_similarity(by_id[a["id"]], by_id[b["id"]])
        return lambda a, b: _similarity(a.get("content") or "", b.get("content") or "")

    @staticmethod
    def _cluster_by_similarity(
        rows: List[dict], threshold: float, sim_fn
    ) -> List[List[dict]]:
        """贪心前导聚类：与簇代表（最新一条）相似度 ≥ threshold 即入簇。

        单链接而非全连接：主题簇允许"链式"相关，只要都与代表足够像。
        调用方保证 rows 按 created_at 降序，结果确定可复现。
        """
        clusters: List[List[dict]] = []
        for row in rows:
            for cluster in clusters:
                if sim_fn(row, cluster[0]) >= threshold:
                    cluster.append(row)
                    break
            else:
                clusters.append([row])
        return clusters

    async def _generate_topic_summary(
        self, cluster: List[dict], category: str
    ) -> Optional[str]:
        """用 LLM 把一个主题簇归纳成一条可独立理解的摘要。"""
        llm = self._resolve_llm()
        if llm is None:
            return None
        lines = [
            f"- {(r.get('content') or '')[: self.LLM_CONTENT_TRUNC]}"
            for r in cluster[: self.LLM_GROUP_LIMIT]
        ]
        prompt = (
            f"下面是同一主题（分类: {category}）的 {len(lines)} 条记忆。请归纳成一条"
            "完整、可独立理解的主题摘要，不超过 200 字。必须保留关键限定语"
            "（版本、范围、例外、否定表述），不要编造未出现的信息。"
            "只输出摘要正文，不要编号、不要解释。\n\n" + "\n".join(lines)
        )
        summary = (await self._chat(llm, prompt)).strip()
        return summary[:400] if summary else None

    def _summary_exists(self, category: str, summary: str) -> bool:
        """同分类已有近重复摘要则跳过（每周运行会反复看到同一簇）。"""
        from backend.memory.conflict import _similarity

        try:
            rows = self.memory_manager.episodic.find_by_category(
                f"{category}_summary", limit=50
            )
        except Exception as exc:  # noqa: BLE001 — 查不到按"不存在"处理
            logger.debug(f"主题摘要查重失败: {exc}")
            return False
        return any(
            _similarity(summary, r.get("content") or "") >= 0.90 for r in rows
        )

    def create_summary_memory(
        self,
        content: str,
        category: str,
        source_memory_ids: List[str],
        importance: int = 7,
        attribution: tuple = ("user", None),
    ) -> Optional[str]:
        """写一条主题摘要记忆；原始记忆保持有效（摘要是补充入口，不是取代）。

        来源 id 记入记忆级审计日志：schema 没有来源列，
        ``memories_evolution_log.before_content`` 是既有的可审计通道。
        """
        if self.memory_manager is None or not content:
            return None
        if self._summary_exists(category, content):
            return None
        scope, project_key = attribution
        try:
            memory_id = self.memory_manager.episodic.save(
                content=content,
                summary=content,
                importance=importance,
                memory_type="summary",
                memory_category=f"{category}_summary",
                scope=scope,
                project_key=project_key,
            )
        except Exception as exc:  # noqa: BLE001 — 摘要写入失败不拖垮任务
            logger.warning(f"主题摘要落库失败: {exc}")
            return None
        _write_evolution_log(
            self.db,
            memory_type="episodic",
            memory_id=memory_id,
            operation="consolidate_summary",
            before_content="+".join(source_memory_ids)[:512],
            after_content=content,
            reason=f"memory_reflection:consolidation:{category}",
        )
        return memory_id

    async def _consolidate_related_memories(
        self, groups: Dict[tuple, List[dict]], skip_ids: Optional[set] = None
    ) -> int:
        """同归属、同分类 → 相似度聚类 → 为 ≥MIN_CLUSTER_SIZE 的簇生成主题摘要。

        原始记忆保持有效：主题摘要可能丢细节，用它取代原始事实风险过高；
        摘要的价值是给检索多一个"主题入口"。
        """
        skip_ids = skip_ids or set()
        created = 0
        for (scope, project_key), rows in groups.items():
            by_category: Dict[str, List[dict]] = {}
            for row in rows:
                if row["id"] in skip_ids:
                    continue
                category = (row.get("memory_category") or "").strip()
                # 摘要行不再参与巩固（否则会出现 *_summary_summary 套娃）
                if not category or category.endswith("_summary"):
                    continue
                by_category.setdefault(category, []).append(row)
            for category, members in by_category.items():
                if len(members) < self.MIN_CLUSTER_SIZE:
                    continue
                ordered = sorted(
                    members, key=lambda r: r.get("created_at") or 0, reverse=True
                )
                sim_fn = self._similarity_fn(ordered)
                for cluster in self._cluster_by_similarity(
                    ordered, self.CLUSTER_SIMILARITY, sim_fn
                ):
                    if len(cluster) < self.MIN_CLUSTER_SIZE:
                        continue
                    summary = await self._generate_topic_summary(cluster, category)
                    if not summary:
                        continue
                    if self.create_summary_memory(
                        content=summary,
                        category=category,
                        source_memory_ids=[m["id"] for m in cluster],
                        attribution=(scope, project_key),
                    ):
                        created += 1
        return created

    # ---- LLM 路：MERGE / KEEP / INVALIDATE ----------------------------------

    async def _run_llm_ops(
        self, groups: Dict[tuple, List[dict]]
    ) -> Tuple[Dict[str, int], set]:
        """跑 LLM 整理。返回 (计数, 被失效的行 id)。

        被失效的 id 要交给主题簇巩固 —— 已被合并/判过时的行不该再进摘要，
        否则摘要把一条已经被取代的旧事实又写一遍。
        """
        stats = {"merged": 0, "invalidated": 0, "kept": 0}
        touched: set = set()
        llm = self._resolve_llm()
        if llm is None:
            return stats, touched
        for (scope, project_key), rows in groups.items():
            if len(rows) < 2:
                continue
            ordered = sorted(rows, key=lambda r: r.get("created_at") or 0, reverse=True)
            sample = ordered[: self.LLM_GROUP_LIMIT]
            lines = [
                f"{i}. [{r['memory_layer']}] {(r.get('content') or '')[: self.LLM_CONTENT_TRUNC]}"
                for i, r in enumerate(sample, 1)
            ]
            prompt = (
                "你是记忆整理专家。下面是同一归属下的近期记忆（编号列出，每条带存储层级）。"
                "你的目标是减少重复、剔除过时事实，同时保留独特且重要的信息。请输出一个 "
                "JSON 数组，每项是一个操作，只允许三种操作：\n"
                '1. {"op": "MERGE", "ids": [<同一主题的多条编号，2 条以上>], '
                '"content": "<合并精炼后的一条事实，不超过 120 字>"}\n'
                '2. {"op": "KEEP", "id": <编号>, "reason": "<为什么独特且应当保留>"}\n'
                '3. {"op": "INVALIDATE", "id": <编号>, "reason": "<为什么被更晚的记忆否定或已过时>"}\n'
                "规则：只在列表内部操作，编号必须真实存在；MERGE 只合并语义重复或同一主题"
                "的不同侧面，主题不同不要强行合并；KEEP 用于明确标记不参与合并的独特记忆"
                "（与 MERGE/INVALIDATE 冲突时以 KEEP 为准）；没有值得整理的就输出 []。"
                "只输出 JSON，无其他文字。\n\n" + "\n".join(lines)
            )
            content = await self._chat(llm, prompt)
            ops = self._parse_ops(content)
            kept_ids = self._kept_ids(ops, sample)
            for op_obj in ops:
                self._apply_llm_op(
                    op_obj, sample, (scope, project_key), stats, kept_ids, touched
                )
        return stats, touched

    @staticmethod
    def _indexed_row(raw_idx, sample: List[dict]) -> Optional[dict]:
        """1-based 序号 → sample 行；非法或越界返回 None（模型不可信）。"""
        try:
            idx = int(raw_idx) - 1
        except (TypeError, ValueError):
            return None
        return sample[idx] if 0 <= idx < len(sample) else None

    @classmethod
    def _kept_ids(cls, ops: List[dict], sample: List[dict]) -> set:
        """KEEP 显式保护的行 id。

        模型偶尔自相矛盾（同一编号既 MERGE 又 KEEP）。丢失记忆不可逆，
        因此 KEEP 优先：被保护的行不参与失效。空 KEEP 无副作用。
        """
        kept = set()
        for op_obj in ops:
            if str(op_obj.get("op", "")).upper() != "KEEP":
                continue
            row = cls._indexed_row(op_obj.get("id"), sample)
            if row is not None:
                kept.add(row["id"])
        return kept

    def _apply_llm_op(
        self,
        op_obj: dict,
        sample: List[dict],
        attribution: tuple,
        stats: Dict[str, int],
        kept_ids: Optional[set] = None,
        touched: Optional[set] = None,
    ) -> None:
        """应用一条 LLM 操作；编号用 1-based 序号（模型不擅长复述 UUID）。

        ``touched`` 收集被失效的行 id，供主题簇巩固跳过它们。
        """
        kept_ids = kept_ids or set()
        touched = touched if touched is not None else set()
        op = str(op_obj.get("op", "")).upper()
        if op == "MERGE":
            members = []
            seen_ids = set()
            for raw_idx in op_obj.get("ids") or []:
                row = self._indexed_row(raw_idx, sample)
                if row is None or row["id"] in seen_ids or row["id"] in kept_ids:
                    continue
                seen_ids.add(row["id"])
                members.append(row)
            merged = str(op_obj.get("content") or "").strip()[:300]
            if len(members) < 2 or not merged:
                return
            if not all(self._invalidate(m, f"merged by reflection: {merged[:80]}") for m in members):
                # 部分失效失败也继续写合并产物（丢失的行仍在, 只是未退出检索）
                logger.warning("反思 MERGE: 部分成员失效失败")
            self._write_merged_fact(merged, members, attribution)
            stats["merged"] += 1
            touched.update(m["id"] for m in members)
        elif op == "INVALIDATE":
            row = self._indexed_row(op_obj.get("id"), sample)
            if row is None or row["id"] in kept_ids:
                return
            reason = str(op_obj.get("reason") or "negated by newer fact")[:200]
            if self._invalidate(row, f"reflect invalidate: {reason}"):
                stats["invalidated"] += 1
                touched.add(row["id"])
        elif op == "KEEP":
            stats["kept"] += 1

    def _write_merged_fact(
        self, merged: str, members: List[dict], attribution: tuple
    ) -> None:
        """合并产物写回最新成员所在层，携带 supersedes 链与归属。"""
        scope, project_key = attribution
        newest = max(members, key=lambda r: r.get("created_at") or 0)
        try:
            if newest["memory_layer"] == "semantic":
                self.memory_manager.semantic.save(
                    content=merged,
                    summary=None,
                    tags=["reflection"],
                    scope=scope,
                    project_key=project_key,
                    supersedes_id=newest["id"],
                )
            else:
                self.memory_manager.episodic.save(
                    content=merged,
                    importance=6,
                    memory_type="reflection",
                    scope=scope,
                    project_key=project_key,
                    supersedes_id=newest["id"],
                )
            _write_evolution_log(
                self.db,
                memory_type=newest["memory_layer"],
                memory_id="+".join(m["id"] for m in members)[:512],
                operation="reflect_merge",
                before_content=" | ".join((m.get("content") or "")[:80] for m in members),
                after_content=merged,
                reason="memory_reflection",
            )
        except Exception as exc:  # noqa: BLE001 — 单条合并失败不拖垮任务
            logger.warning(f"反思 MERGE 落库失败: {exc}")

    def _invalidate(self, row: dict, reason: str) -> bool:
        """按层失效一条记忆 + 记忆级审计日志。"""
        try:
            store = (
                self.memory_manager.episodic
                if row["memory_layer"] == "episodic"
                else self.memory_manager.semantic
            )
            ok = store.invalidate(row["id"])
            if ok:
                _write_evolution_log(
                    self.db,
                    memory_type=row["memory_layer"],
                    memory_id=row["id"],
                    operation="reflect_invalidate",
                    before_content=(row.get("content") or "")[:200],
                    reason=f"memory_reflection: {reason}"[:300],
                )
            return bool(ok)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"反思失效失败({row.get('id')}): {exc}")
            return False

    # ---- LLM 客户端 / 调用（与 PreferenceLearningTask 同模式） ----------------

    def _resolve_llm(self):
        if self.llm is not None:
            return self.llm
        try:
            from backend.core.legacy.llm_client import LLMClient, LLMConfig
            from backend.orchestration.llm_factory import load_llm_config_from_settings

            cfg = load_llm_config_from_settings()
            if cfg is None:
                return None
            return LLMClient(LLMConfig(**cfg))
        except Exception as exc:  # noqa: BLE001 — 降级纯启发式, 不拖垮定时任务
            logger.warning(f"记忆反思 LLM 客户端解析失败，仅走启发式去重: {exc}")
            return None

    async def _chat(self, llm, prompt: str) -> str:
        try:
            try:
                from backend.domain.message import Message

                response_msg = await llm.chat(messages=[Message(role="user", content=prompt)])
                return (
                    response_msg.content
                    if hasattr(response_msg, "content")
                    else str(response_msg)
                )
            except (ImportError, TypeError, AttributeError):
                response = await llm.chat(messages=[{"role": "user", "content": prompt}])
                return response if isinstance(response, str) else str(response.get("content", ""))
        except Exception as exc:  # noqa: BLE001 — LLM 故障降级
            logger.warning(f"记忆反思 LLM 调用失败，本轮跳过模型整理: {exc}")
            return ""

    @staticmethod
    def _parse_ops(raw: str) -> List[dict]:
        """宽容解析 LLM 输出的操作数组（容忍围栏与多余文字）。"""
        if not raw:
            return []
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end <= start:
            return []
        try:
            data = json.loads(text[start : end + 1])
        except (json.JSONDecodeError, ValueError):
            return []
        return [o for o in data if isinstance(o, dict)][:20]

    # ---- 主流程 -------------------------------------------------------------

    async def run_async(self) -> Dict[str, int]:
        logger.info("开始执行记忆反思任务...")
        _started = time.monotonic()
        stats = {
            "scanned": 0,
            "deduped": 0,
            "merged": 0,
            "invalidated": 0,
            "kept": 0,
            "consolidated": 0,
        }
        try:
            if self.memory_manager is None:
                logger.info("记忆反思缺少 memory_manager，跳过")
                record_evolution_log(
                    self.db,
                    evolution_type="memory_reflection",
                    description="跳过: 无 memory_manager",
                    status="skipped",
                    duration_ms=elapsed_ms(_started),
                    metrics=stats,
                )
                return stats

            rows = self._collect_recent()
            stats["scanned"] = len(rows)
            groups = self._group_by_attribution(rows)

            deduped_ids = set(self._heuristic_dedupe(groups))
            stats["deduped"] = len(deduped_ids)
            if deduped_ids:
                # 已失效行不再送 LLM（避免对同一批内容重复出 MERGE 操作）
                groups = {
                    key: [r for r in v if r["id"] not in deduped_ids]
                    for key, v in groups.items()
                }
            llm_stats, invalidated_ids = await self._run_llm_ops(groups)
            stats["merged"] = llm_stats["merged"]
            stats["invalidated"] = llm_stats["invalidated"]
            stats["kept"] = llm_stats["kept"]

            stats["consolidated"] = await self._consolidate_related_memories(
                groups, skip_ids=deduped_ids | invalidated_ids
            )

            description = (
                f"记忆反思完成: 扫描 {stats['scanned']}, 去重 {stats['deduped']}, "
                f"合并 {stats['merged']}, 失效 {stats['invalidated']}, "
                f"主题摘要 {stats['consolidated']}"
            )
            record_evolution_log(
                self.db,
                evolution_type="memory_reflection",
                description=description,
                status="success",
                duration_ms=elapsed_ms(_started),
                metrics=stats,
            )
            logger.info(description)
        except Exception as exc:  # noqa: BLE001 — 定时任务兜底
            logger.warning(f"记忆反思任务失败: {exc}")
            record_evolution_log(
                self.db,
                evolution_type="memory_reflection",
                description=f"记忆反思失败: {exc}",
                status="failed",
                error_message=str(exc),
                duration_ms=elapsed_ms(_started),
                metrics=stats,
            )
        return stats


def create_evolution_tasks(
    config: dict = None, hooks: Any = None
) -> Dict[str, BaseEvolutionTask]:
    """
    创建所有进化任务

    Args:
        config: 配置字典
        hooks: 可选 HookRegistry（Task 4 / Gap A）— 透传给每个任务，
            任务成功后发 ``evolution_completed`` 事件

    Returns:
        任务名称到任务的映射
    """
    db = get_database()
    config = config or {}

    tasks = {}

    # 每日摘要任务
    if config.get("daily_summary", {}).get("enabled", True):
        tasks["daily_summary"] = DailySummaryTask(db=db, config=config.get("daily_summary", {}), hooks=hooks)

    # 记忆修剪任务
    if config.get("memory_pruning", {}).get("enabled", True):
        tasks["memory_pruning"] = MemoryPruningTask(db=db, config=config.get("memory_pruning", {}), hooks=hooks)

    # 偏好学习任务
    if config.get("preference_learning", {}).get("enabled", True):
        tasks["preference_learning"] = PreferenceLearningTask(
            db=db, config=config.get("preference_learning", {}),
            hooks=hooks,
        )

    # 重要性重评估任务
    if config.get("importance_reevaluation", {}).get("enabled", True):
        tasks["importance_reevaluation"] = ImportanceReevaluationTask(
            db=db, config=config.get("importance_reevaluation", {}),
            hooks=hooks,
        )

    # 技能巡检任务 (Round 5/7) — 默认启用，每周运行；无 LLM 时 no-op
    if config.get("skill_consolidation", {}).get("enabled", True):
        tasks["skill_consolidation"] = SkillConsolidationTask(
            db=db, config=config.get("skill_consolidation", {}),
            hooks=hooks,
        )

    # 共享 MemoryManager 单例（memory_consolidation / memory_reflection 都依赖）
    mm = None
    try:
        from backend.memory.registry import get_memory_manager

        mm = get_memory_manager()
    except Exception:
        pass

    # 记忆整合任务（"做梦"）— 默认启用，每周运行
    if config.get("memory_consolidation", {}).get("enabled", True):
        tasks["memory_consolidation"] = MemoryConsolidationTask(
            db=db,
            memory_manager=mm,
            config=config.get("memory_consolidation", {}),
            hooks=hooks,
        )

    # P4 记忆反思 — 默认启用，每周一 05:00；无 LLM 时仅走启发式近重复去重
    if config.get("memory_reflection", {}).get("enabled", True):
        tasks["memory_reflection"] = MemoryReflectionTask(
            db=db,
            memory_manager=mm,
            config=config.get("memory_reflection", {}),
        )

    return tasks


def get_evolution_logs(db, limit: int = 50, offset: int = 0) -> List[dict]:
    """
    获取进化日志

    Args:
        db: 数据库实例
        limit: 返回数量限制
        offset: 偏移量

    Returns:
        进化日志列表
    """
    conn = db.get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, evolution_type, description, before_state, after_state,
               trigger_type, trigger_condition, status, error_message,
               tokens_used, duration_ms, metrics_json,
               created_at, completed_at
        FROM evolution_log
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """,
        [limit, offset],
    )

    rows = cursor.fetchall()
    return [dict(row) for row in rows]
