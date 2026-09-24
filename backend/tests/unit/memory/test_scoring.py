"""R114 — memory/scoring.py 四因子检索评分单元测试。

覆盖：relevance 归一化与中性回退、recency 半衰期衰减、importance 钳位、
confidence 晋升加成、composite_score 加权求和、rank_by_composite 降序排序。
"""

from __future__ import annotations

import pytest

from backend.memory.scoring import (
    WEIGHTS,
    composite_score,
    confidence_factor,
    importance_factor,
    rank_by_composite,
    recency_factor,
    relevance_factor,
)

pytestmark = pytest.mark.unit

DAY_MS = 86_400_000


def make_row(**overrides):
    row = {
        "content": "test memory",
        "rrf_score": 0.02,
        "created_at": 1_700_000_000_000,
        "accessed_at": 1_700_000_000_000,
        "importance": 7,
        "source": "episodic",
        "access_count": 0,
    }
    row.update(overrides)
    return row


class TestRelevanceFactor:
    def test_normal_rrf_score_maps_to_range(self):
        row = {"rrf_score": 0.02}
        r = relevance_factor(row)
        assert 0.0 < r <= 1.0

    def test_zero_rrf_returns_neutral(self):
        assert relevance_factor({"rrf_score": 0}) == 0.5

    def test_missing_rrf_returns_neutral(self):
        assert relevance_factor({}) == 0.5

    def test_very_high_rrf_clamped_to_one(self):
        assert relevance_factor({"rrf_score": 999}) == 1.0


class TestRecencyFactor:
    def test_fresh_memory_high_recency(self):
        row = {"created_at": 1_700_000_000_000}
        now = 1_700_000_000_000 + DAY_MS  # 1 天后
        r = recency_factor(row, now_ms=now)
        assert 0.9 < r < 1.0

    def test_old_memory_decays(self):
        row = {"created_at": 1_700_000_000_000}
        now = 1_700_000_000_000 + 60 * DAY_MS  # 60 天后
        r = recency_factor(row, now_ms=now)
        assert 0.0 < r < 0.5

    def test_missing_timestamp_returns_neutral(self):
        assert recency_factor({}) == 0.5

    def test_accessed_at_used_when_later(self):
        row = {"created_at": 1_700_000_000_000, "accessed_at": 1_700_000_000_000 + 5 * DAY_MS}
        now = 1_700_000_000_000 + 6 * DAY_MS
        r = recency_factor(row, now_ms=now)
        assert 0.9 < r < 1.0


class TestImportanceFactor:
    def test_importance_7_maps_to_point_seven(self):
        assert importance_factor({"importance": 7}) == pytest.approx(0.7)

    def test_missing_defaults_to_neutral(self):
        assert importance_factor({}) == pytest.approx(0.5)

    def test_clamped_to_min_point_one(self):
        assert importance_factor({"importance": -5}) == pytest.approx(0.1)

    def test_clamped_to_max_one(self):
        assert importance_factor({"importance": 99}) == pytest.approx(1.0)


class TestConfidenceFactor:
    def test_baseline_is_half(self):
        assert confidence_factor({"source": "episodic"}) == pytest.approx(0.5)

    def test_promoted_source_adds_bonus(self):
        base = confidence_factor({"source": "episodic"})
        promoted = confidence_factor({"source": "evolution"})
        assert promoted > base

    def test_supersedes_adds_bonus(self):
        base = confidence_factor({"source": "episodic"})
        with_super = confidence_factor({"source": "episodic", "supersedes_id": "old-1"})
        assert with_super > base

    def test_access_count_capped_at_ten(self):
        low = confidence_factor({"source": "episodic", "access_count": 3})
        high = confidence_factor({"source": "episodic", "access_count": 99})
        assert high > low
        assert high <= 1.0


class TestCompositeScore:
    def test_returns_value_between_zero_and_one(self):
        row = make_row()
        assert 0.0 <= composite_score(row) <= 1.0

    def test_weights_sum_to_one(self):
        assert sum(WEIGHTS.values()) == pytest.approx(1.0)


class TestRankByComposite:
    def test_sorts_descending(self):
        fresh_high = make_row(id="fresh", importance=9, rrf_score=0.03)
        old_low = make_row(id="old", importance=2, rrf_score=0.0,
                           created_at=1_000_000_000_000, accessed_at=1_000_000_000_000)
        now = 1_700_000_000_000 + DAY_MS
        ranked = rank_by_composite([old_low, fresh_high], now_ms=now)
        assert ranked[0]["id"] == "fresh"
        assert ranked[1]["id"] == "old"

    def test_does_not_mutate_input_rows(self):
        rows = [make_row(id="a"), make_row(id="b")]
        original = [dict(r) for r in rows]
        rank_by_composite(rows, now_ms=1_700_000_000_000)
        assert rows == original
