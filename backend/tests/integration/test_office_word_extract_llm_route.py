"""Integration test for the use_llm extraction branch (M3b)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest
from docx import Document

import backend.api.office_word_audit_routes as routes
from backend.api.office_word_audit_routes import (
    WordRuleExtractRequest,
    extract_rulepack_endpoint,
)
from backend.office.word_rulepack_models import (
    WordRuleExtractionResult,
    WordRulePack,
    WordRuleSpec,
)


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


def test_extract_endpoint_uses_async_llm_branch(
    monkeypatch: pytest.MonkeyPatch, workspace: Path
) -> None:
    document = Document()
    document.add_paragraph("正文采用仿宋三号字。")
    path = workspace / "spec.docx"
    document.save(str(path))
    captured: Dict[str, Any] = {}

    async def fake_extract(*args: Any, **kwargs: Any) -> WordRuleExtractionResult:
        captured["args"] = args
        captured["kwargs"] = kwargs
        rule = WordRuleSpec(
            id="extracted/style.font",
            title="正文字体",
            kind="style.font",
            params={"style": "Normal", "font_east_asia": "仿宋"},
            source="spec.docx 第 1 段（LLM）",
        )
        return WordRuleExtractionResult(
            ok=True,
            source_path="spec.docx",
            file_type="spec",
            llm_used=True,
            pack=WordRulePack(id="llm-pack", name="LLM pack", rules=[rule]),
            candidates=[],
            conflicts=[],
            warnings=[],
            summary={"rules": 1, "candidates": 1, "conflicts": 0, "warnings": 0},
        )

    monkeypatch.setattr(routes, "extract_word_rules_async", fake_extract)

    result = extract_rulepack_endpoint(
        WordRuleExtractRequest(
            workspace_path=str(workspace),
            file_path=str(path),
            pack_id="llm-pack",
            use_llm=True,
        )
    )

    assert result.llm_used is True
    assert result.pack.id == "llm-pack"
    assert captured["kwargs"]["use_llm"] is True
    assert captured["kwargs"]["pack_id"] == "llm-pack"
