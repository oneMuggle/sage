# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""Markdown → Word 文档结构解析器。

支持：
- # / ## / ### 标题（行内标记拍平为纯文本）
- - / * bullet 列表，1. / 2. 编号列表
- > 引用块（style="quote"）
- 管道表格（首行表头 + |---| 分隔行）→ tables
- 独立成行的 ![alt](src) → images（记入前一段下标）
- 行内 **bold** / *italic* / ***both*** / [text](url) → runs
- 普通段落；emoji 原样保留

不处理（YAGNI）：嵌套列表、嵌套强调、转义字符、单元格内 runs。
无行内标记的段落不附 runs 键，返回结构与历史版本逐键一致。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$")
_BULLET_RE = re.compile(r"^[\-\*]\s+(.+)$")
_NUMBERED_RE = re.compile(r"^\d+\.\s+(.+)$")
_QUOTE_RE = re.compile(r"^>\s?(.*)$")
_IMAGE_RE = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+)\)\s*$")
_TABLE_DELIM_CELL_RE = re.compile(r"^:?-{3,}:?$")

# 顺序即优先级：加粗斜体 > 加粗 > 斜体 > 链接
_INLINE_RE = re.compile(
    r"\*\*\*(?P<bolditalic>[^*]+?)\*\*\*"
    r"|\*\*(?P<bold>.+?)\*\*"
    r"|\*(?P<italic>[^*]+?)\*"
    r"|\[(?P<linktext>[^\]]+)\]\((?P<linkurl>[^)\s]+)\)"
)


def _tokenize_inline(text: str) -> Tuple[str, Optional[List[Dict[str, Any]]]]:
    """把一行行内标记拆成 runs。

    Returns:
        (拍平后的纯文本, runs 或 None)。无标记时 runs 为 None。
    """
    runs: List[Dict[str, Any]] = []
    pos = 0
    found = False
    for match in _INLINE_RE.finditer(text):
        found = True
        if match.start() > pos:
            runs.append({"text": text[pos : match.start()]})
        if match.group("bolditalic") is not None:
            runs.append({"text": match.group("bolditalic"), "bold": True, "italic": True})
        elif match.group("bold") is not None:
            runs.append({"text": match.group("bold"), "bold": True})
        elif match.group("italic") is not None:
            runs.append({"text": match.group("italic"), "italic": True})
        else:
            runs.append({"text": match.group("linktext"), "link": match.group("linkurl")})
        pos = match.end()
    if not found:
        return text, None
    if pos < len(text):
        runs.append({"text": text[pos:]})
    runs = [run for run in runs if run["text"]]
    if not runs:
        return "", None
    return "".join(run["text"] for run in runs), runs


def _make_paragraph(
    text: str, heading: Optional[str] = None, style: Optional[str] = None
) -> Dict[str, Any]:
    flat, runs = _tokenize_inline(text)
    para: Dict[str, Any] = {"text": flat, "heading": heading, "style": style}
    if runs:
        para["runs"] = runs
    return para


def _split_table_row(line: str) -> List[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_table_delimiter_row(line: str) -> bool:
    cells = _split_table_row(line)
    return bool(cells) and all(_TABLE_DELIM_CELL_RE.match(cell) for cell in cells)


def parse_markdown_document(text: str) -> Dict[str, Any]:
    """把 markdown 解析成文档结构。

    Returns:
        {"paragraphs": [...], "tables": [...], "images": [...]}
        - paragraphs 项：{"text", "heading", "style"}，有行内标记时附 "runs"
        - tables 项：{"headers": [str], "rows": [[str]]}
        - images 项：{"source", "caption", "after_paragraph"}
    """
    paragraphs: List[Dict[str, Any]] = []
    tables: List[Dict[str, List[str]]] = []
    images: List[Dict[str, Any]] = []

    if not text or not text.strip():
        return {
            "paragraphs": [{"text": "", "heading": None, "style": None}],
            "tables": [],
            "images": [],
        }

    # 按空行分块（一段 = 一个或多个连续非空行）
    blocks = re.split(r"\n\s*\n", text.strip())
    for block in blocks:
        lines = [raw.rstrip() for raw in block.split("\n") if raw.strip()]
        index = 0
        while index < len(lines):
            line = lines[index]
            # 表格：首行以 | 开头且下一行是 |---| 分隔行
            if (
                line.lstrip().startswith("|")
                and index + 1 < len(lines)
                and _is_table_delimiter_row(lines[index + 1])
            ):
                headers = [_tokenize_inline(cell)[0] for cell in _split_table_row(line)]
                rows: List[List[str]] = []
                index += 2
                while index < len(lines) and lines[index].lstrip().startswith("|"):
                    rows.append(
                        [_tokenize_inline(cell)[0] for cell in _split_table_row(lines[index])]
                    )
                    index += 1
                tables.append({"headers": headers, "rows": rows})
                continue
            match = _IMAGE_RE.match(line.strip())
            if match:
                images.append(
                    {
                        "source": match.group(2),
                        "caption": match.group(1).strip() or None,
                        "after_paragraph": len(paragraphs) - 1,
                    }
                )
                index += 1
                continue
            match = _HEADING_RE.match(line)
            if match:
                flat, _ = _tokenize_inline(match.group(2).strip())
                paragraphs.append(
                    {"text": flat, "heading": f"h{len(match.group(1))}", "style": None}
                )
                index += 1
                continue
            if line.startswith(">"):
                body = _QUOTE_RE.match(line)
                paragraphs.append(
                    _make_paragraph((body.group(1) if body else "").strip(), style="quote")
                )
                index += 1
                continue
            match = _BULLET_RE.match(line)
            if match:
                paragraphs.append(_make_paragraph(match.group(1).strip(), style="bullet"))
                index += 1
                continue
            match = _NUMBERED_RE.match(line)
            if match:
                paragraphs.append(_make_paragraph(match.group(1).strip(), style="numbered"))
                index += 1
                continue
            paragraphs.append(_make_paragraph(line))
            index += 1

    if not paragraphs and not tables and not images:
        paragraphs = [{"text": "", "heading": None, "style": None}]
    return {"paragraphs": paragraphs, "tables": tables, "images": images}


def parse_markdown_to_paragraphs(text: str) -> List[Dict[str, Any]]:
    """把 markdown 文本解析成结构化段落列表（兼容旧接口）。

    Returns:
        每项是 dict：{"text": str, "heading": Optional[str], "style": Optional[str]}；
        有行内标记时附 "runs"。
    """
    return parse_markdown_document(text)["paragraphs"]


__all__ = ["parse_markdown_document", "parse_markdown_to_paragraphs"]
