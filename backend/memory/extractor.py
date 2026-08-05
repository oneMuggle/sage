"""Memory Extractor - LLM 驱动的记忆事实提取

从对话中提取原子事实，类似 Mem0 的 Extractor 模块。
当 LLM 不可用时，降级为基于关键词的简单提取。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 提取提示词（借鉴 Mem0 的 fact extraction prompt）
EXTRACTION_PROMPT = """从以下对话中提取值得记住的关键事实。每个事实应该是：
- 独立的、原子化的（一个事实一句话）
- 长期有效的（不是临时的状态）
- 关于用户的偏好、习惯、身份、目标等

对话内容：
[用户]: {user_message}
[助手]: {assistant_message}

已知事实（避免重复）：
{existing_facts}

以 JSON 数组格式输出，每项包含：
- content: 事实内容（一句话，中文）
- importance: 重要性 1-10（偏好/身份类 7-9，普通事实 4-6）
- category: user_pref / project_fact / decision / task_summary / cross_session_pattern 之一
  （user_pref=用户偏好习惯；project_fact=项目/工作相关事实；decision=重要决策；
   task_summary=任务完成摘要；cross_session_pattern=跨会话模式）
- tags: 相关标签（1-3 个）

如果没有值得提取的事实，返回空数组 []。
只输出 JSON，不要其他文字。"""


class MemoryExtractor:
    """基于 LLM 的记忆事实提取器

    Example:
        >>> extractor = MemoryExtractor(llm_client)
        >>> facts = await extractor.extract(
        ...     "我喜欢吃火锅",
        ...     "好的，我记住了，你喜欢吃火锅",
        ...     existing_facts=["用户喜欢日料"]
        ... )
        >>> # 返回 [{"content": "用户喜欢吃火锅", "importance": 7, ...}]
    """

    def __init__(self, llm_client: Optional[Any] = None) -> None:
        """初始化提取器

        Args:
            llm_client: LLM 客户端（支持 chat() 方法）。
                       如果为 None，降级为关键词提取。
        """
        self._llm = llm_client

    async def extract(
        self,
        user_message: str,
        assistant_message: str,
        existing_facts: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """从对话中提取事实

        Args:
            user_message: 用户消息内容
            assistant_message: 助手回复内容
            existing_facts: 已知事实列表（用于去重）

        Returns:
            提取的事实列表，每项包含 content/importance/category/tags
        """
        # 太短的对话不值得提取
        if len(user_message) < 20 and len(assistant_message) < 50:
            return []

        if self._llm is not None:
            try:
                return await self._extract_with_llm(
                    user_message, assistant_message, existing_facts or []
                )
            except Exception as e:
                logger.warning(f"LLM 事实提取失败，降级为关键词提取: {e}")

        # 降级：关键词提取
        return self._extract_with_keywords(user_message)

    async def _extract_with_llm(
        self,
        user_message: str,
        assistant_message: str,
        existing_facts: List[str],
    ) -> List[Dict[str, Any]]:
        """使用 LLM 提取事实"""
        prompt = EXTRACTION_PROMPT.format(
            user_message=user_message[:500],
            assistant_message=assistant_message[:500],
            existing_facts="\n".join(existing_facts[:20]) if existing_facts else "（无）",
        )

        # 调用 LLM（兼容 LLMPort 和简单 chat() 接口）
        try:
            # 尝试 LLMPort 风格（Message 对象）
            from backend.domain.message import Message

            response_msg = await self._llm.chat(
                messages=[Message(role="user", content=prompt)],
            )
            content = (
                response_msg.content if hasattr(response_msg, "content") else str(response_msg)
            )
        except (ImportError, TypeError, AttributeError):
            # 降级：简单 chat() 接口
            response = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
            )
            content = response if isinstance(response, str) else response.get("content", "")

        # 解析 JSON 响应
        try:
            facts = json.loads(content)
        except json.JSONDecodeError:
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0]
                facts = json.loads(json_str)
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0]
                facts = json.loads(json_str)
            else:
                logger.warning(f"无法解析 LLM 提取结果为 JSON: {content[:100]}")
                return []

        if not isinstance(facts, list):
            return []

        # 验证和清理每个事实
        valid_facts = []
        for fact in facts:
            if isinstance(fact, dict) and "content" in fact:
                valid_facts.append(
                    {
                        "content": str(fact["content"])[:200],
                        "importance": min(max(int(fact.get("importance", 5)), 1), 10),
                        # F4 — LLM may still emit the old vocabulary
                        # (preference/fact/goal/event) or an unknown category;
                        # normalize to the new taxonomy (user_pref /
                        # project_fact / decision / task_summary /
                        # cross_session_pattern), falling back to the keyword
                        # heuristic.
                        "category": self._normalize_category(
                            str(fact.get("category", "project_fact")),
                            content=str(fact["content"]),
                        ),
                        "tags": fact.get("tags", [])[:3],
                    }
                )

        return valid_facts

    def _extract_with_keywords(self, user_message: str) -> List[Dict[str, Any]]:
        """关键词降级提取（无 LLM 时使用）"""
        facts = []

        preference_keywords = ["喜欢", "偏好", "不要", "记得", "设置", "以后", "讨厌", "爱吃"]
        for keyword in preference_keywords:
            if keyword in user_message:
                for sentence in user_message.replace("。", ".").split("."):
                    if keyword in sentence and len(sentence.strip()) > 5:
                        facts.append(
                            {
                                "content": f"用户{sentence.strip()}",
                                "importance": 7,
                                "category": self._categorize(sentence),
                                "tags": ["preference"],
                            }
                        )
                        break
                break

        return facts[:3]

    # ------------------------------------------------------------------
    # Task 4 / Gap A — memory_category heuristic
    # ------------------------------------------------------------------
    #
    # Simple keyword-based bucketing that maps a fact string to one of:
    # - ``user_pref`` — explicit user preference/habit/identity
    # - ``project_fact`` — anything else (default)
    #
    # ``task_summary`` and ``cross_session_pattern`` are reserved for
    # richer extractor stages (LLM post-processing, multi-session
    # detectors) that ship in later milestones. The heuristic here just
    # needs to never mislabel an explicit preference as project_fact.

    _USER_PREF_KEYWORDS = (
        "喜欢",
        "偏好",
        "讨厌",
        "不要",
        "记得",
        "以后",
        "设置",
        "爱吃",
        "不爱",
        "想",
        "希望",
        "需要",
    )

    # F4 — old-vocabulary → new-taxonomy mapping for LLM-extracted facts.
    _CATEGORY_MAP = {
        "preference": "user_pref",
        "fact": "project_fact",
        "goal": "cross_session_pattern",  # 长期目标跨越多个会话
        "event": "task_summary",  # 单次事件 → 任务完成摘要
    }
    _KNOWN_CATEGORIES = {
        "user_pref",
        "project_fact",
        "decision",
        "task_summary",
        "cross_session_pattern",
    }

    def _categorize(self, text: str) -> str:
        """Map a fact string to its ``memory_category``.

        Preference keywords → ``user_pref``; otherwise → ``project_fact``.
        """
        for kw in self._USER_PREF_KEYWORDS:
            if kw in text:
                return "user_pref"
        return "project_fact"

    def _normalize_category(self, category: str, content: str = "") -> str:
        """Reconcile any category string to the new taxonomy (F4).

        Known new-vocabulary categories pass through unchanged; old-vocabulary
        values (``preference``/``fact``/``goal``/``event``) are mapped; anything
        else falls back to the keyword heuristic.
        """
        mapped = self._CATEGORY_MAP.get(category, category)
        if mapped in self._KNOWN_CATEGORIES:
            return mapped
        return self._categorize(content)
