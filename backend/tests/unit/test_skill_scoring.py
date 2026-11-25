"""SkillScoringService 单元测试。"""

from __future__ import annotations

import time

import pytest

from backend.skills.scoring import (
    SkillScore,
    SkillScoringService,
    _compute_description_quality,
    _compute_freshness,
    _classify_tier,
    get_scoring_service,
    reset_scoring_service,
)


class TestComputeFreshness:
    """新鲜度计算测试。"""

    def test_never_used(self):
        assert _compute_freshness(None, 1000) == 0.0

    def test_zero_timestamp(self):
        assert _compute_freshness(0, 1000) == 0.0

    def test_just_used(self):
        now = int(time.time() * 1000)
        score = _compute_freshness(now, now)
        assert score == pytest.approx(100.0)

    def test_one_day_ago(self):
        now = int(time.time() * 1000)
        one_day_ago = now - 24 * 60 * 60 * 1000
        score = _compute_freshness(one_day_ago, now)
        assert 80 < score < 100

    def test_fourteen_days_ago(self):
        now = int(time.time() * 1000)
        two_weeks_ago = now - 14 * 24 * 60 * 60 * 1000
        score = _compute_freshness(two_weeks_ago, now)
        assert 45 < score < 55  # 半衰期 14 天

    def test_sixty_days_ago(self):
        now = int(time.time() * 1000)
        two_months_ago = now - 60 * 24 * 60 * 60 * 1000
        score = _compute_freshness(two_months_ago, now)
        assert score < 15


class TestComputeDescriptionQuality:
    """描述质量评估测试。"""

    def test_full_quality(self):
        desc = "Search and analyze academic papers and literature"
        when = "When the user needs to find research papers or review literature"
        score = _compute_description_quality(desc, when)
        assert score >= 80

    def test_short_description(self):
        score = _compute_description_quality("search", "when needed")
        assert score < 50

    def test_empty(self):
        assert _compute_description_quality("", "") == 0.0

    def test_chinese_with_action_words(self):
        desc = "搜索和分析学术论文及文献"
        when = "当用户需要查找研究论文或回顾文献时使用"
        score = _compute_description_quality(desc, when)
        assert score >= 50  # 有动作动词加分


class TestClassifyTier:
    """热/冷路径分层测试。"""

    def test_hot_tier(self):
        now = int(time.time() * 1000)
        recent = now - 3 * 24 * 60 * 60 * 1000  # 3 天前
        assert _classify_tier(80.0, recent, now) == "hot"

    def test_warm_tier_good_score_old(self):
        now = int(time.time() * 1000)
        old = now - 15 * 24 * 60 * 60 * 1000  # 15 天前
        assert _classify_tier(60.0, old, now) == "warm"

    def test_warm_tier_recent_low_score(self):
        now = int(time.time() * 1000)
        recent = now - 5 * 24 * 60 * 60 * 1000  # 5 天前
        assert _classify_tier(30.0, recent, now) == "warm"

    def test_cold_tier(self):
        now = int(time.time() * 1000)
        very_old = now - 90 * 24 * 60 * 60 * 1000  # 90 天前
        assert _classify_tier(20.0, very_old, now) == "cold"

    def test_cold_never_used(self):
        now = int(time.time() * 1000)
        # overall < 40 且从未使用 → cold
        assert _classify_tier(30.0, None, now) == "cold"


class TestSkillScoringService:
    """评分服务测试。"""

    def test_compute_no_data(self):
        service = SkillScoringService()
        score = service.compute("test-skill")
        assert score.name == "test-skill"
        assert score.overall >= 0
        assert score.tier in ("hot", "warm", "cold")

    def test_compute_with_usage(self):
        service = SkillScoringService()
        now = int(time.time() * 1000)
        score = service.compute(
            "test-skill",
            usage_stats={
                "use_count": 50,
                "success_count": 45,
                "fail_count": 5,
                "last_used_at": now - 2 * 24 * 60 * 60 * 1000,
            },
            description="Search academic papers and literature reviews",
            when_to_use="When user needs to find research papers",
        )
        assert score.success_rate == 90.0
        assert score.usage_freq > 0
        assert score.freshness > 80
        assert score.overall > 30

    def test_compute_batch(self):
        service = SkillScoringService()
        skills = [
            {"name": "a", "description": "desc a", "when_to_use": "when a"},
            {"name": "b", "description": "desc b", "when_to_use": "when b"},
        ]
        scores = service.compute_batch(skills)
        assert len(scores) == 2
        assert scores[0].name == "a"
        assert scores[1].name == "b"

    def test_cache(self):
        service = SkillScoringService()
        score = SkillScore(name="test", overall=50.0)
        service.set_cached(score)
        cached = service.get_cached("test")
        assert cached is not None
        assert cached.overall == 50.0

    def test_to_dict(self):
        score = SkillScore(name="test", overall=75.5, tier="hot")
        d = score.to_dict()
        assert d["name"] == "test"
        assert d["overall"] == 75.5
        assert d["tier"] == "hot"


class TestSingleton:
    """单例管理测试。"""

    def test_get_returns_instance(self):
        reset_scoring_service()
        service = get_scoring_service()
        assert isinstance(service, SkillScoringService)

    def test_reset_clears(self):
        reset_scoring_service()
        s1 = get_scoring_service()
        reset_scoring_service()
        s2 = get_scoring_service()
        assert s1 is not s2
