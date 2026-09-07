"""Markdown → WordParagraphSpec 列表解析器。

支持：
- # / ## / ### 标题
- - / * bullet 列表
- 1. / 2. / ... 编号列表
- 普通段落
- emoji 原样保留

不处理：**bold** / *italic* / [link]() / 嵌套列表（YAGNI，后续按需扩展）。
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$")
_BULLET_RE = re.compile(r"^[\-\*]\s+(.+)$")
_NUMBERED_RE = re.compile(r"^\d+\.\s+(.+)$")


def parse_markdown_to_paragraphs(
    text: str,
) -> List[Dict[str, Optional[str]]]:
    """把 markdown 文本解析成结构化段落列表。

    Returns:
        每项是 dict：{"text": str, "heading": Optional[str], "style": Optional[str]}
    """
    if not text or not text.strip():
        return [{"text": "", "heading": None, "style": None}]

    result: List[Dict[str, Optional[str]]] = []
    # 按空行分段（一段 = 一个或多个连续非空行）
    blocks = re.split(r"\n\s*\n", text.strip())

    for block in blocks:
        for line in block.split("\n"):
            line = line.rstrip()
            if not line:
                continue
            m = _HEADING_RE.match(line)
            if m:
                result.append(
                    {"text": m.group(2).strip(), "heading": f"h{len(m.group(1))}", "style": None}
                )
                continue
            m = _BULLET_RE.match(line)
            if m:
                result.append({"text": m.group(1).strip(), "heading": None, "style": "bullet"})
                continue
            m = _NUMBERED_RE.match(line)
            if m:
                result.append({"text": m.group(1).strip(), "heading": None, "style": "numbered"})
                continue
            # 普通段落
            result.append({"text": line, "heading": None, "style": None})

    if not result:
        return [{"text": "", "heading": None, "style": None}]
    return result


__all__ = ["parse_markdown_to_paragraphs"]