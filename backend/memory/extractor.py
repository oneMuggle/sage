"""Memory Extractor - LLM 驱动的记忆事实提取

从对话中提取原子事实，类似 Mem0 的 Extractor 模块。
当 LLM 不可用时，降级为基于关键词的简单提取。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 提取门槛 —— 高价值信号关键词
# ---------------------------------------------------------------------------
#
# 短消息默认会被跳过（避免纯寒暄被当成事实抽取）；但如果命中任一关键词，
# 即便很短也会放行，因为这类信息即使短也值得长期记忆（用户身份、强烈偏好、
# 重要决策）。关键词按「类别 → 具体表达」组织，便于后续扩展。
#
# 注意：这里只用子串匹配（不用正则），性能更好，且对中文 LLM 输出足够
# 鲁棒——正则里 ``\b`` 边界对中文分词不稳定，反而容易漏。
HIGH_VALUE_KEYWORDS: tuple = (
    # 用户身份（"我是后端工程师，专做 Python"）
    "我是专家",
    "我是工程师",
    "我是开发者",
    "我是研究员",
    "我是设计师",
    "我是产品经理",
    "我是架构师",
    # 强烈偏好 / 禁令（"永远不要用 class"）
    "永远不",
    "不要用",
    "不要再",
    "绝不做",
    "禁止使用",
    # 重要决策（"我们决定用 TypeScript"）
    "我们决定",
    "我们选择",
    "我们采用",
    "我们改用",
    # 显式偏好（"我偏好函数式"）
    "我喜欢",
    "我偏好",
    "我习惯",
)

# 已知事实注入 prompt 的字符预算——控制 LLM 输入成本，同时保证
# 最相关的事实一定进 prompt（按输入顺序，越靠前越相关）。
EXISTING_FACTS_CHAR_BUDGET = 1200

# 判定"已知事实与本轮相关"所需的最小 token 交集数
_MIN_TOKEN_OVERLAP = 1


def _token_set(text: str) -> set:
    """jieba 分词后的 token 集合（去空白、去单字符噪声）。"""
    from backend.memory.chinese_tokenizer import tokenize

    tokens = tokenize(text).split()
    return {t for t in tokens if len(t) > 1}


def _select_existing_facts(
    query: str,
    facts: List[str],
    budget: int = EXISTING_FACTS_CHAR_BUDGET,
) -> List[str]:
    """按相关性 + 字符预算挑选要注入 prompt 的已知事实。

    原来只是 ``existing_facts[:20]`` —— 前 20 条既可能与本轮无关，
    又可能因为单条很长而把 prompt 撑爆。这里改成两步：

    1. 相关性过滤：与本轮对话无 token 交集的事实直接丢弃
       （FTS5 的 OR 匹配会捞回大量仅有一个泛化词命中的弱相关行）
    2. 字符预算：按输入顺序（调用方已按相关性降序）累加，超预算即停；
       单条超长时截断并加省略号，保证预算不被突破

    Args:
        query: 本轮对话文本（用户消息 + 助手消息），用于相关性判定
        facts: 已知事实列表，越靠前越相关
        budget: 注入 prompt 的字符预算

    Returns:
        选中的已知事实文本列表
    """
    if not facts:
        return []

    query_tokens = _token_set(query or "")
    selected: List[str] = []
    used = 0

    for raw in facts:
        text = (raw or "").strip()
        if not text:
            continue
        if query_tokens:
            fact_tokens = _token_set(text)
            overlap = len(query_tokens & fact_tokens)
            if overlap < _MIN_TOKEN_OVERLAP:
                continue
        remaining = budget - used
        if remaining <= 0:
            break
        if len(text) > remaining:
            # 预留 1 字符给省略号，保证单条也不突破预算
            text = text[: max(remaining - 1, 0)].rstrip() + "…"
        if not text:
            break
        selected.append(text)
        used += len(text) + 1

    return selected

# 提取提示词（借鉴 Mem0 的 fact extraction prompt）
# 注意：category 只允许 preference/goal/environment，与
# extract_and_store_memory() 的 profile_categories 路由白名单完全对齐。
# 若允许 fact/event 等类别，会被路由到 episodic memory 而非用户画像库，
# 导致画像长期为空（review 2026-10 发现此问题）。
EXTRACTION_PROMPT = """从以下对话中提取值得记住的关键事实。每个事实应该是：
- 独立的、原子化的（一个事实一句话）
- 长期有效的（不是临时的状态）
- 关于用户的偏好、习惯、身份、目标等
- 或关于本机运行环境的长期事实（category=environment）：如操作系统/PowerShell
  版本限制及可用替代写法、python/node 的实际路径与版本、环境类报错的
  已验证解决方案。这类事实 importance 给 8-10，tags 含 "environment"

工具执行观察（本轮工具返回的环境事实，如 shell 降级提示；可作为
environment 类事实的直接来源）：
{tool_observations}

对话内容：
[用户]: {user_message}
[助手]: {assistant_message}

已知事实（避免重复）：
{existing_facts}

以 JSON 数组格式输出，每项包含：
- content: 事实内容（一句话，中文）
- importance: 重要性 1-10（环境/版本类 8-10，偏好/身份类 7-9，普通事实 4-6）
- category: **只允许以下三种**：
  - preference：用户偏好、沟通风格、工作习惯、身份特征
  - goal：用户当前目标、计划、关注方向
  - environment：本机运行环境的长期事实（工具链/版本/路径/限制）
- tags: 相关标签（1-3 个）

**重要**：不要把 category 写成 fact 或 event，这两类无法被记忆系统正确处理。
所有关于用户的事实都应归入 preference 或 goal；环境事实归入 environment。

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
        tool_observations: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """从对话中提取事实

        Args:
            user_message: 用户消息内容
            assistant_message: 助手回复内容
            existing_facts: 已知事实列表（用于去重）
            tool_observations: 本轮工具执行观察到的环境事实文本（可选，
                如 shell 降级提示），参与 environment 类事实的提取

        Returns:
            提取的事实列表，每项包含 content/importance/category/tags
        """
        # 双向门槛：短消息默认跳过（避免纯寒暄被当成事实），但命中
        # HIGH_VALUE_KEYWORDS 时仍放行（"我喜欢 ruff"、"我们决定用 TS" 等）
        if not self._should_extract(user_message, assistant_message):
            return []

        if self._llm is not None:
            try:
                return await self._extract_with_llm(
                    user_message,
                    assistant_message,
                    existing_facts or [],
                    tool_observations or "",
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
        tool_observations: str = "",
    ) -> List[Dict[str, Any]]:
        """使用 LLM 提取事实"""
        selected_facts = _select_existing_facts(
            f"{user_message} {assistant_message}", existing_facts
        )
        prompt = EXTRACTION_PROMPT.format(
            user_message=user_message[:500],
            assistant_message=assistant_message[:500],
            existing_facts="\n".join(selected_facts) if selected_facts else "（无）",
            tool_observations=tool_observations[:500].strip() or "（无）",
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
                        "category": fact.get("category", "fact"),
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
                                "category": "preference",
                                "tags": ["preference"],
                            }
                        )
                        break
                break

        return facts[:3]

    # ------------------------------------------------------------------
    # 提取门槛 —— 双向 gate
    # ------------------------------------------------------------------
    #
    # 之前只看长度（太短就跳），结果是两类漏网：
    #   1) 长度刚过阈值的纯寒暄（"好的谢谢"、"收到"）仍被送入提取器，
    #      白白浪费 LLM token / 关键词匹配循环；
    #   2) 很短但含高价值信号的消息（"我喜欢 ruff"）会被原 20/50 阈值
    #      放过（恰好用户 15 字、助手 60 字），其实值得保留——这本身
    #      不是漏网，但如果我们上调阈值就会误伤。
    #
    # 双向 gate 同时解决：默认按阈值跳过，但 HIGH_VALUE_KEYWORDS 命中
    # 时强制放行。
    _USER_MSG_THRESHOLD = 30
    _ASSISTANT_MSG_THRESHOLD = 80

    def _should_extract(self, user_message: str, assistant_message: str) -> bool:
        """双向提取门槛：短消息默认跳过，高价值信号命中时放行。"""
        if self._has_high_value_signal(user_message, assistant_message):
            return True
        return not (
            len(user_message) < self._USER_MSG_THRESHOLD
            and len(assistant_message) < self._ASSISTANT_MSG_THRESHOLD
        )

    @staticmethod
    def _has_high_value_signal(user_message: str, assistant_message: str) -> bool:
        """任一消息命中 HIGH_VALUE_KEYWORDS 即返回 True。"""
        combined = f"{user_message or ''} {assistant_message or ''}"
        if not combined.strip():
            return False
        return any(kw in combined for kw in HIGH_VALUE_KEYWORDS)
