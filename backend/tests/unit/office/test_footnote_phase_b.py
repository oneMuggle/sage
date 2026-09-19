"""Unit tests for Round 58 — 脚注 Phase B（样式注入 + 每节重编）。"""

from __future__ import annotations

import base64

import pytest
from docx import Document
from docx.oxml.ns import qn

from backend.office.models import (
    OfficeWordGenerateRequest,
    WordFormatSpec,
    WordImageSpec,
    WordPageSetupSpec,
    WordParagraphSpec,
    WordSectionBreakSpec,
    WordTableSpec,
)
from backend.office.word import generate_docx

pytestmark = pytest.mark.unit

_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _gen(tmp_path, name, format_spec):
    image_file = tmp_path / "tiny.png"
    image_file.write_bytes(base64.b64decode(_TINY_PNG_B64))
    req = OfficeWordGenerateRequest(
        workspace_path="",
        filename=name,
        title="报告",
        paragraphs=[WordParagraphSpec(text="正文{{fn:备注一}}。")],
        images=[WordImageSpec(source=str(image_file), caption="架构图")],
        tables=[WordTableSpec(headers=["A"], rows=[["1"]])],
        format_spec=format_spec,
    )
    return generate_docx(req, output_dir=str(tmp_path))


def test_footnote_styles_injected(tmp_path) -> None:
    output = _gen(tmp_path, "styled.docx", WordFormatSpec())
    doc = Document(str(output))
    style_ids = {
        style.get(qn("w:styleId"))
        for style in doc.styles.element.findall(qn("w:style"))
    }
    assert "FootnoteText" in style_ids
    assert "FootnoteReference" in style_ids


def test_footnote_restart_each_section(tmp_path) -> None:
    """分节 page_setup 声明 footnote_restart_each_section → 新节 sectPr
    写 numRestart=eachSect；主节未声明则不写。"""
    req = OfficeWordGenerateRequest(
        workspace_path="",
        filename="r.docx",
        title="报告",
        paragraphs=[
            WordParagraphSpec(text="前置"),
            WordParagraphSpec(text="正文", heading="h1"),
        ],
        tables=[WordTableSpec(headers=["A"], rows=[["1"]])],
        format_spec=WordFormatSpec(
            section_breaks=[
                WordSectionBreakSpec(
                    start_paragraph=1,
                    page_setup=WordPageSetupSpec(
                        footnote_restart_each_section=True
                    ),
                )
            ],
        ),
    )
    output = generate_docx(req, output_dir=str(tmp_path))
    doc = Document(str(output))

    sections = doc.sections
    first_fnpr = sections[0]._sectPr.find(qn("w:footnotePr"))
    assert first_fnpr is None  # 主节未声明 → 零触碰
    second_fnpr = sections[1]._sectPr.find(qn("w:footnotePr"))
    assert second_fnpr is not None
    restart = second_fnpr.find(qn("w:numRestart"))
    assert restart is not None
    assert restart.get(qn("w:val")) == "eachSect"
