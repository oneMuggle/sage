"""
被动读取循环检测 (A13 NudgeGuard, from LLM_Simple)

当用户要求"创建/写入/修改"等动作，但模型只执行被动读取操作
（read_file / list_dir / web_search 等）时，注入推动消息促使模型
转向实际执行，而不是无限地读下去。

问题：
- 用户说"帮我写一个脚本"，模型却反复 read_file / search 不动手
- 被动读取循环浪费 token 且无法产出交付物

解决方案：
- 检测用户消息中的动作关键词（写/创建/修改/write/create/...）
- 检测一轮 tool_calls 是否全部为被动读取工具
- 连续 passive_threshold 轮全被动时注入 nudge 消息

使用示例：
    guard = NudgeGuard()

    nudge = guard.check(user_message, tool_calls)
    if nudge:
        # 将 nudge 作为 system/user 消息注入上下文
        messages.append({"role": "user", "content": nudge})

    # 新会话/新用户消息时重置连续计数
    guard.reset()

Ported from LLM_Simple's api/middleware/nudge.py, with Sage tool names
and a configurable passive threshold.
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, Iterable, List, Optional

# Sage 中只读（无副作用）的工具名
DEFAULT_PASSIVE_READ_TOOLS: FrozenSet[str] = frozenset({
    "read_file",
    "list_dir",
    "web_search",
    "web_fetch",
    "memory_search",
    "office_list",
    "office_read",
    "calculator",
})

# 表明用户期望"动作"而非"信息"的关键词（中英文）
DEFAULT_ACTION_KEYWORDS: FrozenSet[str] = frozenset({
    # 中文
    "写", "创建", "新建", "生成", "制作", "修改", "改正", "修复",
    "实现", "开发", "构建", "运行", "执行", "测试",
    "总结", "概括", "整理", "翻译", "转换",
    # 英文
    "write", "create", "generate", "make", "build",
    "fix", "modify", "change", "implement", "develop",
    "run", "execute", "test", "summarize", "translate",
})

# 注入的推动消息（引导模型转向 Sage 的写入/执行工具）
DEFAULT_NUDGE_MESSAGE: str = (
    "Stop reading. You have gathered enough information. "
    "Now COMPLETE the user's request — use write_file or terminal "
    "to produce the output. Do NOT read more files. "
    "Take action NOW."
)


class NudgeGuard:
    """
    监控工具调用，在模型陷入被动读取循环时注入推动消息。

    判定条件（同时满足）：
    1. 用户消息包含动作关键词（写/创建/修改 等）
    2. 连续 passive_threshold 轮的 tool_calls 全部为被动读取工具

    任一条件不满足（或出现任意主动工具调用）即重置连续计数。

    Attributes:
        passive_threshold: 连续多少轮全被动读取后触发 nudge（默认 1）
    """

    def __init__(
        self,
        passive_tools: Optional[Iterable[str]] = None,
        action_keywords: Optional[Iterable[str]] = None,
        nudge_message: Optional[str] = None,
        passive_threshold: int = 1,
    ) -> None:
        """
        Args:
            passive_tools:     被动读取工具名集合（默认 Sage 内置只读工具）
            action_keywords:   动作关键词集合（默认中英文常用词）
            nudge_message:     注入的推动消息（默认引导 write_file / terminal）
            passive_threshold: 连续全被动轮数阈值，>=1
        """
        if passive_threshold < 1:
            raise ValueError(f"passive_threshold must be >= 1, got {passive_threshold}")

        self._passive_tools: FrozenSet[str] = (
            frozenset(passive_tools) if passive_tools is not None
            else DEFAULT_PASSIVE_READ_TOOLS
        )
        self._action_keywords: FrozenSet[str] = (
            frozenset(kw.lower() for kw in action_keywords)
            if action_keywords is not None
            else DEFAULT_ACTION_KEYWORDS
        )
        self._nudge_message: str = (
            nudge_message if nudge_message is not None
            else DEFAULT_NUDGE_MESSAGE
        )
        self.passive_threshold: int = passive_threshold
        self._passive_streak: int = 0

    @property
    def passive_streak(self) -> int:
        """当前连续全被动读取轮数"""
        return self._passive_streak

    def check(
        self,
        user_message: str,
        tool_calls: List[Dict[str, Any]],
    ) -> Optional[str]:
        """
        检查一轮工具调用是否陷入被动读取循环。

        兼容两种 tool_call 结构：
        - OpenAI 风格: {"function": {"name": "read_file", ...}}
        - 扁平风格:    {"name": "read_file", ...}

        Args:
            user_message: 当前会话的用户原始消息
            tool_calls:   本轮模型发起的工具调用列表

        Returns:
            需要注入的 nudge 消息；无需干预时返回 None。
        """
        # 条件 1：用户是否期望动作
        if not self._wants_action(user_message):
            self._passive_streak = 0
            return None

        # 条件 2：本轮是否全部为被动读取（空列表视为非被动）
        names = set()
        for tc in tool_calls:
            fn = tc.get("function", tc) if isinstance(tc, dict) else {}
            name = fn.get("name", "") if isinstance(fn, dict) else ""
            if name:
                names.add(name)

        all_passive = bool(names) and names.issubset(self._passive_tools)

        if all_passive:
            self._passive_streak += 1
            if self._passive_streak >= self.passive_threshold:
                return self._nudge_message
        else:
            self._passive_streak = 0

        return None

    def reset(self) -> None:
        """重置连续被动读取计数（新会话/新用户消息时调用）"""
        self._passive_streak = 0

    def _wants_action(self, user_message: str) -> bool:
        """用户消息是否包含动作关键词（子串匹配，中文按字、英文按词面）"""
        msg_lower = (user_message or "").lower()
        return any(kw in msg_lower for kw in self._action_keywords)
