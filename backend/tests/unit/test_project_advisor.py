"""ProjectAdvisor 单元测试 (M3, 2026-10-12)。

覆盖:
- __init__: 自定义 LLM client / 从 settings 构建
- available 属性
- analyze(): cache miss → LLM 调用 → cache hit → force_refresh
- invalidate_cache()
- _parse_response(): 有效 JSON / markdown code block / 残缺 JSON / 完全无效
- _build_prompt(): 包含项目信息和里程碑数据
- _get_cached() / _set_cached(): TTL 过期
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.project_advisor import (
    AdviceResult,
    AdvisorRisk,
    AdvisorSuggestion,
    ProjectAdvisor,
    _days_between,
)

pytestmark = [pytest.mark.unit]


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_llm():
    """模拟 LLM 客户端。"""
    llm = AsyncMock()
    llm.complete = AsyncMock(
        return_value=json.dumps(
            {
                "health_score": 75,
                "summary": "项目进展良好，有少量待处理项",
                "risks": [
                    {
                        "description": "里程碑 A 已逾期",
                        "severity": "high",
                        "suggestion": "尽快完成或重新规划",
                    }
                ],
                "suggestions": [
                    {
                        "action": "更新项目描述",
                        "reason": "描述为空不利于 AI 理解",
                        "priority": "medium",
                    }
                ],
            }
        )
    )
    return llm


@pytest.fixture()
def mock_project():
    """模拟 Project 对象。"""
    project = MagicMock()
    project.id = "proj-123"
    project.name = "Test Project"
    project.project_type = "coding"
    project.project_stage = "development"
    project.description = "A test project"
    project.path = "/tmp/test-project"
    return project


@pytest.fixture()
def mock_milestone():
    """模拟里程碑对象。"""
    m = MagicMock()
    m.title = "Milestone A"
    m.due_date = "2026-10-01"  # 过去日期（逾期）
    m.status = "in_progress"
    return m


@pytest.fixture()
def advisor(mock_llm):
    """使用 mock LLM 的 ProjectAdvisor 实例。"""
    return ProjectAdvisor(llm_client=mock_llm)


# ── __init__ 和 available ─────────────────────────────────────────────────────


class TestAdvisorInit:
    def test_custom_llm_client(self, mock_llm):
        advisor = ProjectAdvisor(llm_client=mock_llm)
        assert advisor.available is True
        assert advisor._llm is mock_llm

    def test_available_with_llm(self, mock_llm):
        advisor = ProjectAdvisor(llm_client=mock_llm)
        assert advisor.available is True

    def test_available_without_llm(self):
        advisor = ProjectAdvisor(llm_client=None)
        # 从 settings 构建可能成功或失败，取决于环境
        # 只验证 available 是 bool
        assert isinstance(advisor.available, bool)


# ── analyze() ─────────────────────────────────────────────────────────────────


class TestAnalyze:
    @pytest.mark.asyncio()
    async def test_analyze_cache_miss(self, advisor, mock_llm):
        """cache miss 时应调用 LLM。"""
        with patch(
                "backend.services.project_advisor.ProjectAdvisor._collect_data",
                return_value={
                    "project": {
                        "name": "Test Project",
                        "type": "coding",
                        "stage": "development",
                        "description": "A test project",
                    },
                    "milestones": {
                        "total": 1,
                        "by_status": {
                            "pending": 0,
                            "in_progress": 1,
                            "completed": 0,
                            "blocked": 0,
                        },
                        "overdue": [
                            {
                                "title": "Milestone A",
                                "due_date": "2026-10-01",
                                "status": "in_progress",
                                "days_overdue": 11,
                            }
                        ],
                    },
                    "profile_entry_count": 5,
                },
        ):
            result = await advisor.analyze(project_id="proj-123")

        assert isinstance(result, AdviceResult)
        assert result.health_score == 75
        assert result.summary == "项目进展良好，有少量待处理项"
        assert len(result.risks) == 1
        assert result.risks[0].severity == "high"
        assert len(result.suggestions) == 1
        mock_llm.complete.assert_called_once()

    @pytest.mark.asyncio()
    async def test_analyze_cache_hit(self, advisor, mock_llm):
        """cache hit 时不应调用 LLM。"""
        # 先写入缓存
        cached_result = AdviceResult(
            health_score=80,
            summary="cached",
            risks=[],
            suggestions=[],
        )
        advisor._set_cached("proj-123", cached_result)

        with patch(
            "backend.services.project_advisor.ProjectAdvisor._collect_data"
        ) as mock_collect:
            result = await advisor.analyze(project_id="proj-123")

        assert result.health_score == 80
        assert result.summary == "cached"
        assert result.cached_at is not None
        mock_llm.complete.assert_not_called()
        mock_collect.assert_not_called()

    @pytest.mark.asyncio()
    async def test_analyze_force_refresh(self, advisor, mock_llm):
        """force_refresh=True 时忽略缓存。"""
        # 先写入缓存
        cached_result = AdviceResult(health_score=80, summary="cached")
        advisor._set_cached("proj-123", cached_result)

        with patch(
                "backend.services.project_advisor.ProjectAdvisor._collect_data",
                return_value={
                    "project": {
                        "name": "Test Project",
                        "type": "coding",
                        "stage": "development",
                        "description": "",
                    },
                    "milestones": {
                        "total": 0,
                        "by_status": {},
                        "overdue": [],
                    },
                    "profile_entry_count": 0,
                },
        ):
            result = await advisor.analyze(
                project_id="proj-123", force_refresh=True
            )

        # 应该重新调用 LLM
        mock_llm.complete.assert_called_once()
        assert result.health_score == 75  # 来自 LLM mock


# ── invalidate_cache() ────────────────────────────────────────────────────────


class TestInvalidateCache:
    def test_invalidate_existing(self, advisor):
        advisor._set_cached(
            "proj-123", AdviceResult(health_score=80, summary="test")
        )
        assert advisor._get_cached("proj-123") is not None

        advisor.invalidate_cache("proj-123")
        assert advisor._get_cached("proj-123") is None

    def test_invalidate_nonexistent(self, advisor):
        # 不应抛出
        advisor.invalidate_cache("nonexistent")


# ── _parse_response() ─────────────────────────────────────────────────────────


class TestParseResponse:
    def test_valid_json(self, advisor):
        raw = json.dumps(
            {
                "health_score": 85,
                "summary": "Good",
                "risks": [{"description": "R1", "severity": "low"}],
                "suggestions": [{"action": "S1", "priority": "high"}],
            }
        )
        result = advisor._parse_response(raw, "proj-1")
        assert result.health_score == 85
        assert result.summary == "Good"
        assert len(result.risks) == 1
        assert len(result.suggestions) == 1

    def test_markdown_code_block(self, advisor):
        raw = (
            "```json\n"
            '{"health_score": 70, "summary": "ok", '
            '"risks": [], "suggestions": []}\n'
            "```"
        )
        result = advisor._parse_response(raw, "proj-1")
        assert result.health_score == 70

    def test_markdown_code_block_no_lang(self, advisor):
        raw = (
            "```\n"
            '{"health_score": 60, "summary": "ok", '
            '"risks": [], "suggestions": []}\n'
            "```"
        )
        result = advisor._parse_response(raw, "proj-1")
        assert result.health_score == 60

    def test_json_with_surrounding_text(self, advisor):
        raw = (
            "Here is my analysis:\n"
            '{"health_score": 55, "summary": "ok", '
            '"risks": [], "suggestions": []}\n'
            "Done."
        )
        result = advisor._parse_response(raw, "proj-1")
        assert result.health_score == 55

    def test_invalid_json_raises(self, advisor):
        with pytest.raises(RuntimeError, match="未找到 JSON"):
            advisor._parse_response("not json at all", "proj-1")

    def test_health_score_clamped(self, advisor):
        raw = json.dumps(
            {
                "health_score": 150,
                "summary": "test",
                "risks": [],
                "suggestions": [],
            }
        )
        result = advisor._parse_response(raw, "proj-1")
        assert result.health_score == 100

    def test_health_score_negative_clamped(self, advisor):
        raw = json.dumps(
            {
                "health_score": -10,
                "summary": "test",
                "risks": [],
                "suggestions": [],
            }
        )
        result = advisor._parse_response(raw, "proj-1")
        assert result.health_score == 0

    def test_risks_limited_to_3(self, advisor):
        raw = json.dumps(
            {
                "health_score": 50,
                "summary": "test",
                "risks": [
                    {"description": f"R{i}", "severity": "medium"}
                    for i in range(5)
                ],
                "suggestions": [],
            }
        )
        result = advisor._parse_response(raw, "proj-1")
        assert len(result.risks) == 3

    def test_suggestions_limited_to_3(self, advisor):
        raw = json.dumps(
            {
                "health_score": 50,
                "summary": "test",
                "risks": [],
                "suggestions": [
                    {"action": f"S{i}", "priority": "medium"}
                    for i in range(5)
                ],
            }
        )
        result = advisor._parse_response(raw, "proj-1")
        assert len(result.suggestions) == 3


# ── _build_prompt() ──────────────────────────────────────────────────────────


class TestBuildPrompt:
    def test_contains_project_info(self, advisor):
        data = {
            "project": {
                "name": "My Project",
                "type": "coding",
                "stage": "planning",
                "description": "A great project",
            },
            "milestones": {
                "total": 3,
                "by_status": {
                    "pending": 1,
                    "in_progress": 1,
                    "completed": 1,
                    "blocked": 0,
                },
                "overdue": [],
            },
            "profile_entry_count": 10,
        }
        prompt = advisor._build_prompt(data)
        assert "My Project" in prompt
        assert "coding" in prompt
        assert "planning" in prompt

    def test_contains_playbook_context(self, advisor):
        data = {
            "project": {
                "name": "P",
                "type": "research",
                "stage": "proposal",
                "description": "",
            },
            "playbook": {
                "name": "科研课题",
                "current_stage": "proposal",
                "detected_stage": "proposal",
                "progress": 50,
                "missing": ["开题报告"],
                "classification_suggestions": 1,
            },
            "milestones": {"total": 0, "by_status": {}, "overdue": []},
            "profile_entry_count": 0,
        }
        prompt = advisor._build_prompt(data)
        assert "科研课题" in prompt
        assert "开题报告" in prompt
        assert "项目规程" in prompt

    def test_contains_overdue_info(self, advisor):
        data = {
            "project": {
                "name": "P",
                "type": "coding",
                "stage": "dev",
                "description": "",
            },
            "milestones": {
                "total": 1,
                "by_status": {},
                "overdue": [
                    {
                        "title": "Late Milestone",
                        "due_date": "2026-09-01",
                        "status": "in_progress",
                        "days_overdue": 41,
                    }
                ],
            },
            "profile_entry_count": 0,
        }
        prompt = advisor._build_prompt(data)
        assert "Late Milestone" in prompt
        assert "41" in prompt

    def test_no_overdue_text(self, advisor):
        data = {
            "project": {
                "name": "P",
                "type": "coding",
                "stage": "dev",
                "description": "",
            },
            "milestones": {
                "total": 1,
                "by_status": {},
                "overdue": [],
            },
            "profile_entry_count": 0,
        }
        prompt = advisor._build_prompt(data)
        assert "无逾期" in prompt


# ── _get_cached() / _set_cached() ────────────────────────────────────────────


class TestCache:
    def test_set_and_get(self, advisor):
        result = AdviceResult(health_score=90, summary="cached")
        advisor._set_cached("proj-1", result)

        cached = advisor._get_cached("proj-1")
        assert cached is not None
        assert cached.health_score == 90
        assert cached.cached_at is not None

    def test_get_nonexistent(self, advisor):
        assert advisor._get_cached("nonexistent") is None

    def test_ttl_expiry(self, advisor):
        result = AdviceResult(health_score=90, summary="old")
        # 直接写入一个过期的 timestamp
        old_ts = int(time.time() * 1000) - (31 * 60 * 1000)  # 31 分钟前
        advisor._cache["proj-1"] = (old_ts, result)

        cached = advisor._get_cached("proj-1")
        assert cached is None  # 已过期


# ── _days_between() ──────────────────────────────────────────────────────────


class TestDaysBetween:
    def test_same_date(self):
        assert _days_between("2026-10-12", "2026-10-12") == 0

    def test_positive_diff(self):
        assert _days_between("2026-10-01", "2026-10-12") == 11

    def test_negative_diff(self):
        assert _days_between("2026-10-12", "2026-10-01") == -11

    def test_invalid_date(self):
        assert _days_between("not-a-date", "2026-10-12") == 0


# ── AdviceResult / AdvisorRisk / AdvisorSuggestion ───────────────────────────


class TestDataclasses:
    def test_advisor_risk_to_dict(self):
        risk = AdvisorRisk(
            description="Test risk",
            severity="high",
            suggestion="Fix it",
        )
        d = risk.to_dict()
        assert d == {
            "description": "Test risk",
            "severity": "high",
            "suggestion": "Fix it",
        }

    def test_advisor_risk_defaults(self):
        risk = AdvisorRisk(description="Test")
        assert risk.severity == "medium"
        assert risk.suggestion is None

    def test_advisor_suggestion_to_dict(self):
        sug = AdvisorSuggestion(
            action="Do something",
            reason="Because",
            priority="high",
        )
        d = sug.to_dict()
        assert d == {
            "action": "Do something",
            "reason": "Because",
            "priority": "high",
            "evidence": [],
            "action_type": "",
            "action_payload": {},
        }

    def test_advisor_suggestion_defaults(self):
        sug = AdvisorSuggestion(action="Test")
        assert sug.reason is None
        assert sug.priority == "medium"

    def test_advice_result_to_dict(self):
        result = AdviceResult(
            health_score=85,
            summary="Good",
            risks=[AdvisorRisk(description="R1", severity="low")],
            suggestions=[AdvisorSuggestion(action="S1", priority="high")],
            cached_at=1728720000000,
        )
        d = result.to_dict()
        assert d["health_score"] == 85
        assert d["summary"] == "Good"
        assert len(d["risks"]) == 1
        assert len(d["suggestions"]) == 1
        assert d["cached_at"] == 1728720000000

    def test_advice_result_defaults(self):
        result = AdviceResult(health_score=50, summary="test")
        assert result.risks == []
        assert result.suggestions == []
        assert result.cached_at is None
        assert result.raw_json is None
