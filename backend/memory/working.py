"""
Working Memory - 工作记忆模块
当前对话上下文，滑动窗口机制

支持 SQLite 持久化：进程内 deque 保持高性能，同时定期快照到 SQLite，
确保重启后工作记忆不丢失。
"""

import logging
import time
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)


class WorkingMemory:
    """
    工作记忆 - 管理当前对话的上下文信息

    特性:
    - 基于 deque 实现滑动窗口
    - 支持最大消息数量限制
    - 支持 Token 数量估算
    - 自动淘汰旧消息
    - 可选的 SQLite 持久化（传入 db 参数启用）
    """

    def __init__(
        self,
        max_size: int = 20,
        max_tokens: int = 4000,
        db: Any | None = None,
        session_id: str | None = None,
    ):
        """
        初始化工作记忆

        Args:
            max_size: 最大消息数量
            max_tokens: 最大 Token 数量（估算值）
            db: 可选的 Database 实例，传入后启用持久化
            session_id: 可选的会话 ID，用于隔离不同会话的工作记忆
        """
        self.max_size = max_size
        self.max_tokens = max_tokens
        self._db = db
        self._session_id = session_id
        self.messages: deque = deque(maxlen=max_size)
        self.total_tokens: int = 0
        self.session_summary: str = ""
        self.active_entities: list[str] = []
        self.temp_variables: dict[str, Any] = {}

        # 如果提供了数据库，从快照恢复
        if self._db is not None:
            self._load_snapshot()

    def add(self, message: dict[str, Any]) -> None:
        """
        添加消息到工作记忆

        Args:
            message: 消息字典，包含 role, content 等字段
        """
        # 计算消息的估算 Token 数量（中文约 2 字符 = 1 Token）
        content = message.get("content", "")
        tokens = self._estimate_tokens(content)

        # 存储消息
        self.messages.append(
            {
                "role": message.get("role", "unknown"),
                "content": content,
                "tokens": tokens,
                "timestamp": time.time(),
            }
        )

        self.total_tokens += tokens

        # 如果超出最大 Token 数，淘汰旧消息
        self._evict_if_needed()

        # 持久化到 SQLite
        self._save_snapshot()

        logger.debug(
            f"工作记忆状态: 消息数={len(self.messages)}, "
            f"Tokens={self.total_tokens}/{self.max_tokens}"
        )

    def _estimate_tokens(self, text: str) -> int:
        """
        估算文本的 Token 数量

        Args:
            text: 输入文本

        Returns:
            估算的 Token 数量
        """
        # 简单估算：中文按字符计，英文按单词计
        chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        other_chars = len(text) - chinese_chars
        return chinese_chars + other_chars // 4 + len(text) // 4

    def _evict_if_needed(self) -> None:
        """如果超出最大 Token 数，淘汰旧消息"""
        while self.total_tokens > self.max_tokens and len(self.messages) > 1:
            old_message = self.messages.popleft()
            self.total_tokens -= old_message.get("tokens", 0)

    def get_context(self, limit: int | None = None) -> list[dict[str, Any]]:
        """
        获取当前上下文

        Args:
            limit: 可选，限制返回的消息数量

        Returns:
            消息列表
        """
        if limit is None:
            return list(self.messages)
        return list(self.messages)[-limit:]

    def get_recent(self, limit: int = 5) -> list[dict[str, Any]]:
        """
        获取最近 N 条消息

        Args:
            limit: 消息数量

        Returns:
            最近的消息列表
        """
        return list(self.messages)[-limit:]

    def clear(self) -> None:
        """清空工作记忆"""
        self.messages.clear()
        self.total_tokens = 0
        self.session_summary = ""
        self.active_entities.clear()
        self.temp_variables.clear()
        # 持久化清空状态
        self._save_snapshot()

    def set_summary(self, summary: str) -> None:
        """
        设置会话摘要

        Args:
            summary: 摘要文本
        """
        self.session_summary = summary

    def get_summary(self) -> str:
        """
        获取会话摘要

        Returns:
            摘要文本，如果未设置则返回默认描述
        """
        if self.session_summary:
            return self.session_summary
        return f"[{len(self.messages)} 条消息, ~{self.total_tokens} tokens]"

    def add_entity(self, entity: str) -> None:
        """
        添加活跃实体

        Args:
            entity: 实体名称
        """
        if entity not in self.active_entities:
            self.active_entities.append(entity)

    def set_variable(self, key: str, value: Any) -> None:
        """
        设置临时变量

        Args:
            key: 变量名
            value: 变量值
        """
        self.temp_variables[key] = value

    def get_variable(self, key: str, default: Any = None) -> Any:
        """
        获取临时变量

        Args:
            key: 变量名
            default: 默认值

        Returns:
            变量值
        """
        return self.temp_variables.get(key, default)

    # ==================== 持久化方法 ====================

    def _save_snapshot(self) -> None:
        """将当前工作记忆快照保存到 SQLite

        如果未配置数据库则静默跳过。写入失败只记录日志不抛异常。
        """
        if self._db is None:
            return

        try:
            conn = self._db.get_connection()
            # 先清空旧快照
            conn.execute(
                "DELETE FROM working_memory_snapshot WHERE session_id = ?",
                (self._session_id,),
            )
            # 插入当前所有消息
            now_ms = int(time.time() * 1000)
            for msg in self.messages:
                conn.execute(
                    """INSERT INTO working_memory_snapshot
                       (session_id, role, content, tokens, timestamp, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        self._session_id,
                        msg.get("role", "unknown"),
                        msg.get("content", ""),
                        msg.get("tokens", 0),
                        msg.get("timestamp", 0.0),
                        now_ms,
                    ),
                )
            conn.commit()
            logger.debug(
                f"工作记忆快照已保存: session={self._session_id}, " f"消息数={len(self.messages)}"
            )
        except Exception as e:
            logger.warning(f"保存工作记忆快照失败: {e}")

    def _load_snapshot(self) -> None:
        """从 SQLite 恢复工作记忆快照

        如果未配置数据库或表为空则静默跳过。加载失败只记录日志不抛异常。
        """
        if self._db is None:
            return

        try:
            conn = self._db.get_connection()
            cursor = conn.execute(
                """SELECT role, content, tokens, timestamp
                   FROM working_memory_snapshot
                   WHERE session_id = ?
                   ORDER BY id ASC""",
                (self._session_id,),
            )
            rows = cursor.fetchall()
            if rows:
                for row in rows:
                    self.messages.append(
                        {
                            "role": row["role"],
                            "content": row["content"],
                            "tokens": row["tokens"],
                            "timestamp": row["timestamp"],
                        }
                    )
                    self.total_tokens += row["tokens"]
                # 确保不超过 max_size（deque 自动截断，但 total_tokens 需要手动调整）
                self._evict_if_needed()
                logger.info(
                    f"工作记忆快照已恢复: session={self._session_id}, "
                    f"消息数={len(self.messages)}, tokens={self.total_tokens}"
                )
        except Exception as e:
            logger.warning(f"加载工作记忆快照失败: {e}")
