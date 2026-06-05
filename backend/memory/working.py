"""
Working Memory - 工作记忆模块
当前对话上下文，滑动窗口机制
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
    """

    def __init__(self, max_size: int = 20, max_tokens: int = 4000):
        """
        初始化工作记忆

        Args:
            max_size: 最大消息数量
            max_tokens: 最大 Token 数量（估算值）
        """
        self.max_size = max_size
        self.max_tokens = max_tokens
        self.messages: deque = deque(maxlen=max_size)
        self.total_tokens: int = 0
        self.session_summary: str = ""
        self.active_entities: list[str] = []
        self.temp_variables: dict[str, Any] = {}

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
        self.messages.append({
            "role": message.get("role", "unknown"),
            "content": content,
            "tokens": tokens,
            "timestamp": time.time()
        })

        self.total_tokens += tokens

        # 如果超出最大 Token 数，淘汰旧消息
        self._evict_if_needed()

        # 内存监控日志 (DEBUG级别)
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
