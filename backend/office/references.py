"""参考文献引用引擎（Round 9）——结构化条目 → 参考文献表文本。

纯字符串格式化，零 docx 依赖、零第三方依赖：generate_docx 通路与
journal 子系统（#584）后续均可复用。不引入 citeproc-py / bibtexparser
（避免双通道依赖矩阵变化与 py38 wheel 风险）。

简化范围（刻意收窄并在此文档化）：
- GB/T 7714-2015 顺序编码制：覆盖论文/报告写作常用的 9 类条目形状，
  不处理译者/版次/丛书/析出文献嵌套等边角；
- APA 为第 7 版简化子集（作者不做名缩写变换，按输入原样列出）；
- ``language`` 缺省时按 title 是否含 CJK 字符自动判定，决定截断词
  （"等" / "et al"）。

编号规则由调用方（word.py 生成器）维护：段落 citations 的 key 首次
出现顺序即文内编号，本文模块只负责"单条条目 → 不带编号的文本"。
"""

from __future__ import annotations

import re
from typing import List, Optional

from .models import ReferenceSpec

#: GB/T 7714-2015 文献类型代码（顺序编码制方括号标识）
_GBT_TYPE_CODES = {
    "journal": "J",
    "book": "M",
    "thesis": "D",
    "conference": "C",
    "report": "R",
    "webpage": "EB/OL",
    "patent": "P",
    "standard": "S",
    "newspaper": "N",
}

#: 作者截断上限（GB/T 7714：>3 取前 3 加"等"/"et al"）
_GBT_MAX_AUTHORS = 3

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))


def _is_zh(ref: ReferenceSpec) -> bool:
    if ref.language is not None:
        return ref.language == "zh"
    return _has_cjk(ref.title)


def format_authors(ref: ReferenceSpec, *, style: str) -> str:
    """作者列表 → "A, B, C"（截断词按语言）；空作者列表返回空串。"""
    authors = [a.strip() for a in ref.authors if a and a.strip()]
    if not authors:
        return ""
    zh = _is_zh(ref)
    if style == "apa":
        return ", ".join(authors)
    if len(authors) > _GBT_MAX_AUTHORS:
        authors = authors[:_GBT_MAX_AUTHORS]
        return ", ".join(authors) + (" 等" if zh else " et al")
    return ", ".join(authors)


def _seg(*parts: Optional[str]) -> str:
    """按序拼接非空片段（前置分隔符已含在片段内）。"""
    return "".join(p for p in parts if p)


def format_gbt7714(ref: ReferenceSpec) -> str:
    """GB/T 7714-2015 顺序编码制单条条目（不含序号 "[N]"，调用方加）。

    各类型模板（缺字段时优雅退化）：
    - journal:    作者. 题名[J]. 刊名, 年, 卷(期): 页.
    - book:       作者. 题名[M]. 出版地: 出版社, 年: 页.
    - thesis:     作者. 题名[D]. 城市: 学校, 年.
    - conference: 作者. 题名[C]// 会议名. 出版地: 出版社, 年: 页.
    - report:     作者. 题名[R]. 机构, 年.
    - newspaper:  作者. 题名[N]. 报纸名, 年: 版次.
    - patent:     作者. 题名[P]. 年.
    - standard:   题名[S]. 出版地: 出版社, 年.
    - webpage:    作者. 题名[EB/OL]. [引用日期]. URL.
    """
    code = _GBT_TYPE_CODES[ref.ref_type]
    authors = format_authors(ref, style="gbt7714")
    head = f"{authors}. " if authors else ""

    if ref.ref_type == "webpage":
        body = f"{ref.title}[{code}]."
        if ref.access_date:
            body += f" [{ref.access_date}]."
        if ref.url:
            body += f" {ref.url}."
        elif ref.doi:
            body += f" DOI: {ref.doi}."
        return head + body

    body = f"{ref.title}[{code}]."
    if ref.ref_type == "journal":
        if ref.source:
            body += f" {ref.source},"
        if ref.year:
            body += f" {ref.year}"
        if ref.volume:
            body += f", {ref.volume}"
        if ref.issue:
            body += f"({ref.issue})"
        if ref.pages:
            body += f": {ref.pages}"
    elif ref.ref_type in ("book", "standard"):
        if ref.address:
            body += f" {ref.address}:"
        if ref.publisher:
            body += f" {ref.publisher},"
        if ref.year:
            body += f" {ref.year}"
        if ref.pages:
            body += f": {ref.pages}"
    elif ref.ref_type == "thesis":
        if ref.address:
            body += f" {ref.address}:"
        if ref.source:
            body += f" {ref.source},"
        if ref.year:
            body += f" {ref.year}"
    elif ref.ref_type == "conference":
        if ref.source:
            # GB/T 析出文献接续符紧跟类型码，中间不加句点：题名[C]//会议名.
            body = body.rstrip(".") + f"// {ref.source}."
        if ref.address:
            body += f" {ref.address}:"
        if ref.publisher:
            body += f" {ref.publisher},"
        if ref.year:
            body += f" {ref.year}"
        if ref.pages:
            body += f": {ref.pages}"
    elif ref.ref_type in ("report", "newspaper"):
        if ref.source:
            body += f" {ref.source},"
        if ref.year:
            body += f" {ref.year}"
        if ref.pages and ref.ref_type == "newspaper":
            body += f": {ref.pages}"
    elif ref.ref_type == "patent":
        if ref.year:
            body += f" {ref.year}"

    # GB/T 条目以句点收尾（webpage 分支已自行保证）
    return head + (body if body.endswith(".") else body + ".")


def format_apa(ref: ReferenceSpec) -> str:
    """APA 第 7 版简化子集（作者名不做缩写变换，按输入原样）。

    形状: 作者 (年). 题名. 来源, 卷(期), 页. 出版社. DOI/URL.
    """
    authors = format_authors(ref, style="apa")
    head = f"{authors} " if authors else ""
    year = f"({ref.year}). " if ref.year else ""

    segments: List[str] = []
    if ref.source:
        source = ref.source
        if ref.volume:
            source += f", {ref.volume}"
            if ref.issue:
                source += f"({ref.issue})"
        if ref.pages:
            source += f", {ref.pages}"
        segments.append(source + ".")
    elif ref.publisher:
        segments.append(ref.publisher + ".")

    text = (head + year + ref.title + ".").strip()
    if segments:
        text += " " + " ".join(segments)
    if ref.doi:
        text += f" https://doi.org/{ref.doi}"
    elif ref.url:
        text += f" {ref.url}"
    return text


def format_reference(ref: ReferenceSpec, style: str) -> str:
    """按 style 分发（"gbt7714" | "apa"）；未知 style 由请求模型约束。"""
    if style == "apa":
        return format_apa(ref)
    return format_gbt7714(ref)


def compact_citation_marker(numbers: List[int]) -> str:
    """编号列表 → 上标标记文本（"[1]"；连续区间合并 "[1-3]，离散 "[1,3]"）。"""
    if not numbers:
        return ""
    ordered = sorted(set(numbers))
    groups: List[List[int]] = []
    for n in ordered:
        if groups and n == groups[-1][-1] + 1:
            groups[-1].append(n)
        else:
            groups.append([n])
    segs = []
    for g in groups:
        segs.append(str(g[0]) if len(g) == 1 else f"{g[0]}-{g[-1]}")
    return "[" + ",".join(segs) + "]"
