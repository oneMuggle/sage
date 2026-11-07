"""Unit tests for playbook document import service (2026-11-03).

Covers:
- Deterministic fallback extraction (stages, artifacts, rules)
- LLM success path (FakeLLM)
- LLM failure fallback
- DocumentImportResult.to_dict()
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Union

import pytest

from backend.services.playbook_document_import import (
    DocumentImportResult,
    _build_deterministic_playbook,
    _extract_artifacts_from_text,
    _extract_rules_from_text,
    _extract_stages_from_text,
    import_playbook_from_document,
)

pytestmark = pytest.mark.unit


class FakeLLM:
    def __init__(self, payload: Union[str, Exception]) -> None:
        self.payload = payload
        self.prompts: List[str] = []

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


# ---------------------------------------------------------------------------
# Deterministic extraction helpers
# ---------------------------------------------------------------------------

class TestExtractStages:
    """_extract_stages_from_text 单元测试"""

    def test_numbered_headings(self):
        text = "# 1. 需求分析\n# 2. 设计\n# 3. 实施"
        stages = _extract_stages_from_text(text)
        assert len(stages) == 3
        assert stages[0]["label"] == "需求分析"
        assert stages[0]["order"] == 1
        assert stages[2]["label"] == "实施"
        assert stages[2]["order"] == 3

    def test_chinese_phase_keyword(self):
        text = "第一阶段：立项\n第二阶段：验收"
        stages = _extract_stages_from_text(text)
        assert len(stages) == 2
        assert stages[0]["label"] == "立项"

    def test_phase_english_keyword(self):
        text = "Phase 1: Planning\nPhase 2: Execution"
        stages = _extract_stages_from_text(text)
        assert len(stages) == 2
        assert stages[0]["label"] == "Planning"

    def test_caps_at_8_stages(self):
        text = "\n".join(f"# {i}. Stage {i}" for i in range(1, 15))
        stages = _extract_stages_from_text(text)
        assert len(stages) == 8

    def test_empty_text(self):
        assert _extract_stages_from_text("") == []


class TestExtractArtifacts:
    """_extract_artifacts_from_text 单元测试"""

    def test_bullet_list_after_keyword(self):
        text = "产物\n- 需求文档\n- 设计规格\n- 测试报告"
        artifacts = _extract_artifacts_from_text(text)
        assert len(artifacts) == 3
        assert artifacts[0]["label"] == "需求文档"
        assert artifacts[0]["required"] is True
        assert artifacts[0]["match"]["min_count"] == 1

    def test_dash_deliverable_keyword(self):
        text = "交付物:\n1. API 文档\n2. 部署手册"
        artifacts = _extract_artifacts_from_text(text)
        assert len(artifacts) == 2

    def test_empty_text(self):
        assert _extract_artifacts_from_text("") == []


class TestExtractRules:
    """_extract_rules_from_text 单元测试"""

    def test_rule_section_bullets(self):
        text = "规则\n- 所有代码必须有单元测试\n- 禁止硬编码密钥"
        rules = _extract_rules_from_text(text)
        assert len(rules) == 2
        assert rules[0]["content"] == "所有代码必须有单元测试"
        assert rules[0]["category"] == "project"

    def test_requirement_section(self):
        text = "要求\n- 必须通过 CI\n- 必须有代码审查"
        rules = _extract_rules_from_text(text)
        assert len(rules) == 2

    def test_empty_text(self):
        assert _extract_rules_from_text("") == []


class TestBuildDeterministicPlaybook:
    """_build_deterministic_playbook 单元测试"""

    def test_basic_structure(self):
        text = "# 1. 规划\n# 2. 执行\n产物\n- 规划书\n- 进度报告"
        playbook = _build_deterministic_playbook(text, "test.md")
        assert playbook["schema_version"] == "1.0"
        assert playbook["name"] == "test"
        assert playbook["meta"]["source"] == "document_import"
        assert playbook["meta"]["source_doc"] == "test.md"
        assert len(playbook["stages"]) == 2

    def test_no_stages_fallback(self):
        text = "产物\n- 文档A\n- 文档B"
        playbook = _build_deterministic_playbook(text, "plain.md")
        assert len(playbook["stages"]) == 1
        assert playbook["stages"][0]["label"] == "实施"

    def test_filename_without_extension(self):
        playbook = _build_deterministic_playbook("", "MyProject")
        assert playbook["name"] == "MyProject"

    def test_long_filename_truncated(self):
        long_name = "x" * 300 + ".md"
        playbook = _build_deterministic_playbook("", long_name)
        assert len(playbook["meta"]["source_doc"]) <= 256


# ---------------------------------------------------------------------------
# Service-level tests
# ---------------------------------------------------------------------------

class TestImportPlaybookFromDocument:
    """import_playbook_from_document 集成测试"""

    @pytest.mark.asyncio()
    async def test_deterministic_fallback_when_no_llm(self, tmp_path: Path):
        md_file = tmp_path / "spec.md"
        md_file.write_text("# 1. 需求\n# 2. 开发\n产物\n- 设计文档", encoding="utf-8")

        result = await import_playbook_from_document(
            md_file, "spec.md", use_llm=False
        )

        assert isinstance(result, DocumentImportResult)
        assert result.llm_available is False
        assert result.source == "deterministic"
        assert result.source_doc == "spec.md"
        assert len(result.playbook["stages"]) >= 1

    @pytest.mark.asyncio()
    async def test_llm_success_path(self, tmp_path: Path):
        md_file = tmp_path / "llm_spec.md"
        md_file.write_text("some content", encoding="utf-8")

        llm_response = """
{
  "rationale": "AI 生成",
  "playbook": {
    "schema_version": "1.0",
    "id": "llm-test",
    "name": "LLM Playbook",
    "description": "test",
    "applies_to": {"project_types": [], "sub_types": []},
    "directory_layout": [],
    "stages": [
      {"id": "stage-1", "label": "阶段一", "order": 1, "objective": "目标",
       "artifacts": [], "exit_criteria": [], "rules": [], "recommended_milestones": []}
    ],
    "global_rules": [],
    "todos": [],
    "ai_guidance": {},
    "meta": {}
  }
}
"""
        fake_llm = FakeLLM(llm_response)

        result = await import_playbook_from_document(
            md_file, "llm_spec.md", use_llm=True, llm_client=fake_llm
        )

        assert result.llm_available is True
        assert result.source == "llm"
        assert result.rationale == "AI 生成"
        assert len(result.playbook["stages"]) == 1

    @pytest.mark.asyncio()
    async def test_llm_failure_fallback(self, tmp_path: Path):
        md_file = tmp_path / "fail_spec.md"
        md_file.write_text("content", encoding="utf-8")

        fake_llm = FakeLLM(RuntimeError("LLM down"))

        result = await import_playbook_from_document(
            md_file, "fail_spec.md", use_llm=True, llm_client=fake_llm
        )

        assert result.llm_available is False
        assert result.source == "deterministic"
        assert "回退" in result.rationale or "fallback" in result.rationale.lower()

    @pytest.mark.asyncio()
    async def test_empty_document(self, tmp_path: Path):
        md_file = tmp_path / "empty.md"
        md_file.write_text("", encoding="utf-8")

        result = await import_playbook_from_document(
            md_file, "empty.md", use_llm=False
        )

        assert result.source == "deterministic"
        assert len(result.playbook["stages"]) >= 1

    def test_to_dict_roundtrip(self):
        result = DocumentImportResult(
            playbook={"id": "test"},
            source_doc="doc.md",
            rationale="test rationale",
            llm_available=True,
            source="llm",
        )
        d = result.to_dict()
        assert d["playbook"] == {"id": "test"}
        assert d["source_doc"] == "doc.md"
        assert d["rationale"] == "test rationale"
        assert d["llm_available"] is True
        assert d["source"] == "llm"
