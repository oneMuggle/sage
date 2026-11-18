"""记忆标题推导共享工具 (2026-11-17 记忆详情化)。

背景：记忆页此前把 content 的前 30 字硬截断当"标题"，长记忆不可扫读。
本模块提供确定性标题推导（不调用 LLM）：取首个非空行、去掉常见
markdown/列表前缀、压缩空白、按字数截断。写入路径缺省用它生成
``title`` 列；读取路径对存量空值行同样用它兜底。

与 ``summary_text.truncate_summary`` 的区别：后者是对全文的逐字截断
（生成 summary 列），本模块只取首个有效行并去掉格式前缀，语义是
"可扫读的短标题"。前端 ``src/widgets/memory/memoryTitle.ts`` 保持同一
套规则，两侧输出应一致。
"""

from __future__ import annotations

import re
from typing import Optional

TITLE_MAX_LENGTH = 60

_PREFIX_PATTERNS = (
    re.compile(r"^#{1,6}\s+"),
    re.compile(r"^[-*>•]\s+"),
    re.compile(r"^\d+[.)、]\s*"),
)


def normalize_whitespace(text: str) -> str:
    """压缩所有连续空白（含换行/制表符）为单个空格。"""
    return " ".join(text.split())


def derive_title(content: Optional[str], max_length: int = TITLE_MAX_LENGTH) -> str:
    """确定性标题推导。

    Args:
        content: 原始记忆内容；空/None → ``"无标题"``。
        max_length: 最大字符数，超出时截断并以省略号收尾。

    Returns:
        可扫读的短标题（≤ ``max_length`` 字符）。
    """
    if not content:
        return "无标题"

    first_line = ""
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line:
            first_line = line
            break

    cleaned = first_line
    for pattern in _PREFIX_PATTERNS:
        cleaned = pattern.sub("", cleaned, count=1)
    cleaned = cleaned.strip()

    normalized = normalize_whitespace(cleaned) or normalize_whitespace(content)
    if not normalized:
        return "无标题"
    if len(normalized) > max_length:
        return normalized[: max_length - 1] + "…"
    return normalized
