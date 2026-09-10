"""ConsolidationService 单元测试（Round 5: LLM 巡检建议）"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.skills.consolidator import ConsolidationService
from backend.skills.review_service import ReviewService

pytestmark = pytest.mark.unit


def _provider(text: str):
    provider = SimpleNamespace()
    provider.complete = AsyncMock(return_value=SimpleNamespace(text=text))
    return provider


SKILLS = [
    {"name": "deploy", "description": "部署", "when_to_use": "部署时", "usage_count": 3},
    {"name": "release", "description": "发布", "when_to_use": "发布时", "usage_count": 0},
    {"name": "cook", "description": "做菜", "when_to_use": "做菜时", "usage_count": 12},
]


class TestParseSuggestions:
    def test_valid_array(self):
        raw = '[{"type": "merge", "skill_names": ["deploy", "release"], "reason": "重叠"}]'
        out = ConsolidationService._parse_suggestions(raw)
        assert out == [
            {"type": "merge", "skill_names": ["deploy", "release"], "reason": "重叠"}
        ]

    def test_fenced_and_prose_tolerated(self):
        raw = '巡检结果：\n```json\n[{"type": "revise", "skill_names": ["cook"], "reason": "描述含糊"}]\n```'
        out = ConsolidationService._parse_suggestions(raw)
        assert out[0]["type"] == "revise"

    def test_garbage_returns_empty(self):
        assert ConsolidationService._parse_suggestions("不是 JSON") == []
        assert ConsolidationService._parse_suggestions('{"a": 1}') == []

    def test_pinned_excluded_from_archive(self):
        raw = (
            '[{"type": "archive", "skill_names": ["deploy", "cook"], "reason": "过时"},'
            '{"type": "merge", "skill_names": ["deploy", "cook"], "reason": "重叠"}]'
        )
        out = ConsolidationService._parse_suggestions(raw, pinned={"deploy"})
        # archive 建议剔除 pinned 成员后仍非空 → 保留；merge 不受 pin 影响
        assert out[0]["skill_names"] == ["cook"]
        assert out[1]["skill_names"] == ["deploy", "cook"]

    def test_archive_all_pinned_dropped(self):
        raw = '[{"type": "archive", "skill_names": ["deploy"], "reason": "过时"}]'
        out = ConsolidationService._parse_suggestions(raw, pinned={"deploy"})
        assert out == []


class TestScan:
    @pytest.mark.asyncio()
    async def test_scan_returns_normalized_suggestions(self):
        svc = ConsolidationService(
            _provider('[{"type": "archive", "skill_names": ["release"], "reason": "零使用"}]')
        )
        out = await svc.scan(SKILLS)
        assert out == [
            {"type": "archive", "skill_names": ["release"], "reason": "零使用"}
        ]

    @pytest.mark.asyncio()
    async def test_llm_failure_returns_empty(self):
        provider = SimpleNamespace()
        provider.complete = AsyncMock(side_effect=RuntimeError("down"))
        svc = ConsolidationService(provider)
        assert await svc.scan(SKILLS) == []

    @pytest.mark.asyncio()
    async def test_empty_skills_skips_llm(self):
        provider = SimpleNamespace()
        provider.complete = AsyncMock()
        svc = ConsolidationService(provider)
        assert await svc.scan([]) == []
        provider.complete.assert_not_awaited()


class TestFactory:
    def test_from_review_service_none_when_unwired(self):
        assert ConsolidationService.from_review_service(None) is None

    def test_from_review_service_reuses_provider(self):
        svc_review = ReviewService(_provider("x"))
        got = ConsolidationService.from_review_service(svc_review)
        assert got is not None
        assert got.llm_provider is svc_review.llm_provider
