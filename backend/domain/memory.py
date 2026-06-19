"""Memory Domain Models

记忆系统的领域模型,用于六边形架构中的记忆上下文传递。
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MemoryContext:
    """记忆上下文 - 用于注入到 LLM prompt

    分层设计（借鉴 Hermes Agent 的冻结快照 + Mem0 的原子事实）：
    - core: 核心记忆（用户画像/偏好），始终注入，类似 Hermes 的 MEMORY.md
    - working: 工作记忆（当前对话上下文）
    - episodic: 情景记忆（对话历史和事件）
    - semantic: 语义记忆（知识和概念）

    Example:
        >>> context = MemoryContext(
        ...     core=[{"content": "用户喜欢吃火锅"}],
        ...     working=[{"role": "user", "content": "你好"}],
        ...     episodic=[{"content": "用户喜欢火锅", "importance": 7}],
        ...     semantic=[{"content": "Python 是编程语言"}]
        ... )
        >>> context.has_memories
        True
        >>> print(context.format(budget_tokens=1500))
        【用户画像】
        - 用户喜欢吃火锅

        【相关记忆】
        - 用户喜欢火锅
        - Python 是编程语言
    """

    working: list[dict[str, Any]] = field(default_factory=list)
    episodic: list[dict[str, Any]] = field(default_factory=list)
    semantic: list[dict[str, Any]] = field(default_factory=list)
    core: list[dict[str, Any]] = field(default_factory=list)

    @property
    def has_memories(self) -> bool:
        """是否有记忆

        Returns:
            True 如果任一层有记忆,否则 False
        """
        return bool(self.working or self.episodic or self.semantic or self.core)

    def format(self, budget_tokens: int = 1500) -> str:
        """格式化为可注入 prompt 的字符串（Token 预算感知）

        借鉴 Hermes Agent 的分层注入策略：
        1. 核心记忆（core）始终注入 — 用户画像/偏好（~500 token 预算）
        2. 工作记忆 + 情景/语义记忆按重要性填充剩余预算
        3. 超出预算的内容截断

        Args:
            budget_tokens: 记忆注入的总 token 预算，默认 1500

        Returns:
            格式化后的记忆上下文字符串,如果没有记忆则返回空字符串
        """
        parts: list[str] = []
        used_tokens = 0

        # ---- 核心记忆：始终注入（类似 Hermes 的 MEMORY.md）----
        if self.core:
            core_lines = []
            for mem in self.core:
                content = mem.get("content", "")[:150]
                core_lines.append(f"- {content}")
            core_text = "【用户画像】\n" + "\n".join(core_lines)
            core_tokens = self._estimate_tokens(core_text)
            if core_tokens <= budget_tokens:
                parts.append(core_text)
                used_tokens += core_tokens

        # ---- 工作记忆：最近 3 条 ----
        if self.working:
            working_lines = []
            for msg in self.working[-3:]:
                content = msg.get("content", "")[:100]
                role = msg.get("role", "unknown")
                working_lines.append(f"- [{role}]: {content}")
            working_text = "【当前对话】\n" + "\n".join(working_lines)
            working_tokens = self._estimate_tokens(working_text)
            if used_tokens + working_tokens <= budget_tokens:
                parts.append(working_text)
                used_tokens += working_tokens

        # ---- 情景 + 语义记忆：按重要性排序，填充剩余预算 ----
        memory_items = list(self.episodic) + list(self.semantic)
        memory_items.sort(
            key=lambda m: m.get("importance", m.get("rrf_score", 0)),
            reverse=True,
        )

        memory_lines: list[str] = []
        for mem in memory_items:
            summary = mem.get("summary", mem.get("content", ""))[:100]
            line = f"- {summary}"
            line_tokens = self._estimate_tokens(line)
            if used_tokens + line_tokens > budget_tokens:
                break
            memory_lines.append(line)
            used_tokens += line_tokens

        if memory_lines:
            parts.append("【相关记忆】\n" + "\n".join(memory_lines))

        return "\n\n".join(parts) if parts else ""

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """粗略估算 token 数量（中文约 1.5 字/token，英文约 4 字符/token）"""
        chinese_chars = sum(1 for c in text if "一" <= c <= "鿿")
        other_chars = len(text) - chinese_chars
        return int(chinese_chars / 1.5 + other_chars / 4)
