"""M2 整块结构填充测试：无占位符模板的段落克隆与内容替换。

对应计划 docs/plans/2026-11-26_word-layout-template-p0.md M2（P0-1）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, Twips

from backend.api.office_word_template_profile_routes import (
    WordTemplateRefillRequest,
    refill_word_template_blocks_endpoint,
)
from backend.office.errors import OfficeTemplateFillError
from backend.office.models import WordTemplateBlock
from backend.office.word_template_refill import fill_word_template_blocks


def _set_outline(paragraph, level: int) -> None:
    pPr = paragraph._p.get_or_add_pPr()
    ol = OxmlElement("w:outlineLvl")
    ol.set(qn("w:val"), str(level))
    pPr.append(ol)


def _add_bookmark(paragraph, name: str, ident: str) -> None:
    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), ident)
    start.set(qn("w:name"), name)
    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), ident)
    paragraph._p.insert(0, start)
    paragraph._p.append(end)


def _build_template(path: Path) -> Path:
    """模仿软著说明书模板：封面 + 直接格式的 h1/h2/正文/加粗段落。"""
    document = Document()
    cover = document.add_paragraph()
    cover_run = cover.add_run("软件名称V1.0")
    cover_run.font.size = Pt(42)

    h1 = document.add_paragraph()
    run = h1.add_run("1、引言")
    run.bold = True
    run.font.size = Pt(16)
    _set_outline(h1, 0)

    h2 = document.add_paragraph()
    run = h2.add_run("1.1 编写目的")
    run.bold = True
    run.font.size = Pt(14)
    _set_outline(h2, 1)

    body = document.add_paragraph()
    run = body.add_run("旧正文内容")
    run.font.size = Pt(12)
    body.paragraph_format.first_line_indent = Twips(480)
    body.paragraph_format.space_after = Twips(156)

    bold = document.add_paragraph()
    run = bold.add_run("1）硬件环境")
    run.bold = True
    run.font.size = Pt(12)

    body2 = document.add_paragraph()
    run = body2.add_run("更多旧正文")
    run.font.size = Pt(12)
    body2.paragraph_format.first_line_indent = Twips(480)

    document.save(str(path))
    return path


BLOCKS = [
    WordTemplateBlock(kind="h1", text="2、系统概述"),
    WordTemplateBlock(kind="h2", text="2.1 系统用途"),
    WordTemplateBlock(kind="body", text="新正文第一段。"),
    WordTemplateBlock(kind="bold", text="1）硬件环境（新）"),
    WordTemplateBlock(kind="body", text="新正文第二段。"),
]


def _output_texts(path: Path):
    document = Document(str(path))
    return [p.text for p in document.paragraphs]


def test_refill_replaces_body_and_preserves_direct_formatting(tmp_path: Path) -> None:
    template = _build_template(tmp_path / "template.docx")

    result = fill_word_template_blocks(
        template, BLOCKS, "out.docx", workspace_path=str(tmp_path)
    )

    assert result["ok"] is True
    assert result["inserted_blocks"] == 5
    assert result["removed_paragraphs"] == 5  # h1 + h2 + body + bold + body2
    texts = _output_texts(tmp_path / "out.docx")
    assert texts[0] == "软件名称V1.0"
    assert texts[1:] == [
        "2、系统概述",
        "2.1 系统用途",
        "新正文第一段。",
        "1）硬件环境（新）",
        "新正文第二段。",
    ]
    document = Document(str(tmp_path / "out.docx"))
    new_h1 = document.paragraphs[1]
    assert new_h1.runs[0].bold is True
    assert new_h1.runs[0].font.size == Pt(16)
    assert new_h1._p.find(qn("w:pPr")).find(qn("w:outlineLvl")).get(qn("w:val")) == "0"
    new_body = document.paragraphs[3]
    assert new_body.paragraph_format.first_line_indent == Twips(480)
    assert new_body.paragraph_format.space_after == Twips(156)
    assert document.paragraphs[4].runs[0].bold is True


def test_refill_honors_explicit_anchors(tmp_path: Path) -> None:
    template = _build_template(tmp_path / "template.docx")

    result = fill_word_template_blocks(
        template,
        [WordTemplateBlock(kind="body", text="仅正文")],
        "out.docx",
        workspace_path=str(tmp_path),
        anchors={"h1": 1, "body": 3},
        start_paragraph=1,
    )

    assert result["anchors"]["body"] == 3
    texts = _output_texts(tmp_path / "out.docx")
    assert texts[0] == "软件名称V1.0"
    assert texts[1] == "仅正文"


def test_refill_region_anchor_text_keeps_prefix_and_suffix(tmp_path: Path) -> None:
    document = Document()
    document.add_paragraph("前言说明")
    h1 = document.add_paragraph()
    run = h1.add_run("1、引言")
    run.bold = True
    run.font.size = Pt(16)
    _set_outline(h1, 0)
    body = document.add_paragraph()
    run = body.add_run("旧正文")
    run.font.size = Pt(12)
    body.paragraph_format.first_line_indent = Twips(480)
    document.add_paragraph("附则说明")
    template = tmp_path / "region.docx"
    document.save(str(template))

    fill_word_template_blocks(
        template,
        [WordTemplateBlock(kind="body", text="新正文")],
        "out.docx",
        workspace_path=str(tmp_path),
        start_anchor_text="1、引言",
        end_anchor_text="附则说明",
    )

    texts = _output_texts(tmp_path / "out.docx")
    assert texts == ["前言说明", "新正文", "附则说明"]


def test_refill_refuses_overwrite(tmp_path: Path) -> None:
    template = _build_template(tmp_path / "template.docx")
    (tmp_path / "out.docx").write_bytes(b"existing")

    with pytest.raises(OfficeTemplateFillError):
        fill_word_template_blocks(
            template, BLOCKS, "out.docx", workspace_path=str(tmp_path)
        )


def test_refill_rejects_missing_block_template(tmp_path: Path) -> None:
    template = _build_template(tmp_path / "template.docx")

    with pytest.raises(OfficeTemplateFillError):
        fill_word_template_blocks(
            template,
            [WordTemplateBlock(kind="h3", text="1.1.1 三级标题")],
            "out.docx",
            workspace_path=str(tmp_path),
        )


def test_refill_strips_bookmarks_from_cloned_block(tmp_path: Path) -> None:
    document = Document()
    h1 = document.add_paragraph()
    run = h1.add_run("1、引言")
    run.bold = True
    run.font.size = Pt(16)
    _set_outline(h1, 0)
    _add_bookmark(h1, "anchor", "101")
    template = tmp_path / "bookmark.docx"
    document.save(str(template))

    result = fill_word_template_blocks(
        template,
        [WordTemplateBlock(kind="h1", text="2、概述")],
        "out.docx",
        workspace_path=str(tmp_path),
        anchors={"h1": 0},
    )

    assert result["ok"] is True
    output = Document(str(tmp_path / "out.docx"))
    assert output.paragraphs[0].text == "2、概述"
    assert output.element.body.find(qn("w:bookmarkStart")) is None
    assert output.element.body.find(qn("w:bookmarkEnd")) is None


def test_refill_rejects_block_template_with_field(tmp_path: Path) -> None:
    document = Document()
    h1 = document.add_paragraph("1、引言")
    h1.runs[0].bold = True
    h1.runs[0].font.size = Pt(16)
    _set_outline(h1, 0)
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    h1._p.append(fld)
    template = tmp_path / "field.docx"
    document.save(str(template))

    with pytest.raises(OfficeTemplateFillError):
        fill_word_template_blocks(
            template,
            [WordTemplateBlock(kind="h1", text="2、概述")],
            "out.docx",
            workspace_path=str(tmp_path),
            anchors={"h1": 0},
        )


def test_refill_endpoint_delegates(tmp_path: Path) -> None:
    template = _build_template(tmp_path / "template.docx")

    response = refill_word_template_blocks_endpoint(
        WordTemplateRefillRequest(
            workspace_path=str(tmp_path),
            template_path=str(template),
            output_filename="api-out.docx",
            blocks=[{"kind": "body", "text": "接口生成的正文"}],
        )
    )

    assert response["ok"] is True
    assert response["inserted_blocks"] == 1
    assert _output_texts(tmp_path / "api-out.docx")[1] == "接口生成的正文"
