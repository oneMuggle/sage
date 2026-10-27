"""ProjectRuleGenerator 单元测试（2026-10-27）。

覆盖:
- 模板规则产出
- 专属规则（LLM 路径 / 降级路径）
- 与已有约束去重
- 里程碑推荐
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from backend.services.project_analysis_agent import AnalysisReport, SuggestedRule
from backend.services.project_profiler import CodebaseProfile
from backend.services.project_rule_generator import (
    SOURCE_AI_CUSTOM,
    SOURCE_TEMPLATE,
    ProjectRuleGenerator,
)

pytestmark = [pytest.mark.unit]


def _profile(**overrides) -> CodebaseProfile:
    base = {
        "root": "/tmp/demo",
        "level1_type": "coding",
        "sub_type": "python_backend",
        "tech_stack": ["python", "pytest"],
        "frameworks": [],
        "test_frameworks": ["pytest"],
        "ci_workflows": [],
        "existing_rule_files": [],
        "lint_configs": [],
    }
    base.update(overrides)
    return CodebaseProfile(**base)


def _report(**overrides) -> AnalysisReport:
    base = {
        "level1_type": "coding",
        "sub_type": "python_backend",
        "confidence": 0.7,
        "tech_stack": ["python"],
        "architecture_summary": "摘要",
        "suggested_rules": [],
        "governance_recommendations": [],
        "stage_recommendation": "development",
        "sage_md_draft": "",
        "docs_refs": [],
        "llm_available": True,
    }
    base.update(overrides)
    return AnalysisReport(**base)


def _llm_returning(payload) -> AsyncMock:
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=payload)
    return llm


def _agent_without_llm() -> ProjectRuleGenerator:
    agent = ProjectRuleGenerator(llm_client=_llm_returning("{}"))
    agent._llm = None
    return agent


# ── 模板规则 ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio()
async def test_template_rules_emitted() -> None:
    report = _report(
        suggested_rules=[
            SuggestedRule(
                template_key="python_default",
                label="Python 规范",
                reason="检测到 pytest",
                confidence=0.8,
                category="coding_style",
                content="使用双引号字符串",
                trigger_pattern="*.py",
                priority=5,
            )
        ]
    )
    result = await _agent_without_llm().generate(_profile(), report)
    template_rules = [r for r in result.rules if r.source == SOURCE_TEMPLATE]
    assert len(template_rules) == 1
    assert template_rules[0].template_key == "python_default"
    assert template_rules[0].content == "使用双引号字符串"


@pytest.mark.asyncio()
async def test_ai_custom_template_key_skipped_in_template_pass() -> None:
    report = _report(
        suggested_rules=[
            SuggestedRule(
                template_key="ai_custom",
                label="自定义",
                reason="",
                confidence=0.5,
                category="security",
                content="自定义内容",
                trigger_pattern="always",
                priority=5,
            )
        ]
    )
    result = await _agent_without_llm().generate(_profile(), report)
    assert not [r for r in result.rules if r.source == SOURCE_TEMPLATE]


# ── 去重 ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio()
async def test_duplicate_with_existing_content_skipped() -> None:
    report = _report(
        suggested_rules=[
            SuggestedRule(
                template_key="python_default",
                label="Python 规范",
                reason="",
                confidence=0.8,
                category="coding_style",
                content="使用双引号字符串",
                trigger_pattern="*.py",
                priority=5,
            )
        ]
    )
    result = await _agent_without_llm().generate(
        _profile(), report, existing_contents=["使用双引号字符串"]
    )
    assert not [r for r in result.rules if r.source == SOURCE_TEMPLATE]
    assert result.skipped_duplicates == 1


@pytest.mark.asyncio()
async def test_duplicate_within_result_skipped() -> None:
    """两条内容相同的模板规则只保留一条。"""
    rule = SuggestedRule(
        template_key="python_default",
        label="Python 规范",
        reason="",
        confidence=0.8,
        category="coding_style",
        content="使用双引号字符串",
        trigger_pattern="*.py",
        priority=5,
    )
    report = _report(suggested_rules=[rule, rule])
    result = await _agent_without_llm().generate(_profile(), report)
    assert len([r for r in result.rules if r.source == SOURCE_TEMPLATE]) == 1
    assert result.skipped_duplicates == 1


@pytest.mark.asyncio()
async def test_whitespace_normalized_dedup() -> None:
    report = _report(
        suggested_rules=[
            SuggestedRule(
                template_key="python_default",
                label="X",
                reason="",
                confidence=0.8,
                category="coding_style",
                content="使用双引号字符串",
                trigger_pattern="*.py",
                priority=5,
            )
        ]
    )
    result = await _agent_without_llm().generate(
        _profile(), report, existing_contents=["  使用双引号字符串  "]
    )
    assert not [r for r in result.rules if r.source == SOURCE_TEMPLATE]


# ── 专属规则 ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio()
async def test_custom_rules_from_llm() -> None:
    payload = json.dumps(
        {
            "custom_rules": [
                {
                    "category": "security",
                    "content": "禁止在源码中硬编码数据库口令",
                    "trigger_pattern": "*.py",
                    "priority": 9,
                    "reason": "源码中出现配置读取",
                }
            ]
        }
    )
    agent = ProjectRuleGenerator(llm_client=_llm_returning(payload))
    result = await agent.generate(_profile(), _report())
    assert result.llm_available is True
    custom = [r for r in result.rules if r.source == SOURCE_AI_CUSTOM]
    assert len(custom) == 1
    assert custom[0].content == "禁止在源码中硬编码数据库口令"
    assert custom[0].priority == 9


@pytest.mark.asyncio()
async def test_custom_rules_fallback_when_llm_errors() -> None:
    llm = AsyncMock()
    llm.complete = AsyncMock(side_effect=RuntimeError("boom"))
    agent = ProjectRuleGenerator(llm_client=llm)
    result = await agent.generate(_profile(), _report())
    assert result.llm_available is False
    assert [r for r in result.rules if r.source == SOURCE_AI_CUSTOM]


@pytest.mark.asyncio()
async def test_custom_rules_fallback_when_llm_unavailable() -> None:
    result = await _agent_without_llm().generate(_profile(), _report())
    assert result.llm_available is False
    custom = [r for r in result.rules if r.source == SOURCE_AI_CUSTOM]
    assert custom
    assert all(r.content for r in custom)


@pytest.mark.asyncio()
async def test_heuristic_custom_rules_follow_tech_stack() -> None:
    result = await _agent_without_llm().generate(
        _profile(tech_stack=["python", "pytest"], lint_configs=["ruff.toml"]),
        _report(),
    )
    contents = " ".join(r.content for r in result.rules)
    assert "Python" in contents
    assert "ruff.toml" in contents


# ── 里程碑 ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio()
async def test_milestones_from_blueprint() -> None:
    result = await _agent_without_llm().generate(_profile(), _report())
    assert result.milestones
    assert all("title" in m for m in result.milestones)


@pytest.mark.asyncio()
async def test_milestones_empty_for_unknown_type() -> None:
    result = await _agent_without_llm().generate(
        _profile(), _report(level1_type="unknown_type")
    )
    assert result.milestones == []


def test_result_to_dict_shape() -> None:
    from backend.services.project_rule_generator import RuleDraft, RuleGenerationResult

    result = RuleGenerationResult(
        rules=[
            RuleDraft(
                category="coding_style",
                content="正文",
                trigger_pattern="always",
                priority=5,
                source=SOURCE_TEMPLATE,
                template_key="python_default",
                reason="原因",
            )
        ],
        milestones=[{"title": "M1"}],
        llm_available=False,
        skipped_duplicates=2,
    )
    data = result.to_dict()
    assert data["llm_available"] is False
    assert data["skipped_duplicates"] == 2
    assert data["rules"][0]["template_key"] == "python_default"
    assert data["milestones"] == [{"title": "M1"}]
