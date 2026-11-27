"""会话摘录 —— LLM 提示词的公共输入（P2 抽出）。

``todo_ai``（对话→待办）与 ``worklog_ai``（对话→工作日志）都要把一段会话压成
**有限长度**的纯文本喂给模型：消息条数上限、单条长度上限、总字符预算、以及
「只取 user/assistant 两条角色」的过滤规则 —— 四处完全一致。抽到这里避免两边
漂移（预算一旦不一致，抽取质量与耗时就会跟着漂）。

抽取出来的文本形态::

    [用户] 今天把登录接口调通了

    [助手] 好的，还需要补单测吗？

**不在这里做 LLM 调用** —— 只负责「把会话变成文本」。
"""
from __future__ import annotations

from typing import Any, List, Optional

#: 单次抽取最多取多少条消息。
MAX_MESSAGES = 80

#: 单条消息最多取多少字符（超出截断）。
MAX_MESSAGE_CHARS = 2000

#: 整段摘录的总字符预算。
TOTAL_BUDGET_CHARS = 12000

#: 参与摘录的角色白名单 —— system / tool 消息不喂给抽取模型。
_EXTRACT_ROLES = ("user", "assistant")


def load_conversation_excerpt(
    session_id: str,
    message_ids: Optional[List[str]] = None,
) -> str:
    """把会话消息压成 ``[用户]/[助手]`` 摘录文本（有预算上限）。

    ``message_ids`` 给了就按给定顺序取（对话窗口内选中的消息），否则取该会话
    最近 ``MAX_MESSAGES`` 条并反转为时间正序。
    """
    from backend.data.session_repo import MessageRepository

    repo = MessageRepository()
    messages: List[Any] = []
    if message_ids:
        for message_id in message_ids[:MAX_MESSAGES]:
            message = repo.get(message_id)
            if message is not None:
                messages.append(message)
    else:
        messages = list(reversed(repo.get_by_session(session_id, limit=MAX_MESSAGES)))

    lines: List[str] = []
    budget = TOTAL_BUDGET_CHARS
    for message in messages:
        role = getattr(message, "role", "") or ""
        if role not in _EXTRACT_ROLES:
            continue
        content = (getattr(message, "content", "") or "").strip()
        if not content or budget <= 0:
            continue
        take = content[: min(MAX_MESSAGE_CHARS, budget)]
        budget -= len(take)
        label = "用户" if role == "user" else "助手"
        lines.append(f"[{label}] {take}")
    return "\n\n".join(lines)
