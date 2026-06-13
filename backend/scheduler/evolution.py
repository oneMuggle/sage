"""
进化任务实现
包含每日摘要、记忆修剪、偏好学习、重要性重评估等任务
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime

from backend.data.database import get_database

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
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self.run_async())
        finally:
            loop.close()


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

    async def _generate_summary(self, messages: list[dict]) -> str | None:
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

        conn.commit()
        logger.info(f"记忆修剪完成，共删除 {total_deleted} 条记忆")

        # 记录进化日志
        await self._log_evolution(
            evolution_type="memory_pruning",
            description=f"记忆修剪完成，删除了 {total_deleted} 条记忆，当前记忆数: {current_count - total_deleted}",
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
        """执行偏好学习"""
        logger.info("开始执行偏好学习任务...")

        conn = self.db.get_connection()
        cursor = conn.cursor()

        # 1. 获取近期反馈消息（包含反馈关键词的用户消息）
        feedback_keywords = [
            "反馈",
            "评分",
            "喜欢",
            "不喜欢",
            "太短",
            "太长",
            "详细",
            "简单",
            "好",
            "差",
        ]
        "%" + "%".join(feedback_keywords) + "%"

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
        logger.info(f"找到 {len(feedback_messages)} 条反馈消息")

        if not feedback_messages:
            logger.info("没有发现新的反馈，跳过")
            return 0

        # 2. 分析偏好模式
        preferences = self._analyze_preferences(feedback_messages)

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

    def _analyze_preferences(self, feedback_messages: list[dict]) -> dict[str, str]:
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


def create_evolution_tasks(config: dict = None) -> dict[str, BaseEvolutionTask]:
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

    return tasks


def get_evolution_logs(db, limit: int = 50, offset: int = 0) -> list[dict]:
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
