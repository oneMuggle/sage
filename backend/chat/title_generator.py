"""Title Generator — LLM 驱动的会话标题自动生成

生成策略：优先调用 LLM 生成简洁标题；LLM 不可用 / 调用失败 / 输出不可用时，
降级到启发式标题（取用户首条消息首行），**永不返回 None**。

启发式兜底的意义：LLM 未配置（新装用户、端点掉线）时，会话仍能得到一个
可辨识的标题，而不是长期停留在占位标题「新对话」。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: 未命名会话的占位标题（与 sessions.title 的 NOT NULL 默认值一致）。
#: 它是「尚未生成」的哨兵值 —— 真实标题永远不会等于它（LLM 输出会被清洗，
#: 启发式兜底在两手皆空时也回落到它，表示确实无法命名）。
DEFAULT_TITLE = "新对话"

#: 启发式标题最大长度（字符）。
FALLBACK_MAX_LEN = 20

#: 触发 LLM 所需的最小内容量（用户消息 + 助手消息字符数）。
#: 低于该阈值直接走启发式，避免为「好/谢谢」这类短对话浪费一次调用。
MIN_CONTENT_FOR_LLM = 20

#: 单会话标题生成尝试次数上限（防止失败会话每轮重试）。
MAX_TITLE_ATTEMPTS = 3

TITLE_PROMPT = """请根据以下对话内容，生成一个简短、具体的会话标题。

要求：
- 长度 2-10 个字（英文标题 2-6 个单词）
- 使用对话的主要语言：中文对话用中文，英文对话用英文
- 概括对话的核心主题，不要泛泛而谈（避免"闲聊""问题"这类空泛词）
- 不要包含引号、书名号、句号等装饰性标点
- 不要输出"标题："前缀，不要解释，不要换行

对话内容：
[用户]: {user_message}
[助手]: {assistant_message}

标题："""


def fallback_title(user_message: str, assistant_message: str) -> str:
    """LLM 不可用时的启发式标题：取用户消息首行，截断到 ``FALLBACK_MAX_LEN``。

    用户消息为空或过短时退而取助手回复首行；两者都不可用时回落到
    ``DEFAULT_TITLE``（表示确实无法命名）。
    """
    for source in (user_message, assistant_message):
        text = (source or "").strip()
        if not text:
            continue
        first_line = text.splitlines()[0].strip()
        if len(first_line) < 2:
            continue
        if len(first_line) > FALLBACK_MAX_LEN:
            return first_line[:FALLBACK_MAX_LEN].rstrip() + "…"
        return first_line
    return DEFAULT_TITLE


def needs_title(session: Any) -> bool:
    """会话是否仍需生成标题（兼容 ``Session`` 对象 / ``dict``）。

    判定口径：标题仍是占位值（``None`` 或 ``DEFAULT_TITLE``）且尝试次数未达上限。
    """
    if isinstance(session, dict):
        title = session.get("title")
        attempts = session.get("title_attempts") or 0
    else:
        title = getattr(session, "title", None)
        attempts = getattr(session, "title_attempts", 0) or 0

    if title and title != DEFAULT_TITLE:
        return False
    try:
        return int(attempts) < MAX_TITLE_ATTEMPTS
    except (TypeError, ValueError):
        return True


class TitleGenerator:
    """从首轮对话生成会话标题（LLM 优先，启发式兜底）"""

    def __init__(self, llm_client) -> None:
        """
        Args:
            llm_client: LLM 客户端（支持 chat() 方法）。
                        为 None 时 generate() 直接走启发式兜底。
        """
        self._llm = llm_client

    async def generate(
        self,
        user_message: str,
        assistant_message: str,
    ) -> str:
        """生成会话标题 —— 永不返回 None。

        Args:
            user_message: 用户首条消息内容
            assistant_message: 助手回复内容

        Returns:
            生成的标题字符串。LLM 不可用或输出不可用时为启发式标题；
            两者都不可用时为 ``DEFAULT_TITLE``。
        """
        combined = f"{user_message or ''}{assistant_message or ''}".strip()
        if self._llm is None or len(combined) < MIN_CONTENT_FOR_LLM:
            return fallback_title(user_message, assistant_message)

        try:
            title = await self._generate_with_llm(user_message, assistant_message)
        except Exception as e:  # noqa: BLE001 — 任何 LLM 故障都降级
            logger.warning("LLM 标题生成失败，降级到启发式: %s", e)
            title = None

        if title:
            return title
        return fallback_title(user_message, assistant_message)

    async def _generate_with_llm(
        self,
        user_message: str,
        assistant_message: str,
    ) -> Optional[str]:
        """使用 LLM 生成标题（输出不可用时返回 None）"""
        prompt = TITLE_PROMPT.format(
            user_message=(user_message or "")[:300],
            assistant_message=(assistant_message or "")[:300],
        )

        # 调用 LLM（兼容 LLMPort 和简单 chat() 接口）
        try:
            # 尝试 LLMPort 风格（Message 对象）
            from backend.domain.message import Message

            response_msg = await self._llm.chat(
                messages=[Message(role="user", content=prompt)],
            )
            content = self._extract_content(response_msg)
        except (ImportError, TypeError, AttributeError):
            # 降级：简单 dict 接口
            response = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
            )
            content = self._extract_content(response)

        return self._clean_title(content)

    @staticmethod
    def _extract_content(response) -> str:
        """从 LLM 响应中提取文本内容（兼容多种返回格式）"""
        if isinstance(response, str):
            return response
        if isinstance(response, dict):
            return response.get("content", "")
        if hasattr(response, "content"):
            return response.content or ""
        return str(response)

    @staticmethod
    def _clean_title(raw: str) -> Optional[str]:
        """清洗 LLM 返回的标题文本"""
        if not raw:
            return None

        # 取第一行
        title = raw.strip().split("\n")[0].strip()

        # 去除常见前缀如 "title:" "标题:" 等
        title = re.sub(r"^(title|标题|Title)\s*[:：]\s*", "", title, flags=re.IGNORECASE)

        # 去除首尾引号（中英文）
        title = title.strip("\"'「」『』""")

        # 去除首尾空白
        title = title.strip()

        # 太短或太长都不合适
        if len(title) < 2 or len(title) > 30:
            return None

        # 占位标题不视为有效生成结果（会触发下一轮重试）
        if title == DEFAULT_TITLE:
            return None

        return title
