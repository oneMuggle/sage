"""ProjectAnalysisAgent 单元测试（2026-10-27）。

覆盖:
- LLM 不可用 → 确定性降级报告
- LLM 调用异常 → 降级
- LLM 返回非法 JSON → 降级
- LLM 正常路径 → 解析规则 / 建议 / 草稿
- confidence / priority 钳位
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from backend.services.project_analysis_agent import (
    AnalysisReport,
    ProjectAnalysisAgent,
    SuggestedRule,
)
from backend.services.project_profiler import CodebaseProfile, GitStats

pytestmark = [pytest.mark.unit]


def _profile(**overrides) -> CodebaseProfile:
    """构造测试用画像。"""
    base = {
        "root": "/tmp/demo",
        "level1_type": "coding",
        "sub_type": "python_backend",
        "tech_stack": ["python", "fastapi", "pytest", "react"],
        "frameworks": ["fastapi", "react"],
        "test_frameworks": ["pytest"],
        "ci_workflows": [],
        "existing_rule_files": [],
        "lint_configs": ["ruff.toml"],
    }
    base.update(overrides)
    return CodebaseProfile(**base)


def _llm_returning(payload) -> AsyncMock:
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=payload)
    return llm


def _agent_without_llm() -> ProjectAnalysisAgent:
    """构造 LLM 不可用的 agent（跳过 settings 构建）。"""
    agent = ProjectAnalysisAgent(llm_client=_llm_returning("{}"))
    agent._llm = None
    return agent


# ── 降级路径 ────────────────────────────────────────────────────────────────


def test_agent_without_llm_is_unavailable() -> None:
    assert _agent_without_llm().available is False


@pytest.mark.asyncio
async def test_fallback_when_llm_unavailable() -> None:
    report = await _agent_without_llm().analyze(_profile())
    assert report.llm_available is False
    assert report.level1_type == "coding"
    assert report.sub_type == "python_backend"
    assert report.suggested_rules
    assert report.sage_md_draft
    assert report.governance_recommendations


@pytest.mark.asyncio
async def test_fallback_when_llm_raises() -> None:
    llm = AsyncMock()
    llm.complete = AsyncMock(side_effect=RuntimeError("network down"))
    agent = ProjectAnalysisAgent(llm_client=llm)
    report = await agent.analyze(_profile())
    assert report.llm_available is False
    assert report.suggested_rules


@pytest.mark.asyncio
async def test_fallback_when_llm_returns_invalid_json() -> None:
    agent = ProjectAnalysisAgent(llm_client=_llm_returning("not json at all"))
    report = await agent.analyze(_profile())
    assert report.llm_available is False
    assert report.suggested_rules


@pytest.mark.asyncio
async def test_fallback_rules_come_from_templates() -> None:
    report = await _agent_without_llm().analyze(_profile(tech_stack=["python"]))
    template_keys = {r.template_key for r in report.suggested_rules}
    assert "python_default" in template_keys
    for rule in report.suggested_rules:
        assert rule.content
        assert rule.reason


@pytest.mark.asyncio
async def test_fallback_recommends_ci_when_missing() -> None:
    report = await _agent_without_llm().analyze(_profile(ci_workflows=[]))
    assert any("CI" in rec for rec in report.governance_recommendations)


@pytest.mark.asyncio
async def test_fallback_stage_depends_on_commit_count() -> None:
    report = await _agent_without_llm().analyze(
        _profile(git_stats=GitStats(is_repo=True, commit_count=100))
    )
    assert report.stage_recommendation == "stabilization"


# ── LLM 正常路径 ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_response_parsed() -> None:
    payload = json.dumps(
        {
            "architecture_summary": "FastAPI 后端 + React 前端",
            "confidence": 0.8,
            "suggested_rules": [
                {
                    "template_key": "python_default",
                    "label": "Python 规范",
                    "reason": "检测到 pytest",
                    "confidence": 0.9,
                    "category": "coding_style",
                    "trigger_pattern": "*.py",
                    "priority": 7,
                }
            ],
            "governance_recommendations": ["补充 CI 门禁"],
            "stage_recommendation": "development",
            "sage_md_draft": "# 项目约定\n",
            "docs_refs": [
                {
                    "title": "质量门禁",
                    "reason": "前端项目",
                    "path": "docs/technical/15-quality-gates.md",
                }
            ],
        }
    )
    agent = ProjectAnalysisAgent(llm_client=_llm_returning(payload))
    report = await agent.analyze(_profile())
    assert report.llm_available is True
    assert report.architecture_summary == "FastAPI 后端 + React 前端"
    assert report.confidence == pytest.approx(0.8)
    assert len(report.suggested_rules) == 1
    assert report.suggested_rules[0].template_key == "python_default"
    assert report.suggested_rules[0].content  # 模板内容被填充
    assert report.stage_recommendation == "development"
    assert report.governance_recommendations == ["补充 CI 门禁"]
    assert report.docs_refs[0].path.endswith("15-quality-gates.md")


@pytest.mark.asyncio
async def test_llm_fenced_json_parsed() -> None:
    payload = "```json\n" + json.dumps({"architecture_summary": "OK"}) + "\n```"
    agent = ProjectAnalysisAgent(llm_client=_llm_returning(payload))
    report = await agent.analyze(_profile())
    assert report.llm_available is True
    assert report.architecture_summary == "OK"


@pytest.mark.asyncio
async def test_confidence_and_priority_clamped() -> None:
    payload = json.dumps(
        {
            "confidence": 5.0,
            "suggested_rules": [
                {
                    "template_key": "ai_custom",
                    "label": "X",
                    "content": "内容",
                    "confidence": -3.0,
                    "priority": 99,
                }
            ],
        }
    )
    agent = ProjectAnalysisAgent(llm_client=_llm_returning(payload))
    report = await agent.analyze(_profile())
    assert report.confidence == 1.0
    assert report.suggested_rules[0].confidence == 0.0
    assert report.suggested_rules[0].priority == 10


@pytest.mark.asyncio
async def test_invalid_stage_recommendation_dropped() -> None:
    payload = json.dumps({"stage_recommendation": "unknown_phase"})
    agent = ProjectAnalysisAgent(llm_client=_llm_returning(payload))
    report = await agent.analyze(_profile())
    assert report.stage_recommendation is None


# ── 数据结构 ────────────────────────────────────────────────────────────────


def test_suggested_rule_to_dict() -> None:
    rule = SuggestedRule(
        template_key="ai_custom",
        label="标签",
        reason="原因",
        confidence=0.5,
        category="security",
        content="正文",
        trigger_pattern="always",
        priority=5,
    )
    data = rule.to_dict()
    assert data["template_key"] == "ai_custom"
    assert data["trigger_pattern"] == "always"


def test_report_to_dict_shape() -> None:
    report = AnalysisReport(
        level1_type="coding",
        sub_type=None,
        confidence=0.5,
        tech_stack=["python"],
        architecture_summary="摘要",
        suggested_rules=[],
        governance_recommendations=[],
        stage_recommendation=None,
        sage_md_draft="",
        docs_refs=[],
        llm_available=False,
    )
    data = report.to_dict()
    assert data["llm_available"] is False
    assert data["tech_stack"] == ["python"]
    assert "suggested_rules" in data
    assert "docs_refs" in data
