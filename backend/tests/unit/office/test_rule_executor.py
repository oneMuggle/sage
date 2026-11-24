from __future__ import annotations

from pathlib import Path
from typing import Any, List

import pytest

from backend.office.errors import OfficeLLMError, OfficeParseError
from backend.office.rule_executor import (
    DocumentBlock,
    extract_blocks,
    run_audit,
    select_blocks,
)
from backend.office.rule_models import Rule


class _FakeClient:
    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.prompts: List[str] = []

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.payload


@pytest.fixture()
def docx_path(tmp_path: Path) -> Path:
    from docx import Document as DocxDocument

    document = DocxDocument()
    document.add_heading("第一章 总则", level=1)
    document.add_paragraph("正文应当使用宋体。")
    document.add_paragraph("这一行包含违禁词：待定。")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "表格内容"
    table.cell(0, 1).text = "待定"
    path = tmp_path / "sample.docx"
    document.save(str(path))
    return path


@pytest.fixture()
def xlsx_path(tmp_path: Path) -> Path:
    from openpyxl import Workbook

    workbook = Workbook()
    summary = workbook.active
    summary.title = "汇总"
    summary.append(["名称", "状态"])
    summary.append(["方案A", "待定"])
    summary.append([None, None])
    details = workbook.create_sheet("明细")
    details["A1"] = "干净的正文"
    path = tmp_path / "sample.xlsx"
    workbook.save(str(path))
    return path


@pytest.fixture()
def pptx_path(tmp_path: Path) -> Path:
    from pptx import Presentation
    from pptx.util import Inches

    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    slide.shapes.title.text = "页面标题"
    box = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(4), Inches(1))
    box.text_frame.text = "正文包含待定"
    table_shape = slide.shapes.add_table(1, 2, Inches(1), Inches(4), Inches(6), Inches(1))
    table_shape.table.cell(0, 0).text = "表格单元"
    table_shape.table.cell(0, 1).text = "待定"

    blank = presentation.slides.add_slide(presentation.slide_layouts[6])
    box2 = blank.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
    box2.text_frame.text = "第二页无标题正文"
    path = tmp_path / "sample.pptx"
    presentation.save(str(path))
    return path


def _rule(**overrides: Any) -> Rule:
    payload = {
        "id": "rule-1",
        "name": "禁用待定",
        "type": "terminology",
        "severity": "warning",
        "scope": "body",
        "check_mode": "regex",
        "pattern": "待定",
        "group_id": "group-1",
    }
    payload.update(overrides)
    return Rule(**payload)


def test_extract_blocks_classifies_and_labels(docx_path: Path) -> None:
    blocks = extract_blocks(docx_path)
    assert [block.kind for block in blocks] == ["heading", "body", "body", "table"]
    assert blocks[0].label == "第 1 段"
    assert blocks[1].index == 1
    assert blocks[3].label == "表格 1"
    assert "待定" in blocks[3].text


def test_select_blocks_scope() -> None:
    blocks = [
        DocumentBlock(index=0, kind="heading", text="h", label="第 1 段"),
        DocumentBlock(index=1, kind="body", text="b", label="第 2 段"),
        DocumentBlock(index=2, kind="table", text="t", label="表格 1"),
    ]
    assert select_blocks(blocks, "full") == blocks
    assert [block.kind for block in select_blocks(blocks, "body")] == ["body"]
    assert select_blocks(blocks, "caption") == []


async def test_regex_rule_honours_scope(docx_path: Path) -> None:
    result = await run_audit([_rule()], docx_path)
    assert result.warning_count == 1
    assert result.error_count == 0
    assert result.findings[0].rule_id == "rule-1"
    assert result.findings[0].location == "第 3 段"


async def test_regex_rule_invalid_pattern_raises(docx_path: Path) -> None:
    with pytest.raises(OfficeParseError):
        await run_audit([_rule(pattern="[unclosed")], docx_path)


async def test_ai_rule_uses_llm(docx_path: Path) -> None:
    client = _FakeClient(
        '[{"rule_id":"rule-ai","block_index":2,"message":"出现占位词","suggestion":"改为具体内容"}]'
    )
    rule = _rule(id="rule-ai", check_mode="ai", pattern=None, severity="error", scope="full")
    result = await run_audit([rule], docx_path, llm_client=client)
    assert result.error_count == 1
    assert result.findings[0].location == "第 3 段"
    assert result.findings[0].message == "出现占位词"
    assert client.prompts
    assert "rule-ai" in client.prompts[0]


async def test_ai_rule_without_client_raises(docx_path: Path) -> None:
    rule = _rule(id="rule-ai", check_mode="ai", pattern=None)
    with pytest.raises(OfficeParseError):
        await run_audit([rule], docx_path)


async def test_ai_rule_ignores_non_int_block_index(docx_path: Path) -> None:
    client = _FakeClient('[{"rule_id":"rule-ai","block_index":[0],"message":"x"}]')
    rule = _rule(id="rule-ai", check_mode="ai", pattern=None, scope="full")
    result = await run_audit([rule], docx_path, llm_client=client)
    assert result.findings == []


async def test_ai_rule_with_provider_failure_raises_office_llm_error(docx_path: Path) -> None:
    class _BrokenClient:
        async def complete(self, prompt: str) -> str:
            raise RuntimeError("provider down")

    rule = _rule(id="rule-ai", check_mode="ai", pattern=None, scope="full")
    with pytest.raises(OfficeLLMError, match="LLM 调用失败"):
        await run_audit([rule], docx_path, llm_client=_BrokenClient())


async def test_ai_audit_caps_blocks_and_llm_calls(tmp_path: Path) -> None:
    from docx import Document as DocxDocument

    document = DocxDocument()
    for index in range(500):
        document.add_paragraph(f"段落 {index}")
    path = tmp_path / "long.docx"
    document.save(str(path))

    client = _FakeClient("[]")
    rule = _rule(id="rule-ai", check_mode="ai", pattern=None, scope="full")
    result = await run_audit([rule], path, llm_client=client)

    assert result.findings == []
    # 400-block cap / 40-block batches = 10 calls, never 500/40 + remainder.
    assert len(client.prompts) == 10
    assert len(client.prompts) <= 10


def test_extract_blocks_xlsx_labels_sheets_and_rows(xlsx_path: Path) -> None:
    blocks = extract_blocks(xlsx_path)
    assert [(block.kind, block.label) for block in blocks] == [
        ("heading", "工作表「汇总」"),
        ("table", "工作表「汇总」第 1 行"),
        ("table", "工作表「汇总」第 2 行"),
        ("heading", "工作表「明细」"),
        ("table", "工作表「明细」第 1 行"),
    ]
    assert blocks[2].text == "方案A | 待定"


async def test_xlsx_audit_scope_and_anchor(xlsx_path: Path) -> None:
    table_hit = await run_audit([_rule(scope="table")], xlsx_path)
    assert table_hit.warning_count == 1
    assert table_hit.findings[0].location == "工作表「汇总」第 2 行"

    heading_hit = await run_audit(
        [_rule(id="rule-heading", scope="heading", pattern="汇总")], xlsx_path
    )
    assert [item.location for item in heading_hit.findings] == ["工作表「汇总」"]

    body_hit = await run_audit([_rule(scope="body")], xlsx_path)
    assert body_hit.findings == []


def test_extract_blocks_xlsx_caps_rows(tmp_path: Path) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    for index in range(600):
        sheet.append([f"行{index}"])
    path = tmp_path / "long.xlsx"
    workbook.save(str(path))

    blocks = extract_blocks(path)
    assert sum(1 for block in blocks if block.kind == "table") == 500


def test_extract_blocks_pptx_slides(pptx_path: Path) -> None:
    blocks = extract_blocks(pptx_path)
    assert [(block.kind, block.label) for block in blocks] == [
        ("heading", "幻灯片 1 标题"),
        ("body", "幻灯片 1 正文"),
        ("table", "幻灯片 1 表格 1"),
        ("body", "幻灯片 2 正文"),
    ]
    assert blocks[2].text == "表格单元 | 待定"


async def test_pptx_audit_scope_and_anchor(pptx_path: Path) -> None:
    body_hit = await run_audit([_rule(scope="body")], pptx_path)
    assert [item.location for item in body_hit.findings] == ["幻灯片 1 正文"]

    table_hit = await run_audit([_rule(scope="table")], pptx_path)
    assert [item.location for item in table_hit.findings] == ["幻灯片 1 表格 1"]

    heading_hit = await run_audit(
        [_rule(id="rule-heading", scope="heading", pattern="标题")], pptx_path
    )
    assert [item.location for item in heading_hit.findings] == ["幻灯片 1 标题"]


def test_extract_blocks_rejects_unsupported_suffix(tmp_path: Path) -> None:
    path = tmp_path / "sample.pdf"
    path.write_bytes(b"%PDF-1.4")
    with pytest.raises(OfficeParseError, match="仅支持"):
        extract_blocks(path)
