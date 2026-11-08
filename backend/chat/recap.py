# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""
会话进度总结（Recap）

对标 Claude Code 的 /recap 命令，提供结构化的对话进度总结：
- progress: 当前进度总结
- decisions: 关键决策列表
- nextSteps: 建议的下一步
- openQuestions: 未解决问题（如有）

与 compaction.py 的区别：
- compaction 面向机器（压缩上下文续接），本模块面向人类（可理解性）
- compaction 自动触发，本模块由用户手动触发
- 共享 LLM 调用模式，但 prompt 和输出格式不同
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, List, Optional, Sequence

logger = logging.getLogger(__name__)


@dataclass
class RecapResult:
    """结构化的 recap 结果。"""

    progress: str = ""
    decisions: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "progress": self.progress,
            "decisions": self.decisions,
            "nextSteps": self.next_steps,
            "openQuestions": self.open_questions,
        }


class RecapError(RuntimeError):
    """Recap 生成失败（LLM 调用失败 / 消息不足等）。"""


class RecapTooShortError(RecapError):
    """会话消息数不足，无法生成有意义的 recap。"""


# ---- 常量 -----------------------------------------------------------------

#: 消息数地板：少于此数量的会话不生成 recap（短对话 recap 无意义）
MIN_RECAP_MESSAGE_COUNT = 3

#: 用于 recap 的最近消息条数
DEFAULT_RECAP_MESSAGE_LIMIT = 20


# ---- 辅助函数 ---------------------------------------------------------------


def _msg_role(message: Any) -> str:
    """统一读取 dict / Message 对象的 role 字段。"""
    if isinstance(message, dict):
        return str(message.get("role") or "unknown")
    return str(getattr(message, "role", None) or "unknown")


def _msg_content(message: Any) -> str:
    """统一读取 dict / Message 对象的 content 字段。"""
    if isinstance(message, dict):
        return str(message.get("content") or "")
    return str(getattr(message, "content", None) or "")


def _parse_recap_output(text: str) -> RecapResult:
    """解析 LLM 输出的 recap 文本为结构化结果。

    支持两种格式：
    1. JSON 格式（首选）
    2. Markdown 格式（降级解析）
    """
    text = text.strip()

    # 尝试 JSON 解析
    if text.startswith("{"):
        try:
            data = json.loads(text)
            return RecapResult(
                progress=str(data.get("progress", "")),
                decisions=list(data.get("decisions", [])),
                next_steps=list(data.get("nextSteps", data.get("next_steps", []))),
                open_questions=list(data.get("openQuestions", data.get("open_questions", []))),
            )
        except json.JSONDecodeError:
            pass

    # 降级：Markdown 格式解析
    result = RecapResult()

    # 提取进度总结（第一行或 "## 进度" 后的内容）
    progress_match = re.search(r"(?:^|\n)\s*(?:##?\s*进度[：:]?\s*|Progress[：:]?\s*)(.+?)(?:\n|$)", text, re.IGNORECASE)
    if progress_match:
        result.progress = progress_match.group(1).strip()
    elif text:
        # 取第一行作为进度
        first_line = text.split("\n")[0].strip()
        if first_line and not first_line.startswith("#"):
            result.progress = first_line[:100]

    # 提取列表项（以 - 或 * 或数字开头的行）
    lines = text.split("\n")
    current_section = None

    for line in lines:
        line_stripped = line.strip()

        # 检测 section
        if re.match(r"^##?\s*(决策|决定|decisions?)", line_stripped, re.IGNORECASE):
            current_section = "decisions"
            continue
        if re.match(r"^##?\s*(下一步|next\s*steps?|建议)", line_stripped, re.IGNORECASE):
            current_section = "next_steps"
            continue
        if re.match(r"^##?\s*(问题|待解决|open\s*questions?)", line_stripped, re.IGNORECASE):
            current_section = "open_questions"
            continue

        # 提取列表项
        if line_stripped and current_section:
            item_match = re.match(r"^(?:[-*•]|\d+[.)])\s*(.+)", line_stripped)
            if item_match:
                item = item_match.group(1).strip()
                if item:
                    if current_section == "decisions":
                        result.decisions.append(item)
                    elif current_section == "next_steps":
                        result.next_steps.append(item)
                    elif current_section == "open_questions":
                        result.open_questions.append(item)

    return result


def build_recap_prompt(messages: Sequence[Any]) -> str:
    """构造让 LLM 生成结构化 recap 的 prompt。

    输出格式要求：
    - progress: 一句话总结当前进度（20字以内）
    - decisions: 关键决策列表（最多3条）
    - nextSteps: 建议的下一步（最多3条）
    - openQuestions: 未解决问题（如有）
    """
    transcript_lines = [
        f"[{_msg_role(msg)}]: {_msg_content(msg)}" for msg in messages
    ]
    transcript = "\n".join(transcript_lines)

    return f"""请根据以下对话历史生成一份简洁的进度总结。

要求：
1. 用 JSON 格式输出，包含以下字段：
   - progress: 一句话总结当前进度（20字以内，中文）
   - decisions: 本次对话中做出的关键决策列表（最多3条，每条不超过30字）
   - nextSteps: 建议的下一步行动列表（最多3条，每条不超过30字）
   - openQuestions: 尚未解决的问题列表（如有，最多3条）

2. 保持简洁、可操作
3. 使用用户的语言（中文/英文与对话一致）
4. 只输出 JSON，不要额外文字

输出格式示例：
{{
  "progress": "完成了用户认证模块",
  "decisions": ["使用 JWT 而非 Session", "选择 Redis 做缓存"],
  "nextSteps": ["编写单元测试", "部署到测试环境"],
  "openQuestions": ["是否需要支持 OAuth?"]
}}

对话历史：
{transcript}

请输出 JSON:"""


async def generate_recap(
    session_id: str,
    llm_callable: Callable[[str], Awaitable[str]],
    message_fetcher: Optional[Callable[[str, int], Awaitable[List[Any]]]] = None,
    limit: int = DEFAULT_RECAP_MESSAGE_LIMIT,
) -> RecapResult:
    """生成会话 recap。

    Args:
        session_id: 会话 ID
        llm_callable: LLM 调用函数 (prompt) -> str
        message_fetcher: 消息获取函数 (session_id, limit) -> List[Message]
            默认为 None 时使用 MessageRepository.get_recent_messages
        limit: 获取的最近消息条数

    Returns:
        RecapResult 结构化结果

    Raises:
        RecapError: 消息不足 / LLM 调用失败 / 解析失败
    """
    # 获取消息
    if message_fetcher is not None:
        messages = await message_fetcher(session_id, limit)
    else:
        from backend.data.session_repo import MessageRepository
        messages = MessageRepository().get_recent_messages(session_id, limit)

    if len(messages) < MIN_RECAP_MESSAGE_COUNT:
        raise RecapTooShortError(
            f"对话太短（{len(messages)} 条消息），至少需要 {MIN_RECAP_MESSAGE_COUNT} 条才能生成总结"
        )

    # 构建 prompt 并调用 LLM
    prompt = build_recap_prompt(messages)
    try:
        llm_output = await llm_callable(prompt)
    except Exception as exc:
        raise RecapError(f"LLM 调用失败: {exc}") from exc

    if not llm_output or not str(llm_output).strip():
        raise RecapError("LLM 返回空结果")

    # 解析输出
    try:
        result = _parse_recap_output(str(llm_output))
    except Exception as exc:
        raise RecapError(f"解析 LLM 输出失败: {exc}") from exc

    # 验证至少有 progress
    if not result.progress:
        raise RecapError("LLM 未生成有效的进度总结")

    return result
