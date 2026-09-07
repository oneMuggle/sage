# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""会话历史 → LLM 请求消息（对标增强第二轮 L1，docs/plans/2026-09-06-parity-round2）。

此前 legacy ``/chat/stream`` producer 每次只组装 ``[system, attachments?, user]``
交给 ``run_loop``，持久化历史完全不进 LLM 请求 —— 用户第二条消息起 agent
"失忆"，自动压缩只惠及存储/UI，不省每轮 token（legacy_routes._maybe_auto_compact_session
的"已知限制"注释）。本模块补上缺失的一环：

- ``db_rows_to_history``: 把 MessageRepository 的行转成 OpenAI 兼容请求消息
  （仅 user/assistant，剥离 reasoning_content / 空 / tool 行）；
- ``truncate_history``: 按 token 预算从最旧开始丢，保序保最近；
- ``build_request_messages``: producer 一次性组装
  ``[system(+省略说明), attachments?, *history, user]``。

对数据库保持纯净：所有函数只接收行对象 / dict，不触碰 SQLite；LLM 调用
为零（历史复用已落盘内容，不二次摘要）——压缩仍由 M4 自动压缩负责。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend.chat.compaction import estimate_messages_tokens

logger = logging.getLogger(__name__)

#: 进入请求的历史角色白名单 —— legacy 流式路径只落盘 user / assistant /
#: 压缩续接（assistant）三类行；tool 行与带 tool_calls 的 assistant 行
#: （裸 ReAct 中间态，不入库）防御性跳过。
_HISTORY_ROLES = ("user", "assistant")

#: 历史 token 预算默认值的下限 —— 即使压缩阈值被调小，历史也不会被砍到
#: 无法承载基本多轮对话（约等于 compact 默认阈值的 3 倍）。
_MIN_HISTORY_TOKEN_BUDGET = 18000

#: 历史 token 预算 = max(compact 阈值 × 倍数, 下限)；env ``SAGE_HISTORY_TOKEN_BUDGET``
#: 显式覆盖（合法正整数才生效，fail-safe）。
_HISTORY_BUDGET_MULTIPLIER = 3
_ENV_HISTORY_BUDGET = "SAGE_HISTORY_TOKEN_BUDGET"

#: 截断发生时注入 system prompt 的说明（透明原则：让模型知道开头不完整）
_TRUNCATION_NOTICE = (
    "\n\n[上下文说明] 本次请求为符合长度限制省略了最早的 {omitted} 条历史消息，"
    "只保留最近的对话。若需要更早的细节，请询问用户或使用 memory_search 工具。"
)


def history_token_budget() -> int:
    """读取历史 token 预算：env > max(compact 阈值 × 3, 18000)。

    任何一层解析失败都静默降级到下一层，本函数永不抛错。
    """
    env_raw = os.environ.get(_ENV_HISTORY_BUDGET)
    if env_raw:
        try:
            value = int(env_raw.strip())
            if value > 0:
                return value
        except ValueError:
            logger.warning(
                "env %s=%r 不是合法正整数，回退默认预算", _ENV_HISTORY_BUDGET, env_raw
            )
    try:
        from backend.chat.compaction import get_compact_threshold

        return max(get_compact_threshold() * _HISTORY_BUDGET_MULTIPLIER, _MIN_HISTORY_TOKEN_BUDGET)
    except Exception:  # noqa: BLE001 — 阈值读取失败时用硬下限
        return _MIN_HISTORY_TOKEN_BUDGET


def db_rows_to_history(rows: Sequence[Any]) -> List[Dict[str, str]]:
    """把 MessageRepository 行（DbMessage）转成请求用 ``{"role", "content"}`` 列表。

    规则：
    - 只保留 ``user`` / ``assistant`` 行（tool 行 / 未知角色跳过）；
    - 带非空 ``tool_calls`` 的 assistant 行跳过 —— 那是裸 agent.chat() 路径
      可能留下的中间态，重放进请求缺 tool 结果配对会被 API 拒绝；
    - ``reasoning_content`` 一律剥离（多数 OpenAI 兼容上游不接受该入参，
      DeepSeek reasoner 会直接报错）；
    - 空 / 纯空白 content 跳过。
    """
    history: List[Dict[str, str]] = []
    for row in rows:
        role = (getattr(row, "role", None) or "").strip()
        if role not in _HISTORY_ROLES:
            continue
        if getattr(row, "tool_calls", None):
            continue
        content = getattr(row, "content", None)
        if content is None or not str(content).strip():
            continue
        history.append({"role": role, "content": str(content)})
    return history


def truncate_history(
    messages: Sequence[Dict[str, str]],
    budget_tokens: Optional[int] = None,
) -> Tuple[List[Dict[str, str]], int]:
    """按 token 预算截断历史：保留最近、丢弃最旧。

    从最新一条向前累积估算 token，超出预算即停；前面的整段丢弃。
    历史里没有 tool 往返行（见 ``db_rows_to_history``），任意消息边界都是
    安全切点，无需配对修补。

    Returns:
        ``(kept, omitted_count)``；全部放得下时 ``omitted_count == 0``。
    """
    if budget_tokens is None:
        budget_tokens = history_token_budget()
    if budget_tokens <= 0 or not messages:
        return list(messages), 0

    kept_reversed: List[Dict[str, str]] = []
    used = 0
    for msg in reversed(messages):
        cost = estimate_messages_tokens([msg])
        if kept_reversed and used + cost > budget_tokens:
            break
        kept_reversed.append(msg)
        used += cost
    kept_reversed.reverse()
    omitted = len(messages) - len(kept_reversed)
    return kept_reversed, omitted


def build_request_messages(
    system_content: str,
    user_text: str,
    history_rows: Sequence[Any],
    attachment_block: Optional[str] = None,
    budget_tokens: Optional[int] = None,
    trailing_system: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """组装 producer 的完整请求消息（L1 主入口，纯函数）。

    顺序：``[system(+省略说明), attachments?, *history, trailing_system?, user]``。
    附件块属于本轮请求的即时上下文，放在历史之后、当前消息之前（与既有实现一致）。

    L4' (round4 批次 C) prompt 前缀稳定化：环境上下文 / 记忆等**每轮都会
    变化**的内容经 ``trailing_system`` 传入，作为独立 system 消息插在历史
    之后、末条 user 之前——OpenAI 系 / DeepSeek 的前缀缓存按逐字节前缀
    命中，头部 system + 追加式历史保持跨请求稳定即可吃到缓存；易变块若
    混进头部 system，任何 git 状态/时间变化都会让整轮缓存失效。

    Returns:
        ``(messages, omitted_count)``。任何失败都不抛错 —— 历史注入是
        best-effort 增强，绝不能阻断聊天。
    """
    kept, omitted = truncate_history(db_rows_to_history(history_rows), budget_tokens)

    messages: List[Dict[str, Any]] = []
    system_text = system_content
    if omitted > 0:
        system_text += _TRUNCATION_NOTICE.format(omitted=omitted)
    messages.append({"role": "system", "content": system_text})
    if attachment_block:
        messages.append(
            {
                "role": "system",
                "content": (
                    "The user has referenced the following attached documents. "
                    "Treat them as primary context for the user's request.\n\n"
                    f"{attachment_block}"
                ),
            }
        )
    messages.extend(kept)
    if trailing_system and str(trailing_system).strip():
        messages.append({"role": "system", "content": str(trailing_system)})
    messages.append({"role": "user", "content": user_text})
    return messages, omitted


__all__ = [
    "build_request_messages",
    "db_rows_to_history",
    "history_token_budget",
    "truncate_history",
]
