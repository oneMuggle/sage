"""从 .docx (OOXML) 抽取 JournalSpec。

关键实现：
- python-docx 读取 styles.xml 和 sectPr；
- 字体取 w:eastAsia（CJK 优先）再回退到 w:ascii；
- 字号 w:sz 单位是 half-point（24 = 12pt）；
- 行距 w:line 单位 240ths（240 = 1.0 倍）；
- 边距 w:pgMar 单位 twips（567 ≈ 1cm）；
- 章节由 style.outline_lvl 判定；
- 同族字体归一化（_FONT_FAMILY_ALIASES）。

设计要点：
- PEP 604/585 全部禁用（X | None / list[int]）；运行时注解用 Optional/List/Dict；
- `.doc` 输入委托 pandoc_adapter.convert_doc_to_docx；失败包装为 JournalParseError。
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Dict, List, Optional

from docx import Document
from docx.enum.text import WD_LINE_SPACING
from docx.oxml.ns import qn

from backend.office.journal.errors import JournalPandocError, JournalParseError
from backend.office.journal.models import (
    CitationStyle,
    FontFamily,
    HeadingSpec,
    JournalSpec,
)
from backend.office.journal.pandoc_adapter import convert_doc_to_docx

_PT_TO_CN: Dict[float, str] = {
    42.0: "初号",
    36.0: "小初",
    26.0: "一号",
    24.0: "小一",
    22.0: "二号",
    18.0: "小二",
    16.0: "三号",
    15.0: "小三",
    14.0: "四号",
    12.0: "小四",
    10.5: "五号",
    9.0: "小五",
    7.5: "六号",
    6.5: "小六",
    5.5: "七号",
    4.5: "八号",
}

_FONT_FAMILY_ALIASES: Dict[str, str] = {
    "宋体": "宋体",
    "SimSun": "宋体",
    "Songti SC": "宋体",
    "Noto Serif CJK SC": "宋体",
    "黑体": "黑体",
    "SimHei": "黑体",
    "Heiti SC": "黑体",
    "Noto Sans CJK SC": "黑体",
    "楷体": "楷体",
    "KaiTi": "楷体",
    "微软雅黑": "微软雅黑",
    "Microsoft YaHei": "微软雅黑",
    "Times New Roman": "Times New Roman",
    "Times": "Times New Roman",
    "Liberation Serif": "Times New Roman",
    "Arial": "Arial",
    "Liberation Sans": "Arial",
    "Helvetica": "Arial",
}


def _normalize_font(name: Optional[str]) -> str:
    if not name:
        return ""
    return _FONT_FAMILY_ALIASES.get(name.strip(), name.strip())


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _style_eastasia(style) -> str:
    rPr = style._element.find(qn("w:rPr"))
    if rPr is None:
        return ""
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        return ""
    return (rFonts.get(qn("w:eastAsia")) or "").strip()


def _style_pt(style) -> float:
    rPr = style._element.find(qn("w:rPr"))
    if rPr is None:
        return 0.0
    sz = rPr.find(qn("w:sz"))
    if sz is None:
        return 0.0
    val = sz.get(qn("w:val")) or "0"
    try:
        half_pt = float(val)
    except ValueError:
        return 0.0
    return half_pt / 2.0


def _style_line_spacing(style) -> float:
    pf = style.paragraph_format
    if pf.line_spacing is None:
        return 0.0
    if isinstance(pf.line_spacing_rule, WD_LINE_SPACING):
        # 倍数（1.0/1.5/2.0）
        return float(pf.line_spacing)
    if isinstance(pf.line_spacing, (int, float)):  # noqa: UP038 - 兼容 Py3.8
        return float(pf.line_spacing)
    return 0.0


def _style_margins_cm(section) -> float:
    # 取左右页边（中文期刊一般对称）
    left = section.left_margin
    right = section.right_margin
    if left is None or right is None:
        return 0.0
    # Cm 是 360000 EMU per cm
    return float(left) / 360000.0


def _heading_keywords(doc: Document) -> List[HeadingSpec]:
    out: List[HeadingSpec] = []
    for para in doc.paragraphs:
        if para.style and para.style.name and para.style.name.startswith("Heading"):
            text = para.text.strip()
            if not text:
                continue
            # 尝试按段落文本取标题级别
            try:
                level = int(para.style.name.split()[-1])
            except (ValueError, IndexError):
                level = 1
            out.append(
                HeadingSpec(
                    keyword=text,
                    level=level,
                    expected_pt=_style_pt(para.style) or 0.0,
                )
            )
    # 去重 keyword
    seen = set()
    deduped: List[HeadingSpec] = []
    for h in out:
        if h.keyword in seen:
            continue
        seen.add(h.keyword)
        deduped.append(h)
    return deduped


def _detect_citation_style(doc: Document) -> CitationStyle:
    """从全文文本匹配引用模式。"""
    full = "\n".join(p.text for p in doc.paragraphs)
    if not full.strip():
        return CitationStyle.UNKNOWN
    # numeric style — bracket-N / bracket-N-M
    if re.search(r"\[\d+(?:,\s*\d+)*\]", full):
        return CitationStyle.NUMERIC
    # author_year like "张三等，2020" 或 "(Smith, 2020)"
    if re.search(r"（\d{4}）|\(\d{4}\)", full):
        return CitationStyle.AUTHOR_YEAR_PAREN
    if re.search(r"等[，,]\s*\d{4}", full):
        return CitationStyle.AUTHOR_YEAR
    return CitationStyle.UNKNOWN


def _resolve_input(input_path: Path, cache_dir: Optional[Path]) -> Path:
    """处理 .doc 输入；.docx 透传；失败包装为 JournalParseError。"""
    if not input_path.exists():
        raise JournalParseError(f"模板文件不存在: {input_path}")
    suffix = input_path.suffix.lower()
    if suffix == ".doc":
        try:
            return convert_doc_to_docx(input_path, cache_dir=cache_dir or Path())
        except JournalPandocError as exc:
            raise JournalParseError(f"pandoc 转换失败: {exc}") from exc
    if suffix == ".docx":
        return input_path
    raise JournalParseError(f"不支持的扩展名: {suffix}")


def parse_journal_spec(
    input_path: Path, *, cache_dir: Optional[Path] = None
) -> JournalSpec:
    """从 .doc / .docx 模板抽取 JournalSpec。"""
    docx_path = _resolve_input(input_path, cache_dir)
    try:
        doc = Document(str(docx_path))
    except Exception as exc:  # noqa: BLE001
        raise JournalParseError(f"无法打开 docx: {exc}") from exc

    # 主体样式
    normal = doc.styles["Normal"]
    body_ea = _style_eastasia(normal)
    body_ascii = ""
    rPr = normal._element.find(qn("w:rPr"))
    if rPr is not None:
        rFonts = rPr.find(qn("w:rFonts"))
        if rFonts is not None:
            body_ascii = rFonts.get(qn("w:ascii")) or ""

    # Heading 1 样式（若无则从段落样本推断）
    all_style_names = [s.name for s in doc.styles]
    heading_style = (
        doc.styles["Heading 1"] if "Heading 1" in all_style_names else None
    )
    if heading_style is None:
        # fallback: 找第一个 Heading N
        for s in doc.styles:
            if s.name and s.name.startswith("Heading"):
                heading_style = s
                break

    heading_ea = (
        _style_eastasia(heading_style) if heading_style is not None else ""
    )
    body_pt = _style_pt(normal) or 12.0
    heading_pt = (
        _style_pt(heading_style) if heading_style is not None else 0.0
    )
    if heading_pt == 0.0:
        heading_pt = max(body_pt + 4.0, 16.0)
    line_spacing = _style_line_spacing(normal) or 1.5
    section = doc.sections[0] if doc.sections else None
    margins_cm = (
        _style_margins_cm(section) if section is not None else 2.54
    )
    if margins_cm == 0.0:
        margins_cm = 2.54

    headings = _heading_keywords(doc) or [
        HeadingSpec(keyword="摘要", level=1, expected_pt=heading_pt),
        HeadingSpec(keyword="关键词", level=1, expected_pt=heading_pt),
    ]

    return JournalSpec(
        spec_id=f"spec_{_sha256(docx_path)[:12]}",
        template_sha256=_sha256(docx_path),
        template_filename=input_path.name,
        font_body=FontFamily(
            family=_normalize_font(body_ea),
            ascii_family=_normalize_font(body_ascii),
            eastasia=_normalize_font(body_ea),
        ),
        font_heading=FontFamily(
            family=_normalize_font(heading_ea) or _normalize_font(body_ea),
            ascii_family=_normalize_font(heading_ea)
            or _normalize_font(body_ascii),
            eastasia=_normalize_font(heading_ea) or _normalize_font(body_ea),
        ),
        body_pt=body_pt,
        heading_pt=heading_pt,
        line_spacing=line_spacing,
        margins_cm=margins_cm,
        headings=headings,
        citation_style=_detect_citation_style(doc),
        page_size="A4",
        extra={},
    )


__all__ = ["parse_journal_spec"]
