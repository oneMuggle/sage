"""
会话上下文压缩（M4 Session Engineering）

移植自 claw-code 的 conversation-engineering 模式
（rust/crates/runtime/src/compact.rs）:

- ``estimate_session_tokens``  → ``estimate_messages_tokens``
- ``should_compact``           → ``should_compact``（阈值 + 消息数地板）
- ``get_compact_continuation_message`` → ``continuation_message``
- ``Session::fork``            → ``backend/data/session_repo.py:fork_session``

本模块对数据库保持**纯净**：所有函数只接收消息列表（``session_repo.Message``
对象或 ``{"role", "content"}`` dict），返回新列表；落盘由调用方（API 路由层）
负责，这样压缩逻辑可以被单测完整覆盖而不触碰 SQLite。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Awaitable, Callable, List, Optional, Sequence, Tuple

from backend.memory.working import estimate_tokens

logger = logging.getLogger(__name__)

# ---- 常量 -----------------------------------------------------------------

#: 默认 token 阈值（settings key ``compact_threshold_tokens`` 可覆盖，
#: env ``SAGE_COMPACT_THRESHOLD`` 优先级最高）
DEFAULT_COMPACT_THRESHOLD_TOKENS = 6000

#: 消息数地板：少于此数量的会话永不压缩（短对话压缩只会丢信息）
MIN_COMPACT_MESSAGE_COUNT = 12

#: compact_messages 默认保留的最近消息条数
DEFAULT_KEEP_RECENT = 6

#: 续接消息前缀（claw-code continuation-message 模式）
CONTINUATION_PREFIX = "[上下文已压缩] 此前对话摘要："

#: settings KV 白名单 key（见 backend/data/settings_repo.py:KEYS）
SETTINGS_KEY = "compact_threshold_tokens"

#: env 覆盖开关
ENV_THRESHOLD_KEY = "SAGE_COMPACT_THRESHOLD"

#: compact_messages 接受的消息元素类型（session_repo.Message 对象或裸 dict）
MessageLike = Any


class CompactionError(RuntimeError):
    """压缩失败（LLM 调用失败 / 摘要为空等）。

    调用方捕获后自行决定降级策略：
    - 手动路由 → 502 + DB 不动
    - 自动压缩 → log + 继续未压缩的聊天（压缩失败永不阻塞对话）
    """


# ---- 辅助读取 --------------------------------------------------------------


def _msg_role(message: MessageLike) -> str:
    """统一读取 dict / Message 对象的 role 字段。"""
    if isinstance(message, dict):
        return str(message.get("role") or "unknown")
    return str(getattr(message, "role", None) or "unknown")


def _msg_content(message: MessageLike) -> str:
    """统一读取 dict / Message 对象的 content 字段。"""
    if isinstance(message, dict):
        return str(message.get("content") or "")
    return str(getattr(message, "content", None) or "")


# ---- 核心 API ---------------------------------------------------------------


def estimate_messages_tokens(messages: Sequence[MessageLike]) -> int:
    """估算消息列表的总 token 数。

    复用 ``backend.memory.working.estimate_tokens``（中文按字符、
    英文按 4 字符≈1 token），对每条消息的 role + content 文本估算，
    与 WorkingMemory 保持同一口径。
    """
    total = 0
    for msg in messages:
        # role 前缀本身也占 context（"[user]: " 之类），计入估算
        total += estimate_tokens(_msg_role(msg) + _msg_content(msg))
    return total


def get_compact_threshold(default: int = DEFAULT_COMPACT_THRESHOLD_TOKENS) -> int:
    """读取压缩阈值，优先级：env > settings KV > default。

    任何一层解析失败（非整数 / DB 不可用）都静默降级到下一层，
    保证阈值读取本身永不抛错。
    """
    env_raw = os.environ.get(ENV_THRESHOLD_KEY)
    if env_raw:
        try:
            return int(env_raw.strip())
        except ValueError:
            logger.warning(
                "env %s=%r 不是合法整数，回退 settings/default", ENV_THRESHOLD_KEY, env_raw
            )
    try:
        # 延迟导入避免模块级循环依赖（settings_repo → database）
        from backend.data.settings_repo import SettingsRepository

        raw = SettingsRepository().get(SETTINGS_KEY)
        if raw is not None and raw.strip():
            return int(raw.strip())
    except (ValueError, TypeError):
        logger.warning("settings %s 不是合法整数，回退 default", SETTINGS_KEY)
    except Exception as exc:  # DB 未初始化等极端场景
        logger.warning("读取 settings %s 失败: %s，回退 default", SETTINGS_KEY, exc)
    return default


def should_compact(
    messages: Sequence[MessageLike],
    threshold: Optional[int] = None,
) -> bool:
    """判断消息列表是否值得压缩。

    两个条件必须同时满足：
    1. 消息数 >= ``MIN_COMPACT_MESSAGE_COUNT``（地板，保护短对话）
    2. 估算 token 数 >= 阈值（``threshold`` 缺省时走 ``get_compact_threshold``）
    """
    if len(messages) < MIN_COMPACT_MESSAGE_COUNT:
        return False
    effective_threshold = (
        threshold if threshold is not None else get_compact_threshold()
    )
    return estimate_messages_tokens(messages) >= effective_threshold


def build_compaction_prompt(messages: Sequence[MessageLike]) -> str:
    """构造让 LLM 生成结构化摘要的中文 prompt。

    摘要要求四段式（目标 / 决策 / 关键事实 / 待办），风格与
    scheduler/evolution.py 的中文摘要 prompt 保持一致（简洁指令 + 原文 + 输出锚点）。
    """
    transcript_lines = [
        f"[{_msg_role(msg)}]: {_msg_content(msg)}" for msg in messages
    ]
    transcript = "\n".join(transcript_lines)
    return f"""请将以下对话历史压缩为一份结构化摘要，作为后续对话的上下文续接。

要求：
1. 用中文输出，控制在 400 字以内；
2. 严格按以下四个小节组织，缺失的小节写"无"：
   ## 目标
   （用户想达成的总体目标）
   ## 决策
   （对话中已确定的方案与取舍）
   ## 关键事实
   （后续对话必须记住的数据、路径、名称、约束）
   ## 待办事项
   （尚未完成、需要继续跟进的事项）
3. 只输出摘要本身，不要寒暄、不要重复原文。

对话历史：
{transcript}

摘要:"""


def continuation_message(digest: str) -> str:
    """生成替换旧消息的续接内容（claw-code continuation-message 模式）。"""
    return f"{CONTINUATION_PREFIX}\n{digest.strip()}"


async def compact_messages(
    messages: Sequence[MessageLike],
    llm_chat_callable: Callable[[str], Awaitable[str]],
    keep_recent: int = DEFAULT_KEEP_RECENT,
) -> Tuple[List[MessageLike], int]:
    """压缩消息列表：摘要 旧消息 → 续接消息 + 保留最近消息。

    对数据库保持纯净：入参是消息序列，返回新消息列表，调用方负责落盘。

    Args:
        messages: 完整消息列表（按时间升序）
        llm_chat_callable: ``async (prompt) -> digest_text``，通常是
            ``LLMClient.complete`` 或测试替身
        keep_recent: 保留最近 N 条不压缩

    Returns:
        ``(new_messages, removed_count)``。``new_messages`` 的第一条是
        role=assistant 的续接摘要消息（dict），其余是原样保留的最近消息
        （保持传入的元素类型不变）。

    Raises:
        CompactionError: 没有可压缩的消息、LLM 调用失败或摘要为空。
            绝不返回半成品——失败时调用方应整体跳过。
    """
    if keep_recent < 0:
        raise CompactionError(f"keep_recent must be >= 0, got {keep_recent}")

    total = len(messages)
    if total <= keep_recent:
        raise CompactionError(
            f"nothing to compact: {total} messages <= keep_recent={keep_recent}"
        )

    to_summarize = list(messages[: total - keep_recent])
    kept = list(messages[total - keep_recent :])
    removed_count = len(to_summarize)

    prompt = build_compaction_prompt(to_summarize)
    try:
        digest = await llm_chat_callable(prompt)
    except CompactionError:
        raise
    except Exception as exc:
        raise CompactionError(f"LLM 摘要调用失败: {exc}") from exc

    if not digest or not str(digest).strip():
        raise CompactionError("LLM 返回空摘要，放弃压缩")

    summary_msg = {
        "role": "assistant",
        "content": continuation_message(str(digest)),
    }
    return [summary_msg] + kept, removed_count
