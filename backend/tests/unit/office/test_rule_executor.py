from __future__ import annotations

from pathlib import Path
from typing import Any, List

import pytest

from backend.office.errors import OfficeParseError
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
