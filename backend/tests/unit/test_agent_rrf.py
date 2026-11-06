"""M2-Task 3 — 多路 RRF 融合纯函数测试。

覆盖：单路排序分数、跨路同文档分数相加、来源溯源、top_k、k 参数、
空输入。与 ``backend/wiki/rrf.py`` 的两路变体互不影响。
"""

from __future__ import annotations

import pytest

from backend.agents.rrf import DEFAULT_RRF_K, FusedRank, reciprocal_rank_fusion


class TestReciprocalRankFusion:
    def test_single_ranking_scores_by_rank(self):
        fused = reciprocal_rank_fusion([["a", "b", "c"]])

        assert [item.item_id for item in fused] == ["a", "b", "c"]
        assert fused[0].score == pytest.approx(1.0 / DEFAULT_RRF_K)
        assert fused[1].score == pytest.approx(1.0 / (DEFAULT_RRF_K + 1))
        assert fused[2].score == pytest.approx(1.0 / (DEFAULT_RRF_K + 2))

    def test_document_in_multiple_rankings_sums_scores(self):
        fused = reciprocal_rank_fusion([["a", "b"], ["b", "a"]])
        by_id = {item.item_id: item for item in fused}

        expected = 1.0 / DEFAULT_RRF_K + 1.0 / (DEFAULT_RRF_K + 1)
        assert by_id["a"].score == pytest.approx(expected)
        assert by_id["b"].score == pytest.approx(expected)

    def test_three_rankings_accumulate(self):
        fused = reciprocal_rank_fusion([["a"], ["a"], ["a"]])

        assert len(fused) == 1
        assert fused[0].score == pytest.approx(3.0 / DEFAULT_RRF_K)

    def test_sources_records_contributing_ranking_indices(self):
        fused = reciprocal_rank_fusion([["a"], ["b"], ["a", "b"]])
        by_id = {item.item_id: item for item in fused}

        assert by_id["a"].sources == (0, 2)
        assert by_id["b"].sources == (1, 2)

    def test_sorted_by_score_desc(self):
        fused = reciprocal_rank_fusion([["shared"], ["shared"], ["only"]])
        assert fused[0].item_id == "shared"
        assert fused[0].score > fused[1].score

    def test_top_k_truncates_after_sorting(self):
        fused = reciprocal_rank_fusion([["a", "b", "c"]], top_k=2)

        assert [item.item_id for item in fused] == ["a", "b"]

    def test_custom_k_changes_scores(self):
        fused = reciprocal_rank_fusion([["a"]], k=10.0)

        assert fused[0].score == pytest.approx(1.0 / 10.0)

    def test_duplicate_within_one_ranking_ranked_once(self):
        fused = reciprocal_rank_fusion([["a", "a", "b"]])

        assert [item.item_id for item in fused] == ["a", "b"]
        assert fused[0].score == pytest.approx(1.0 / DEFAULT_RRF_K)

    def test_empty_input_returns_empty(self):
        assert reciprocal_rank_fusion([]) == []
        assert reciprocal_rank_fusion([[], []]) == []

    def test_returns_fused_rank_instances(self):
        fused = reciprocal_rank_fusion([["a"]])
        assert isinstance(fused[0], FusedRank)
