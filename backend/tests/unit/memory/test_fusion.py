"""R120 — RRF 混合检索融合单元测试。

覆盖：空输入、跨路去重累计、分数数学（rank/k/权重）、等权回退、
memory_id 回退、输入不被修改、降序排序、shortest-zip 语义钉死。
"""

from __future__ import annotations

import pytest

from backend.memory.fusion import reciprocal_rank_fusion

pytestmark = pytest.mark.unit


def test_empty_input_returns_empty():
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[]]) == []


def test_item_in_both_lists_ranks_first():
    vector = [{"id": "a", "content": "va"}, {"id": "b", "content": "vb"}]
    keyword = [{"id": "b", "content": "vb"}, {"id": "c", "content": "vc"}]
    fused = reciprocal_rank_fusion([vector, keyword])
    assert fused[0]["id"] == "b"  # 两路都出现 → 分数累计最高
    assert [f["id"] for f in fused] == ["b", "a", "c"]


def test_score_math_single_hit():
    fused = reciprocal_rank_fusion([[{"id": "x"}]])
    assert fused[0]["rrf_score"] == pytest.approx(1.0 / (60 + 1))


def test_k_parameter_honored():
    fused = reciprocal_rank_fusion([[{"id": "x"}]], k=10)
    assert fused[0]["rrf_score"] == pytest.approx(1.0 / 11)


def test_rank_positions_accumulate():
    # 同一路内 rank2 的分数必须低于 rank1
    fused = reciprocal_rank_fusion([[{"id": "a"}, {"id": "b"}]])
    scores = {f["id"]: f["rrf_score"] for f in fused}
    assert scores["a"] > scores["b"]
    assert scores["b"] == pytest.approx(1.0 / 62)


def test_weights_change_ordering():
    a = [{"id": "a"}, {"id": "b"}]  # a 在本路 rank1
    b = [{"id": "b"}, {"id": "a"}]
    equal = reciprocal_rank_fusion([a, b])  # 等权 → 并列，谁先不定，分数相等
    assert equal[0]["rrf_score"] == equal[1]["rrf_score"]
    # a 路权重大：a 的 rank1 贡献更大 → a 第一
    weighted = reciprocal_rank_fusion([a, b], weights=[0.9, 0.1])
    assert weighted[0]["id"] == "a"


def test_weights_length_mismatch_falls_back_to_equal():
    lists = [[{"id": "a"}], [{"id": "b"}]]
    fused = reciprocal_rank_fusion(lists, weights=[1.0, 0.0, 0.5])  # 长度不符
    scores = {f["id"]: f["rrf_score"] for f in fused}
    assert scores["a"] == scores["b"]  # 等权回退


def test_memory_id_field_fallback():
    fused = reciprocal_rank_fusion([[{"memory_id": "m1"}]])
    assert fused[0]["rrf_score"] == pytest.approx(1.0 / 61)


def test_items_without_id_do_not_crash_and_stay_distinct():
    item_a = {"content": "a"}
    item_b = {"content": "b"}
    fused = reciprocal_rank_fusion([[item_a, item_b]])
    assert len(fused) == 2
    assert {f["content"] for f in fused} == {"a", "b"}


def test_input_not_mutated():
    lists = [[{"id": "a"}], [{"id": "a"}, {"id": "b"}]]
    import copy

    snapshot = copy.deepcopy(lists)
    reciprocal_rank_fusion(lists)
    assert lists == snapshot  # 原 dict 未被塞入 rrf_score


def test_short_lists_get_equal_weights_covering_all():
    # 权重长度不符时：warning + 按实际路数生成等权 → 所有路都参与融合，
    # 不会因 shortest-zip 静默丢路（行为钉死防变更）
    fused = reciprocal_rank_fusion(
        [[{"id": "a"}], [{"id": "b"}], [{"id": "c"}]], weights=[1.0, 0.0]
    )
    scores = {f["id"]: f["rrf_score"] for f in fused}
    assert set(scores) == {"a", "b", "c"}
    assert len(set(scores.values())) == 1
