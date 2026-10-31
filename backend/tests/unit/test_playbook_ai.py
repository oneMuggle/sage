"""Unit tests for LLM-assisted playbook audit (2026-10-31)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.services.playbook_ai import audit_with_llm
from backend.services.playbook_library import get_builtin


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.responses.pop(0)


class FailingLLM:
    async def complete(self, prompt: str) -> str:
        raise RuntimeError("llm down")


def _project(root: Path) -> SimpleNamespace:
    return SimpleNamespace(id="p1", name="demo", path=str(root))


def _proposal_project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "01_开题").mkdir(parents=True)
    (root / "01_开题" / "开题报告.md").write_text(
        "这是一份与检查项无关的内容", encoding="utf-8"
    )
    return root


@pytest.mark.asyncio()
async def test_llm_content_check_can_pass_keyword_failure(tmp_path: Path) -> None:
    root = _proposal_project(tmp_path)
    client = FakeLLM([json.dumps({"pass": True, "reason": "包含研究问题"})])
    result = await audit_with_llm(
        _project(root), get_builtin("cn-research-grant"), llm_client=client
    )
    assert result.llm_available is True
    proposal = next(stage for stage in result.audit["stages"] if stage["id"] == "proposal")
    report = next(item for item in proposal["artifacts"] if item["id"] == "proposal_report")
    assert report["checks"][0]["status"] == "pass"
    assert report["checks"][0]["source"] == "llm"


@pytest.mark.asyncio()
async def test_ambiguous_stage_is_adjudicated(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    client = FakeLLM([json.dumps({"stage_id": "execution", "reason": "已有实施活动"})])
    result = await audit_with_llm(
        _project(root), get_builtin("cn-research-grant"), llm_client=client
    )
    assert result.audit["detected_stage"]["id"] == "execution"
    assert result.audit["detected_stage"]["source"] == "llm"
    assert result.llm_available is True


@pytest.mark.asyncio()
async def test_no_llm_keeps_deterministic_result(tmp_path: Path) -> None:
    root = _proposal_project(tmp_path)
    result = await audit_with_llm(
        _project(root), get_builtin("cn-research-grant"), use_llm=False
    )
    assert result.llm_available is False
    assert result.source == "deterministic"
    assert result.audit["stages"]


@pytest.mark.asyncio()
async def test_llm_failure_degrades_gracefully(tmp_path: Path) -> None:
    root = _proposal_project(tmp_path)
    result = await audit_with_llm(
        _project(root), get_builtin("cn-research-grant"), llm_client=FailingLLM()
    )
    assert result.llm_available is False
    assert result.audit["stages"]


def test_collect_text_reads_docx(tmp_path: Path) -> None:
    import docx

    root = tmp_path / "docx"
    root.mkdir()
    document = docx.Document()
    document.add_paragraph("研究问题与科学假设")
    document.save(str(root / "开题报告.docx"))

    from backend.services.playbook_ai import _collect_text

    text = _collect_text(root, ["开题报告.docx"])
    assert "研究问题与科学假设" in text
