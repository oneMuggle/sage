"""
进化任务实现
包含每日摘要、记忆修剪、偏好学习、重要性重评估等任务
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime
from typing import Dict, List

from backend.data.database import get_database
from backend.memory.vector_store import prune_orphan_vectors

logger = logging.getLogger(__name__)


class BaseEvolutionTask:
    """进化任务基类"""

    def __init__(self, db=None, memory_manager=None):
        self.db = db or get_database()
        self.memory_manager = memory_manager

    async def run_async(self):
        """异步执行任务（子类实现）"""
        raise NotImplementedError

    def run(self):
        """同步执行任务"""
        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self.run_async())
        finally:
            loop.close()


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

    def __init__(self, db=None, memory_manager=None, llm_client=None, config: dict = None):
        super().__init__(db, memory_manager)
        self.llm = llm_client
        self.config = config or {}
        self.min_messages = self.config.get("min_messages", 3)

    async def run_async(self):
        """执行每日摘要"""
        logger.info("开始执行每日摘要任务...")

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
        await self._log_evolution(
            evolution_type="daily_summary",
            description=f"每日摘要完成，处理了 {processed} 个会话",
            status="success",
        )

        return processed

    async def _generate_summary(self, messages: List[dict]) -> str | None:
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

    async def _log_evolution(
        self,
        evolution_type: str,
        description: str,
        status: str,
        error_message: str = None,
        before_state: str = None,
        after_state: str = None,
    ):
        """记录进化日志"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO evolution_log
            (id, evolution_type, description, status, error_message, before_state, after_state,
             trigger_type, created_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                str(uuid.uuid4()),
                evolution_type,
                description,
                status,
                error_message,
                before_state,
                after_state,
                "scheduled",
                int(time.time()),
                int(time.time()) if status == "success" else None,
            ),
        )

        conn.commit()


class MemoryPruningTask(BaseEvolutionTask):
    """
    记忆修剪任务

    功能:
    1. 删除 expires_at < now 的记忆
    2. 删除 importance<=1 且 30天未访问的记忆
    3. 超过上限(1000条)时删除最旧最不重要的
    """

    def __init__(self, db=None, memory_manager=None, config: dict = None):
        super().__init__(db, memory_manager)
        self.config = config or {}
        self.max_memories = self.config.get("max_memories", 1000)

    async def run_async(self):
        """执行记忆修剪"""
        logger.info("开始执行记忆修剪任务...")

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
        cursor.execute(
            """
            DELETE FROM memories_episodic
            WHERE importance <= 1
            AND access_count = 0
            AND created_at < ?
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

        conn.commit()

        # D1 (P6): 向量库补偿式对账 —— 上面的批量 DELETE 只写主表,
        # memories_vec 的对应条目由对账清扫, 避免已删记忆仍被向量检索命中。
        orphan_vectors = prune_orphan_vectors(self.db)

        logger.info(f"记忆修剪完成，共删除 {total_deleted} 条记忆")

        # 记录进化日志
        await self._log_evolution(
            evolution_type="memory_pruning",
            description=(
                f"记忆修剪完成，删除了 {total_deleted} 条记忆，"
                f"当前记忆数: {current_count - total_deleted}，"
                f"清理孤儿向量: {orphan_vectors} 条"
            ),
            status="success",
        )

        return total_deleted

    async def _log_evolution(
        self, evolution_type: str, description: str, status: str, error_message: str = None
    ):
        """记录进化日志"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO evolution_log
            (id, evolution_type, description, status, error_message, trigger_type, created_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                str(uuid.uuid4()),
                evolution_type,
                description,
                status,
                error_message,
                "scheduled",
                int(time.time()),
                int(time.time()) if status == "success" else None,
            ),
        )

        conn.commit()


class PreferenceLearningTask(BaseEvolutionTask):
    """
    偏好学习任务

    功能:
    1. 获取用户反馈消息
    2. 分析偏好模式 (response_length, tone, detail_level)
    3. 保存到语义记忆
    """

    def __init__(self, db=None, memory_manager=None, llm_client=None, config: dict = None):
        super().__init__(db, memory_manager)
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
        logger.info("开始执行偏好学习任务...")

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
        if llm is not None:
            recent_messages = self._fetch_recent_user_messages(cursor)
            llm_preferences = await self._analyze_preferences_with_llm(
                llm, recent_messages
            )
            if llm_preferences:
                logger.info(f"LLM 偏好抽取命中 {len(llm_preferences)} 个维度")
        else:
            logger.debug("LLM 不可用，偏好学习仅走关键词路径")

        # 2. 分析偏好模式: 关键词基线 + LLM 结果覆盖
        preferences = self._analyze_preferences(feedback_messages)
        preferences.update(llm_preferences)

        # 证据门槛: 关键词与 LLM 采样均无信号时不落库 ——
        # _analyze_preferences 恒返回默认基线, 无证据也写入会每天
        # 生成一条无信息量的"用户偏好总结"（语义记忆噪音）。
        if not feedback_messages and not llm_preferences:
            logger.info("没有发现新的反馈（关键词与 LLM 采样均无信号），跳过")
            return 0

        if not preferences:
            logger.info("无法分析出明确偏好")
            return 0

        # 3. 保存到语义记忆
        profile_text = "\n".join([f"{k}: {v}" for k, v in preferences.items()])
        memory_id = str(uuid.uuid4())
        now_ts = int(time.time())

        cursor.execute(
            """
            INSERT INTO memories_semantic
            (id, content, summary, tags, created_at)
            VALUES (?, ?, ?, ?, ?)
        """,
            (
                memory_id,
                f"用户偏好总结: {profile_text}",
                f"用户偏好: {preferences.get('response_length', 'medium')}, "
                f"风格: {preferences.get('tone', 'friendly')}, "
                f"详细度: {preferences.get('detail_level', 'medium')}",
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
        logger.info(f"偏好学习完成: {preferences}")

        # 记录进化日志
        await self._log_evolution(
            evolution_type="preference_learning",
            description=f"偏好学习完成，分析出 {len(preferences)} 个偏好维度",
            status="success",
            after_state=profile_text,
        )

        return len(preferences)

    def _analyze_preferences(self, feedback_messages: List[dict]) -> Dict[str, str]:
        """
        分析用户偏好

        Args:
            feedback_messages: 反馈消息列表

        Returns:
            偏好字典
        """
        preferences = {"response_length": "medium", "tone": "friendly", "detail_level": "medium"}

        # 简单的关键词分析
        length_prefs = {"太短": "long", "太长": "short", "简短": "short", "详细": "detailed"}
        tone_prefs = {
            "友好": "friendly",
            "专业": "professional",
            "幽默": "humorous",
            "严肃": "formal",
        }
        detail_prefs = {"详细": "detailed", "简单": "brief", "复杂": "comprehensive"}

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
    ) -> Dict[str, str]:
        """LLM 抽取稳定偏好（只输出有明确证据的维度，宽容解析）

        Returns:
            形如 {"response_length": "short", ...} 的偏好字典；
            LLM 失败 / 输出不可解析 / 无证据时返回 {}。
        """
        if llm is None or not recent_messages:
            return {}

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
            return {}

        prompt = (
            "以下是用户最近与 AI 助手的对话消息采样。请从中提取用户的稳定偏好，"
            "只关注以下三个维度（取值约定）:\n"
            "- response_length: short / medium / long / detailed（用户对回复长度的要求）\n"
            "- tone: friendly / professional / humorous / formal（用户期望的语气）\n"
            "- detail_level: brief / medium / comprehensive（用户期望的详细程度）\n\n"
            "严格要求:\n"
            "1. 只输出用户**明确表达过**的偏好（例如『回答简短点』『正式一些』）；\n"
            "2. 没有证据的维度直接省略，不要猜测；\n"
            '3. 只输出 JSON 对象，无其他文字。示例: {"response_length": "short"}\n\n'
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
            return {}

        return self._parse_preference_json(content if isinstance(content, str) else "")

    def _parse_preference_json(self, raw: str) -> Dict[str, str]:
        """宽容解析 LLM 输出的偏好 JSON（容忍代码围栏与多余文字）"""
        import json

        if not raw:
            return {}
        text = raw.strip()
        # 剥离 ```json ... ``` 围栏
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        # 截取首个 { 到末个 } 之间
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return {}
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}
        if not isinstance(data, dict):
            return {}
        allowed = {
            "response_length": {"short", "medium", "long", "detailed"},
            "tone": {"friendly", "professional", "humorous", "formal"},
            "detail_level": {"brief", "medium", "comprehensive"},
        }
        result: Dict[str, str] = {}
        for key, allowed_values in allowed.items():
            value = data.get(key)
            if isinstance(value, str) and value.lower() in allowed_values:
                result[key] = value.lower()
        return result

    async def _log_evolution(
        self,
        evolution_type: str,
        description: str,
        status: str,
        error_message: str = None,
        before_state: str = None,
        after_state: str = None,
    ):
        """记录进化日志"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO evolution_log
            (id, evolution_type, description, status, error_message, before_state, after_state,
             trigger_type, created_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                str(uuid.uuid4()),
                evolution_type,
                description,
                status,
                error_message,
                before_state,
                after_state,
                "scheduled",
                int(time.time()),
                int(time.time()) if status == "success" else None,
            ),
        )

        conn.commit()


class ImportanceReevaluationTask(BaseEvolutionTask):
    """
    重要性重评估任务

    功能:
    1. 高重要性(>=7)但长期未访问 -> 降低重要性
    2. 低重要性(<=4)但频繁访问 -> 提高重要性
    """

    def __init__(self, db=None, memory_manager=None, config: dict = None):
        super().__init__(db, memory_manager)
        self.config = config or {}

    async def run_async(self):
        """执行重要性重评估"""
        logger.info("开始执行重要性重评估任务...")

        conn = self.db.get_connection()
        cursor = conn.cursor()

        now_ts = int(time.time())
        seven_days_ago = now_ts - 7 * 24 * 3600
        thirty_days_ago = now_ts - 30 * 24 * 3600

        total_adjusted = 0

        # 1. 重评估长期未访问的高重要性记忆
        cursor.execute(
            """
            SELECT id, importance, access_count, content
            FROM memories_episodic
            WHERE importance >= 7
            AND access_count < 2
            AND created_at < ?
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
        await self._log_evolution(
            evolution_type="importance_reevaluation",
            description=f"重要性重评估完成，调整了 {total_adjusted} 条记忆",
            status="success",
        )

        return total_adjusted

    async def _log_evolution(
        self, evolution_type: str, description: str, status: str, error_message: str = None
    ):
        """记录进化日志"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO evolution_log
            (id, evolution_type, description, status, error_message, trigger_type, created_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                str(uuid.uuid4()),
                evolution_type,
                description,
                status,
                error_message,
                "scheduled",
                int(time.time()),
                int(time.time()) if status == "success" else None,
            ),
        )

        conn.commit()


class MemoryConsolidationTask(BaseEvolutionTask):
    """
    记忆整合任务（"做梦"）— 借鉴 Letta 的 sleep-time compute

    功能（定期运行，例如每周日凌晨）:
    1. 识别高频访问的情景记忆 → 提升为语义记忆
    2. 识别重复/相似的记忆 → 合并为一条
    3. 降低长期未访问记忆的重要性

    类似人脑在睡眠期间整合记忆的过程。
    """

    def __init__(self, db=None, memory_manager=None, config: dict = None):
        super().__init__(db, memory_manager)
        self.config = config or {}
        self.promotion_threshold = self.config.get("promotion_access_count", 5)
        self.decay_days = self.config.get("decay_days", 30)

    async def run_async(self):
        """执行记忆整合"""
        logger.info("开始执行记忆整合任务（做梦）...")

        conn = self.db.get_connection()
        cursor = conn.cursor()
        total_consolidated = 0

        # 1. 提升高频访问的情景记忆为语义记忆
        cursor.execute(
            """
            SELECT id, content, summary, tags, importance
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

        return {
            "promoted": promoted,
            "decayed": decayed,
            "total": total_consolidated,
        }


def _safe_json_loads(s: str) -> list:
    """安全地解析 JSON 字符串"""
    import json

    try:
        return json.loads(s) if s else []
    except (json.JSONDecodeError, TypeError):
        return []


def create_evolution_tasks(config: dict = None) -> Dict[str, BaseEvolutionTask]:
    """
    创建所有进化任务

    Args:
        config: 配置字典

    Returns:
        任务名称到任务的映射
    """
    db = get_database()
    config = config or {}

    tasks = {}

    # 每日摘要任务
    if config.get("daily_summary", {}).get("enabled", True):
        tasks["daily_summary"] = DailySummaryTask(db=db, config=config.get("daily_summary", {}))

    # 记忆修剪任务
    if config.get("memory_pruning", {}).get("enabled", True):
        tasks["memory_pruning"] = MemoryPruningTask(db=db, config=config.get("memory_pruning", {}))

    # 偏好学习任务
    if config.get("preference_learning", {}).get("enabled", True):
        tasks["preference_learning"] = PreferenceLearningTask(
            db=db, config=config.get("preference_learning", {})
        )

    # 重要性重评估任务
    if config.get("importance_reevaluation", {}).get("enabled", True):
        tasks["importance_reevaluation"] = ImportanceReevaluationTask(
            db=db, config=config.get("importance_reevaluation", {})
        )

    # 记忆整合任务（"做梦"）— 默认启用，每周运行
    if config.get("memory_consolidation", {}).get("enabled", True):
        mm = None
        try:
            from backend.memory.registry import get_memory_manager

            mm = get_memory_manager()
        except Exception:
            pass
        tasks["memory_consolidation"] = MemoryConsolidationTask(
            db=db,
            memory_manager=mm,
            config=config.get("memory_consolidation", {}),
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
               tokens_used, created_at, completed_at
        FROM evolution_log
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """,
        [limit, offset],
    )

    rows = cursor.fetchall()
    return [dict(row) for row in rows]
