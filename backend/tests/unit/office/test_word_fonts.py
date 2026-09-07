"""字体设置测试。"""
from __future__ import annotations

from docx import Document
from docx.oxml.ns import qn

from backend.office.word import (
    DEFAULT_ASCII_FONT,
    DEFAULT_EA_FONT,
    set_doc_default_font,
)


def test_default_constants() -> None:
    """常量必须是 Times New Roman + 宋体。"""
    assert DEFAULT_ASCII_FONT == "Times New Roman"
    assert DEFAULT_EA_FONT == "宋体"


def test_set_doc_default_font_writes_styles_xml() -> None:
    """调用后 styles.xml 的 Normal.rPr.rFonts 出现 eastAsia=宋体。"""
    doc = Document()
    set_doc_default_font(doc, DEFAULT_ASCII_FONT, DEFAULT_EA_FONT)

    normal = doc.styles["Normal"]
    rPr = normal.element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    assert rFonts is not None
    assert rFonts.get(qn("w:ascii")) == "Times New Roman"
    assert rFonts.get(qn("w:eastAsia")) == "宋体"


def test_set_doc_default_font_overrides_existing() -> None:
    """重复调用以最后一次为准。"""
    doc = Document()
    set_doc_default_font(doc, "Arial", "微软雅黑")
    set_doc_default_font(doc, DEFAULT_ASCII_FONT, DEFAULT_EA_FONT)
    normal = doc.styles["Normal"]
    rFonts = normal.element.get_or_add_rPr().find(qn("w:rFonts"))
    assert rFonts.get(qn("w:eastAsia")) == "宋体"
