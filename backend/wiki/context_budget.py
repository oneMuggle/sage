"""Token 预算分配。

实现上下文窗口的 token 预算分配，确保不超出模型限制。
"""

import math
from dataclasses import dataclass

# 常量
PAGES_RATIO = 0.50  # 50% 用于检索页面
HISTORY_RATIO = 0.30  # 30% 用于聊天历史 + 系统
INDEX_RATIO = 0.05  # 5% 用于 index
RESERVE_RATIO = 0.15  # 15% 预留给 LLM 输出
PER_PAGE_DIVISOR = 8  # 单页硬限制 = total / 8
CHARS_PER_TOKEN = 3  # 粗略估计: UTF-8 字符数 / 3
DEFAULT_MAX_TOKENS = 8192  # 默认模型最大 token


@dataclass
class ContextBudget:
    """上下文预算。"""

    total: int
    pages: int
    history: int
    index: int
    response_reserve: int
    per_page_cap: int

    @classmethod
    def compute(cls, model_max_tokens: int = DEFAULT_MAX_TOKENS) -> "ContextBudget":
        """计算上下文预算。

        Args:
            model_max_tokens: 模型最大 token 数

        Returns:
            ContextBudget: 预算分配
        """
        total = min(model_max_tokens, DEFAULT_MAX_TOKENS) * 7 // 10  # 70% of capped max
        pages = int(total * PAGES_RATIO)
        history = int(total * HISTORY_RATIO)
        index = int(total * INDEX_RATIO)
        response_reserve = int(total * RESERVE_RATIO)
        per_page_cap = total // PER_PAGE_DIVISOR

        return cls(
            total=total,
            pages=pages,
            history=history,
            index=index,
            response_reserve=response_reserve,
            per_page_cap=per_page_cap,
        )


def estimate_tokens(text: str) -> int:
    """估算文本的 token 数。

    Args:
        text: 文本

    Returns:
        int: 估算的 token 数
    """
    return math.ceil(len(text) / CHARS_PER_TOKEN)


@dataclass
class PageChunk:
    """页面分块。"""

    page_path: str
    content: str
    truncated: bool


def truncate_pages(pages: list[tuple[str, str]], budget: ContextBudget) -> list[PageChunk]:
    """截断页面以适应预算。

    Args:
        pages: 页面列表 [(path, content), ...]
        budget: 上下文预算

    Returns:
        list[PageChunk]: 截断后的页面分块
    """
    chunks = []
    remaining = budget.pages

    for path, original_content in pages:
        if remaining <= 0:
            break

        full_tokens = estimate_tokens(original_content)
        allowed = min(full_tokens, budget.per_page_cap, remaining)
        max_chars = allowed * CHARS_PER_TOKEN

        # 截断内容
        if len(original_content) > max_chars:
            content = original_content[:max_chars]
            truncated = True
        else:
            content = original_content
            truncated = False

        chunks.append(PageChunk(page_path=path, content=content, truncated=truncated))
        remaining -= allowed

    return chunks
