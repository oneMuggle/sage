"""BibTeX 解析（Round 9）—— .bib 文本 → 结构化 ReferenceSpec 列表。

确定性手写实现，零第三方依赖（不引 bibtexparser：双通道依赖矩阵 +
py38 wheel 风险）。覆盖论文写作常用 entry 类型：

==========  =====================  ==========================
@type       → ReferenceType        字段映射
==========  =====================  ==========================
article     journal                journal→source, number→issue
book        book                   publisher/address
inproceedings conference             booktitle→source
phdthesis / mastersthesis  thesis  school→source
techreport  report                 institution→source
misc/online webpage（有 url 时）/ report  howpublished→source
==========  =====================  ==========================

清理规则：值可为 ``{...}`` 或 ``"..."``；花括号剥除、``~``→空格、
``--``→``-``（页码区间）、连续空白折叠；作者按 BibTeX 规范以
`` and ``（两侧空格）切分。``language`` 不取自输入（按 title CJK 自动
判定），解析结果如需指定语言由调用方补写。

未知 @type 归入 misc 语义（有 url → webpage，否则 report）；一条
条目解析失败跳过该条（带 logging.warning），全部失败/输入为空 →
:class:`OfficeParseError`。
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Tuple

from .errors import OfficeParseError
from .models import ReferenceSpec

logger = logging.getLogger(__name__)

_ENTRY_HEAD_RE = re.compile(r"@(?P<type>[A-Za-z]+)\s*\{\s*(?P<key>[^,\s]+)\s*,")
_FIELD_RE = re.compile(r"(\w+)\s*=\s*", re.ASCII)

#: @type → ReferenceType 主映射（misc/online 特判见 _BIBTEX_TYPE_MAP 注释）
_BIBTEX_TYPE_MAP = {
    "article": "journal",
    "book": "book",
    "inproceedings": "conference",
    "conference": "conference",
    "phdthesis": "thesis",
    "mastersthesis": "thesis",
    "techreport": "report",
    "proceedings": "conference",
    "misc": "webpage",
    "online": "webpage",
    "electronic": "webpage",
    "manual": "report",
    "unpublished": "report",
    "patent": "patent",
    "standard": "standard",
}


def _clean_value(raw: str) -> str:
    """剥引号/花括号 + 字符规范化（~→空格、--→-、空白折叠）。"""
    value = raw.strip()
    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    # 剥除包裹花括号（保留内部嵌套花括号内容本身——简化：全部剥除）
    while value.startswith("{") and value.endswith("}"):
        value = value[1:-1]
    value = value.replace("{", "").replace("}", "")
    value = value.replace("~", " ").replace("\\&", "&")
    value = re.sub(r"--+", "-", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _split_top_level_braces(text: str, start: int) -> Tuple[str, int]:
    """从 start（指向 '{'）起取配对花括号内的内容，返回 (内容, 结束下标)。"""
    depth = 0
    in_quotes = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if ch == '"' and depth > 0:
            in_quotes = not in_quotes
        elif ch == "{" and not in_quotes:
            depth += 1
        elif ch == "}" and not in_quotes:
            depth -= 1
            if depth == 0:
                return text[start + 1 : idx], idx
    raise OfficeParseError("BibTeX 条目花括号不配对")


def _parse_fields(body: str) -> Dict[str, str]:
    """解析条目体的 `name = value` 字段（value 为 {…} / "…" / 裸数字）。"""
    fields: Dict[str, str] = {}
    idx = 0
    length = len(body)
    while idx < length:
        match = _FIELD_RE.search(body, idx)
        if match is None:
            break
        name = match.group(1).lower()
        idx = match.end()
        while idx < length and body[idx] in " \t\r\n":
            idx += 1
        if idx >= length:
            break
        if body[idx] == "{":
            value, idx = _split_top_level_braces(body, idx)
            idx += 1
        elif body[idx] == '"':
            end = body.find('"', idx + 1)
            if end == -1:
                raise OfficeParseError(f"BibTeX 字段 {name} 引号不配对")
            value = body[idx + 1 : end]
            idx = end + 1
        else:
            end = body.find(",", idx)
            if end == -1:
                end = length
            value = body[idx:end]
            idx = end
        # 跳过逗号与空白到下一字段
        while idx < length and body[idx] in ", \t\r\n":
            idx += 1
        fields[name] = _clean_value(value)
    return fields


def _spec_from_entry(entry_type: str, key: str, fields: Dict[str, str]) -> ReferenceSpec:
    ref_type = _BIBTEX_TYPE_MAP.get(entry_type, "report")
    if ref_type == "webpage" and not fields.get("url"):
        # 无 url 的 misc 归为 report（报告/预印本类内容）
        ref_type = "report"
    authors = [a.strip() for a in re.split(r"\s+and\s+", fields.get("author", "")) if a.strip()]
    return ReferenceSpec(
        key=key,
        ref_type=ref_type,  # type: ignore[arg-type]
        title=fields.get("title") or fields.get("booktitle") or "",
        authors=authors,
        year=fields.get("year"),
        source=fields.get("journal")
        or fields.get("booktitle")
        or fields.get("school")
        or fields.get("institution")
        or fields.get("howpublished"),
        volume=fields.get("volume"),
        issue=fields.get("number"),
        pages=fields.get("pages"),
        publisher=fields.get("publisher"),
        address=fields.get("address"),
        url=fields.get("url") or None,
        doi=fields.get("doi") or None,
    )


def parse_bibtex(text: str) -> List[ReferenceSpec]:
    """解析 BibTeX 文本为 ReferenceSpec 列表。

    坏条目跳过（warning 日志），不阻断其余条目；无可解析条目时抛
    :class:`OfficeParseError`（空输入/纯噪声一致处理）。
    """
    if not text or not text.strip():
        raise OfficeParseError("BibTeX 输入为空")

    specs: List[ReferenceSpec] = []
    pos = 0
    while True:
        head = _ENTRY_HEAD_RE.search(text, pos)
        if head is None:
            break
        entry_type = head.group("type").lower()
        key = head.group("key")
        # 匹配段 "@type{key," 内的 '{' 即条目体起点
        brace_idx = text.rfind("{", head.start(), head.end())
        if brace_idx == -1:
            pos = head.end()
            continue
        try:
            body, close_idx = _split_top_level_braces(text, brace_idx)
        except OfficeParseError as exc:
            logger.warning("BibTeX 条目 %s 解析失败: %s", key, exc)
            pos = head.end()
            continue
        pos = close_idx + 1
        try:
            fields = _parse_fields(body)
            spec = _spec_from_entry(entry_type, key, fields)
        except Exception as exc:  # noqa: BLE001 — 单条失败不阻断批次
            logger.warning("BibTeX 条目 %s 字段解析失败: %s", key, exc)
            continue
        if not spec.title:
            logger.warning("BibTeX 条目 %s 缺 title，跳过", key)
            continue
        specs.append(spec)

    if not specs:
        raise OfficeParseError("BibTeX 输入中未解析出任何条目")
    return specs


def parse_bibtex_file(path: str, *, max_bytes: int = 5 * 1024 * 1024) -> List[ReferenceSpec]:
    """从 .bib 文件解析（上限 5MB，与 office 图片预算同级）。"""
    from pathlib import Path

    bib_path = Path(path)
    size = bib_path.stat().st_size
    if size > max_bytes:
        raise OfficeParseError(f"BibTeX 文件过大: {size} > {max_bytes}")
    return parse_bibtex(bib_path.read_text(encoding="utf-8", errors="replace"))
