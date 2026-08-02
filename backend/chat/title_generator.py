"""Title Generator - LLM 驱动的会话标题自动生成

在第一轮对话完成后，根据用户消息和助手回复自动生成一个简洁的描述性标题。
当 LLM 不可用时，返回 None（标题保持默认的"新对话"）。
"""

from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

TITLE_PROMPT = """请根据以下对话内容，生成一个简洁的中文标题（2-10个字）。
标题应该概括对话的核心主题，不要加引号或其他装饰。

对话内容：
[用户]: {user_message}
[助手]: {assistant_message}

只输出标题文本，不要任何解释或额外内容。"""


class TitleGenerator:
    """使用 LLM 从首轮对话生成会话标题"""

    def __init__(self, llm_client) -> None:
        """
        Args:
            llm_client: LLM 客户端（支持 chat() 方法）。
                        如果为 None，generate() 直接返回 None。
        """
        self._llm = llm_client

    async def generate(
        self,
        user_message: str,
        assistant_message: str,
    ) -> Optional[str]:
        """从首轮对话生成标题

        Args:
            user_message: 用户首条消息内容
            assistant_message: 助手回复内容

        Returns:
            生成的标题字符串，LLM 失败返回 None
        """
        # 太短的对话不值得生成标题
        if len(user_message) < 5 and len(assistant_message) < 20:
            return None

        if self._llm is None:
            return None

        try:
            return await self._generate_with_llm(user_message, assistant_message)
        except Exception as e:
            logger.warning(f"LLM 标题生成失败: {e}")
            return None

    async def _generate_with_llm(
        self,
        user_message: str,
        assistant_message: str,
    ) -> Optional[str]:
        """使用 LLM 生成标题"""
        prompt = TITLE_PROMPT.format(
            user_message=user_message[:300],
            assistant_message=assistant_message[:300],
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

        return title
