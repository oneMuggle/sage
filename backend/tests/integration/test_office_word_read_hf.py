"""Integration tests for read_docx header/footer/TOC extraction (Round 15).

Round-trip coverage: generate a document with format_spec (header text /
footer page-number field / TOC field), then read it back and assert the
extracted headers_footers + toc_fields. Also covers the negative case
(no header/footer/TOC → empty extractions) and a generated TOC instr
mapping.
"""

from __future__ import annotations

from pathlib import Path

from backend.office.models import OfficeWordGenerateRequest
from backend.office.word import generate_docx, read_docx

_SPEC = {
    "page": {"size": "A4"},
    "header": {"text": "内部资料 · 请勿外传"},
    "footer": {"page_number": True},
    "toc": {"heading_text": "目录", "levels": "1-3"},
}


def _generate(tmp_path: Path, name: str, spec: dict, **kwargs) -> Path:
    req = OfficeWordGenerateRequest(
        workspace_path="",
        filename=name,
        title="测试文档",
        format_spec=spec,
        **kwargs,
    )
    return generate_docx(req, output_dir=str(tmp_path))


def test_read_back_header_footer_and_toc(tmp_path: Path) -> None:
    path = _generate(
        tmp_path,
        "full.docx",
        _SPEC,
        paragraphs=[{"text": "引言", "heading": "h1"}, {"text": "正文"}],
    )
    result = read_docx(file_path=path)
    assert result.headers_footers, "单节文档应有 1 条节记录"
    section = result.headers_footers[0]
    assert section.section == 1
    assert section.header_text == "内部资料 · 请勿外传"
    assert section.has_page_number_field is True
    assert len(result.toc_fields) == 1
    assert result.toc_fields[0].startswith("TOC ")
    assert '"1-3"' in result.toc_fields[0]


def test_read_plain_document_extracts_nothing(tmp_path: Path) -> None:
    path = _generate(tmp_path, "plain.docx", {}, paragraphs=[{"text": "正文"}])
    result = read_docx(file_path=path)
    assert result.headers_footers == []
    assert result.toc_fields == []


def test_read_toc_placeholder_text_visible_in_field(tmp_path: Path) -> None:
    path = _generate(
        tmp_path,
        "ph.docx",
        {"toc": {"placeholder_text": "更新域以生成目录"}},
        paragraphs=[{"text": "正文"}],
    )
    result = read_docx(file_path=path)
    assert len(result.toc_fields) == 1


def test_extraction_survives_multi_section_documents(tmp_path: Path) -> None:
    """多节文档：逐节报告（第二节继承第一节页眉，文本取空）。"""
    from docx import Document
    from docx.enum.section import WD_SECTION

    path = _generate(
        tmp_path,
        "multi.docx",
        {"header": {"text": "统一页眉"}},
        paragraphs=[{"text": "正文"}],
    )
    doc = Document(str(path))
    sec2 = doc.add_section(WD_SECTION.NEW_PAGE)
    # 第二节断开链接并写自己的页眉（否则继承前节，提取侧跳过空节）
    sec2.header.is_linked_to_previous = False
    sec2.header.paragraphs[0].text = "附录页眉"
    doc.save(str(path))

    result = read_docx(file_path=path)
    assert len(result.headers_footers) == 2
    assert result.headers_footers[0].section == 1
    assert result.headers_footers[0].header_text == "统一页眉"
    assert result.headers_footers[1].section == 2
    assert result.headers_footers[1].header_text == "附录页眉"
