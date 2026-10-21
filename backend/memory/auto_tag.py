"""自动标签派生 - 为无标签记忆从内容推导标签。

背景
----
实测 ``memories_episodic`` 表 84% 的行 ``tags=[]``（37 行中 31 行），
且绝大多数标签在整份语料里只出现一次——``TagCooccurrenceGraph`` 的共现矩阵
几乎没有边，Phase 2 接入的第三路召回（tag_graph 扩展）形同虚设。

根因
----
标签只有两个来源，且都可能为空：

1. LLM 提取器（``extractor._extract_with_llm``）——LLM 常返回 ``"tags": []``
2. 关键词降级提取（``extractor._extract_with_keywords``）——只产 ``["preference"]``

其余写入路径（``memory_tool`` / ``legacy_memory_routes`` / ``adapter.store``）
都允许 tags 为空，空标签一路写进 DB。

策略
----
无显式标签时，从内容本地派生（jieba 分词 + 停用词过滤 + 词频/长度加权），
不调用 LLM。

与 query 侧 ``adapter._extract_query_tags`` 共用同一套停用词与过滤规则——
「存储派生的标签」与「查询抽取的标签」必须落在同一词表上，否则图谱两端
对不上，共现边永远建不起来。
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from typing import Any, Dict, List

import jieba

logger = logging.getLogger(__name__)

# 抑制 jieba 首次加载时的初始化日志
jieba.setLogLevel(logging.WARNING)

# 通用停用词 + 领域泛化词。
# query 抽取（adapter._extract_query_tags）与存储派生（derive_tags）共用，
# 保证两端词表一致——否则图谱的 tag_memory_index 键与查询标签对不上。
TAG_STOPWORDS = frozenset({
    # 中文虚词
    "的", "了", "是", "在", "和", "与", "或", "也", "都", "就",
    "不", "有", "这", "那", "我", "你", "他", "她", "它", "们",
    "到", "从", "把", "被", "让", "给", "向", "对", "关于",
    "一个", "这个", "那个", "什么", "怎么", "如何", "为什么",
    "以及", "并且", "但是", "而且", "所以", "因为", "如果",
    # 泛化名词/动词——无主题区分度，进图谱只贡献噪声边
    "用户", "内容", "信息", "数据", "情况", "问题", "时候",
    "使用", "管理", "处理", "进行", "相关", "一些", "这些",
    "那些", "需要", "可以", "应该", "开始", "完成", "提供",
    "记忆", "助手", "系统", "方式", "工作", "东西", "地方",
    "第一", "每次", "全部", "其他", "更多", "很多", "现在",
    # 英文虚词/代词
    "for", "and", "the", "with", "that", "this", "from", "into",
    "when", "what", "how", "are", "was", "were", "has", "have",
    "had", "not", "but", "you", "your", "all", "any", "can",
    "will", "would", "should", "could", "its", "our", "their",
    "been", "they", "them", "his", "her", "him", "she",
})

# 纯标点/符号 token（jieba 会把标点单独切出来）
_PUNCT_RE = re.compile(r"^[\W_]+$", re.UNICODE)

# 标签长度下限：单字中文噪声太大（"车"/"水"），不入标签
_MIN_TAG_LEN = 2


def is_valid_tag(token: str) -> bool:
    """判断 token 是否可作为标签。

    存储侧派生（``derive_tags``）与查询侧抽取
    （``adapter._extract_query_tags``）共用此判定，保证两端词表一致。
    """
    if len(token) < _MIN_TAG_LEN:
        return False
    if token in TAG_STOPWORDS:
        return False
    if token.isdigit():
        return False
    if _PUNCT_RE.match(token):
        return False
    return True


def filter_valid_tags(tokens: List[str]) -> List[str]:
    """按标签规则过滤 token 列表（保留原顺序，不去重）。

    Args:
        tokens: 原始 token 列表

    Returns:
        通过标签校验的 token 列表
    """
    return [t for t in tokens if is_valid_tag(t)]


def normalize_tags(raw: Any) -> List[str]:
    """把任意形态的 tags 值规整为干净的字符串列表。

    兼容三种来源：已是 list、JSON 字符串、None/缺失。字符串元素会被
    去除首尾空白并丢弃空串与重复项。

    Args:
        raw: 原始 tags 值（list / JSON 字符串 / None / 其他）

    Returns:
        规整后的标签列表（可能为空）
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(raw, (list, tuple, set)):  # noqa: UP038 - Py3.8 win7 LTS requires tuple form
        return []

    result: List[str] = []
    seen = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        token = item.strip()
        if not token or token in seen:
            continue
        seen.add(token)
        result.append(token)
    return result


def score_tags(tokens: List[str]) -> List[str]:
    """对候选 token 按「频次 × 长度权重」排序。

    权重公式 ``freq × (1 + 0.3 × (词长 - 2))``：高频词优先，同频时长词优先
    （长词主题区分度更高）。同分按首次出现位置排序，保证结果确定性。

    Args:
        tokens: 候选 token 列表（已通过 ``is_valid_tag`` 校验）

    Returns:
        排序后的 token 列表（去重）
    """
    if not tokens:
        return []

    counter = Counter(tokens)
    first_pos: Dict[str, int] = {}
    for idx, token in enumerate(tokens):
        if token not in first_pos:
            first_pos[token] = idx

    scored = []
    for token, freq in counter.items():
        score = freq * (1.0 + 0.3 * (len(token) - 2))
        scored.append((-score, first_pos[token], token))
    scored.sort()

    return [token for _, _, token in scored]


def extract_tags(text: str, max_tags: int = 5) -> List[str]:
    """从自由文本提取标签 —— 存储派生与查询抽取的唯一实现。

    策略：jieba 分词 → 过滤（长度 / 停用词 / 纯数字 / 纯标点）→
    按「频次 × 长度权重」排序 → 取 top N。

    存储侧（``derive_tags``）与查询侧（``adapter._extract_query_tags``）必须
    共用本函数：同一段文本在两侧得到同一个标签集合（查询侧 max_tags 更大，
    故查询标签 ⊇ 存储标签），图谱的「标签 → 记忆」和「查询 → 标签」两端
    才能对齐，共现边才建得起来。

    Args:
        text: 自由文本（中文 / 英文混合）
        max_tags: 最多返回的标签数

    Returns:
        标签列表（无有效词时为空）
    """
    if not text or not text.strip() or max_tags <= 0:
        return []

    candidates = [t.strip() for t in jieba.cut(text)]
    candidates = filter_valid_tags(candidates)
    return score_tags(candidates)[:max_tags]


def derive_tags(content: str, max_tags: int = 3) -> List[str]:
    """从记忆内容派生标签（存储侧）。

    见 ``extract_tags``：共用同一实现，此处仅把默认上限收紧为 3
    （记忆携带过多标签会让共现矩阵噪声上升）。

    Args:
        content: 记忆内容
        max_tags: 最多返回的标签数

    Returns:
        标签列表（内容无有效词时为空）

    Example:
        >>> derive_tags("用户喜欢 Python 编程")
        ['Python', '编程']
    """
    return extract_tags(content, max_tags)
