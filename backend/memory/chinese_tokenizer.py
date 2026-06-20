"""Chinese Tokenizer - 中文分词模块

使用 jieba 对中文文本进行分词，供 FTS5 全文搜索和 LIKE 搜索使用。
FTS5 默认的 unicode61 分词器对中文无效（整句作为一个 token），
jieba 分词后以空格连接，使 FTS5 能正确检索中文内容。
"""

import logging

import jieba

logger = logging.getLogger(__name__)

# 抑制 jieba 首次加载时的初始化日志
jieba.setLogLevel(logging.WARNING)


def tokenize(text: str) -> str:
    """将文本用 jieba 分词后，以空格连接供 FTS5 使用

    Args:
        text: 原始文本（中文/英文混合均可）

    Returns:
        空格连接的分词结果，如 "用户 喜欢 火锅"

    Example:
        >>> tokenize("用户喜欢火锅")
        '用户 喜欢 火锅'
        >>> tokenize("hello world")
        'hello world'
    """
    if not text or not text.strip():
        return ""
    words = jieba.cut(text)
    # 过滤空白词，保留有意义的 token
    return " ".join(w.strip() for w in words if w.strip())


def tokenize_for_search(query: str) -> str:
    """为搜索查询分词，生成 FTS5 查询字符串

    与 tokenize() 类似，但额外处理 FTS5 特殊字符，
    并将结果格式化为 FTS5 兼容的 OR 查询。

    Args:
        query: 用户输入的搜索查询

    Returns:
        FTS5 兼容的查询字符串，如 '"用户" OR "喜欢" OR "火锅"'
    """
    if not query or not query.strip():
        return '""'

    words = jieba.cut(query)
    # 过滤空白和 FTS5 特殊字符
    safe_words = []
    for word in words:
        cleaned = word.strip()
        if not cleaned:
            continue
        # 转义 FTS5 特殊字符
        cleaned = cleaned.replace('"', '""')
        safe_words.append(cleaned)

    if not safe_words:
        return '""'

    # 使用 OR 连接多个词
    return " OR ".join(f'"{w}"' for w in safe_words)
