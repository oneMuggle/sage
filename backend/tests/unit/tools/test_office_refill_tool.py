"""P0 整块结构填充 Agent 工具测试。"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

from backend.tools.office_template_tool import OfficeRefillWordTemplateTool


def _set_outline(paragraph, level: int) -> None:
    pPr = paragraph._p.get_or_add_pPr()
    ol = OxmlElement("w:outlineLvl")
    ol.set(qn("w:val"), str(level))
    pPr.append(ol)


def _build_template(path: Path) -> Path:
    document = Document()
    h1 = document.add_paragraph()
    run = h1.add_run("1、引言")
    run.bold = True
    run.font.size = Pt(16)
    _set_outline(h1, 0)
    body = document.add_paragraph()
    run = body.add_run("旧正文")
    run.font.size = Pt(12)
    document.save(str(path))
    return path


def test_refill_tool_requires_blocks(tmp_path: Path) -> None:
    tool = OfficeRefillWordTemplateTool()
    result = tool.execute(file_path=str(tmp_path / "x.docx"), blocks=[])
    assert result.success is False
    assert result.error == "blocks_required"


def test_refill_tool_writes_refilled_copy(tmp_path: Path) -> None:
    template = _build_template(tmp_path / "template.docx")
    tool = OfficeRefillWordTemplateTool()

    result = tool.execute(
        file_path=str(template),
        blocks=[{"kind": "body", "text": "工具写入的正文"}],
    )

    assert result.success is True
    output = tmp_path / "template-refilled.docx"
    assert output.exists()
    document = Document(str(output))
    assert any("工具写入的正文" in p.text for p in document.paragraphs)
    assert result.content["inserted_blocks"] == 1


def test_refill_tool_honors_output_path(tmp_path: Path) -> None:
    template = _build_template(tmp_path / "template.docx")
    tool = OfficeRefillWordTemplateTool()

    result = tool.execute(
        file_path=str(template),
        blocks=[{"kind": "body", "text": "指定输出"}],
        output_path=str(tmp_path / "custom.docx"),
    )

    assert result.success is True
    assert (tmp_path / "custom.docx").exists()


def test_refill_tool_maps_service_error(tmp_path: Path) -> None:
    template = _build_template(tmp_path / "template.docx")
    tool = OfficeRefillWordTemplateTool()

    result = tool.execute(
        file_path=str(template),
        blocks=[{"kind": "h3", "text": "缺少 h3 块模板"}],
    )

    assert result.success is False
    assert "缺少块模板段落" in (result.error or "")
