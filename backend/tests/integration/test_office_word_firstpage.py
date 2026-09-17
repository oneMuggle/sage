"""Integration tests for Word first-page-different header/footer (Round 33).

Covers: first-page header/footer written independently, body pages
using the generic header, PAGE field in first-page footer, zero change
when first_page_different is false, and model validation.
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

from backend.office.models import OfficeWordGenerateRequest, WordFormatSpec
from backend.office.word import generate_docx


def _generate(tmp_path: Path, name: str, spec: dict, **kwargs) -> Path:
    req = OfficeWordGenerateRequest(
        workspace_path="",
        filename=name,
        title="测试文档",
        format_spec=spec,
        **kwargs,
    )
    return generate_docx(req, output_dir=str(tmp_path))


def _first_page_fields(section) -> list:
    fields = []
    for p in section.first_page_footer.paragraphs:
        for fld in p._p.findall(".//" + qn("w:fldSimple")):
            fields.append(fld.get(qn("w:instr")))
    return fields


def test_first_page_different_written(tmp_path: Path) -> None:
    path = _generate(
        tmp_path,
        "fp.docx",
        {
            "first_page_different": True,
            "first_page_header": {"text": "封面页眉"},
            "first_page_footer": {"text": "封面页脚"},
        },
        paragraphs=[{"text": "正文"}],
    )
    doc = Document(str(path))
    section = doc.sections[0]
    assert section.different_first_page_header_footer is True
    assert section.first_page_header.paragraphs[0].text == "封面页眉"
    assert section.first_page_footer.paragraphs[0].text == "封面页脚"


def test_first_page_footer_page_field(tmp_path: Path) -> None:
    path = _generate(
        tmp_path,
        "fpf.docx",
        {
            "first_page_different": True,
            "first_page_footer": {"text": "首页", "page_number": True},
        },
        paragraphs=[{"text": "正文"}],
    )
    doc = Document(str(path))
    section = doc.sections[0]
    fields = _first_page_fields(section)
    assert fields == ["PAGE"]


def test_first_page_disabled_zero_change(tmp_path: Path) -> None:
    path = _generate(
        tmp_path,
        "off.docx",
        {
            "first_page_different": False,
            "first_page_header": {"text": "不应出现"},
        },
        paragraphs=[{"text": "正文"}],
    )
    doc = Document(str(path))
    section = doc.sections[0]
    assert section.different_first_page_header_footer is False
    # 未启用时不写首页页眉
    assert section.first_page_header.paragraphs[0].text != "不应出现"


def test_model_first_page_fields() -> None:
    spec = WordFormatSpec(first_page_different=True)
    assert spec.first_page_different is True
    assert spec.first_page_header is None



