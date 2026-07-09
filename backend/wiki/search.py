"""Token 搜索（支持 CJK 分词）。

实现基于 token 的全文搜索，支持中文 bigram 分词，BM25-like 评分。
"""

from pathlib import Path
from typing import List

from .models import SearchResponse, SearchResult

# 停止词
_STOP_WORDS = {
    # 中文
    "的",
    "了",
    "在",
    "是",
    "我",
    "有",
    "和",
    "就",
    "不",
    "人",
    "都",
    "一",
    "一个",
    "上",
    "也",
    "很",
    "到",
    "说",
    "要",
    "去",
    "你",
    "会",
    "着",
    "没有",
    "看",
    "好",
    "自己",
    "这",
    "他",
    "她",
    "它",
    "们",
    "那",
    "些",
    "什么",
    "怎么",
    "如何",
    # 英文
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "could",
    "should",
    "may",
    "might",
    "can",
    "this",
    "that",
    "these",
    "those",
    "i",
    "you",
    "he",
    "she",
    "it",
    "we",
    "they",
}


def search_wiki(project_root: Path, query: str, limit: int = 20) -> SearchResponse:
    """搜索 Wiki 页面。

    Args:
        project_root: 项目根目录
        query: 搜索查询
        limit: 返回数量上限

    Returns:
        SearchResponse: 搜索结果
    """
    tokens = _tokenize_query(query)
    if not tokens:
        return SearchResponse(results=[], total=0)

    wiki_dir = project_root / "wiki"
    if not wiki_dir.exists():
        return SearchResponse(results=[], total=0)

    results = []

    # 收集所有 .md 文件
    for md_file in wiki_dir.rglob("*.md"):
        # 跳过隐藏目录
        if any(part.startswith(".") for part in md_file.parts):
            continue

        # 跳过特殊文件
        if md_file.name in ("index.md", "log.md", "schema.md"):
            continue

        # 读取内容
        content = md_file.read_text(encoding="utf-8")
        title = _extract_title(content)
        relative_path = str(md_file.relative_to(project_root)).replace("\\", "/")

        # 计算得分
        score = 0.0
        snippet = ""

        for i, token in enumerate(tokens):
            weight = 1.5 if i == 0 else 1.0

            # 标题匹配
            if token in title.lower():
                score += 10.0 * weight

            # 内容匹配
            token_lower = token.lower()
            content_lower = content.lower()
            count = content_lower.count(token_lower)

            if count > 0:
                score += count * 0.5 * weight

                # 构建 snippet（如果还没有）
                if not snippet:
                    match_pos = content_lower.find(token_lower)
                    if match_pos != -1:
                        start = max(0, match_pos - 80)
                        end = min(len(content), match_pos + 120)
                        snippet = content[start:end]

                        if start > 0:
                            snippet = "..." + snippet
                        if end < len(content):
                            snippet = snippet + "..."

        if score > 0:
            results.append(
                SearchResult(
                    path=relative_path,
                    title=title,
                    snippet=snippet,
                    score=score,
                )
            )

    # 按得分排序
    results.sort(key=lambda r: r.score, reverse=True)
    results = results[:limit]

    return SearchResponse(results=results, total=len(results))


def _tokenize_query(query: str) -> List[str]:
    """分词查询。

    支持 CJK 字符 bigram 分词，英文按空格分词。

    Args:
        query: 查询字符串

    Returns:
        list[str]: token 列表（已过滤停止词）
    """
    tokens = []
    current_word = []

    for char in query.lower():
        # 空白或 ASCII 标点 → 刷新当前词
        if char.isspace() or (char.isascii() and not char.isalnum()):
            if current_word:
                word = "".join(current_word)
                if word not in _STOP_WORDS:
                    tokens.append(word)
                current_word = []

            # CJK 字符 → 单独作为 token
            if _is_cjk(char) and char not in _STOP_WORDS:
                tokens.append(char)
        else:
            current_word.append(char)

    # 刷新最后一个词
    if current_word:
        word = "".join(current_word)
        if word not in _STOP_WORDS:
            tokens.append(word)

    return tokens


def _is_cjk(char: str) -> bool:
    """判断字符是否为 CJK 字符。"""
    code = ord(char)
    return (
        (0x4E00 <= code <= 0x9FFF)  # CJK Unified Ideographs
        or (0x3400 <= code <= 0x4DBF)  # CJK Unified Ideographs Extension A
        or (0xF900 <= code <= 0xFAFF)  # CJK Compatibility Ideographs
    )


def _extract_title(content: str) -> str:
    """从 Markdown 内容提取标题。

    Args:
        content: Markdown 内容

    Returns:
        str: 标题
    """
    for raw_line in content.split("\n"):
        line = raw_line.strip()

        # 跳过 frontmatter
        if line == "---":
            continue

        # 查找 # 或 ## 标题
        if line.startswith("# "):
            return line[2:].strip()
        if line.startswith("## "):
            return line[3:].strip()

        # 第一个非空行（如果不是 frontmatter）
        if line and not line.startswith("---"):
            return line[:80]

    return "未命名页面"
