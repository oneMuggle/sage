"""Memory Domain Models

记忆系统的领域模型,用于六边形架构中的记忆上下文传递。
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class MemoryContext:
    """记忆上下文 - 用于注入到 LLM prompt

    包含三层记忆:
    - working: 工作记忆 (当前对话上下文)
    - episodic: 情景记忆 (对话历史和事件)
    - semantic: 语义记忆 (知识和概念)

    Example:
        >>> context = MemoryContext(
        ...     working=[{"role": "user", "content": "你好"}],
        ...     episodic=[{"content": "用户喜欢火锅", "summary": "偏好"}],
        ...     semantic=[{"content": "Python 是编程语言", "summary": "知识"}]
        ... )
        >>> context.has_memories
        True
        >>> print(context.format())
        【当前对话】
        - [user]: 你好

        【相关经历】
        - 偏好

        【相关知识】
        - 知识
    """

    working: list[dict[str, Any]]
    episodic: list[dict[str, Any]]
    semantic: list[dict[str, Any]]

    @property
    def has_memories(self) -> bool:
        """是否有记忆

        Returns:
            True 如果任一层有记忆,否则 False
        """
        return bool(self.working or self.episodic or self.semantic)

    def format(self) -> str:
        """格式化为可注入 prompt 的字符串

        将三层记忆格式化为可读的文本,用于注入到 LLM 的 system prompt。

        Returns:
            格式化后的记忆上下文字符串,如果没有记忆则返回空字符串
        """
        parts = []

        # 格式化工作记忆 (最近 3 条)
        if self.working:
            parts.append("【当前对话】")
            for msg in self.working[-3:]:
                content = msg.get("content", "")[:100]
                role = msg.get("role", "unknown")
                parts.append(f"- [{role}]: {content}")

        # 格式化情景记忆 (最近 3 条)
        if self.episodic:
            parts.append("\n【相关经历】")
            for mem in self.episodic[:3]:
                summary = mem.get("summary", mem.get("content", ""))[:100]
                parts.append(f"- {summary}")

        # 格式化语义记忆 (最近 3 条)
        if self.semantic:
            parts.append("\n【相关知识】")
            for mem in self.semantic[:3]:
                summary = mem.get("summary", mem.get("content", ""))[:100]
                parts.append(f"- {summary}")

        return "\n".join(parts) if parts else ""
