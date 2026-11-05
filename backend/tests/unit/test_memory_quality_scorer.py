"""Task 3.3 —— 记忆质量评分器单元测试。

评分器给每条记忆算 0-1 分（清晰度 / 重要性 / 新鲜度 / 使用频率 /
独特性），并给出"该不该清理"的判定。两个条件缺一不可：质量分低 **且**
长期未被访问 —— 只看质量分会误伤"刚建好还没被检索到"的记忆。

时间戳约定：DB 里一律毫秒（``int(time.time() * 1000)``），历史脏数据
可能是秒级，经 ``scoring._as_millis`` 归一。
"""

from __future__ import annotations

import pytest

from backend.memory.quality_scorer import (
    LOW_QUALITY_THRESHOLD,
    MAX_CORPUS,
    STALE_DAYS,
    USAGE_SATURATION,
    WEIGHTS,
    MemoryQualityScorer,
)

pytestmark = pytest.mark.unit

NOW_MS = 1_800_000_000_000
DAY_MS = 86_400_000


def _mem(**overrides):
    row = {
        "id": "m1",
        "content": "用户偏好使用 Python 编写后端服务",
        "importance": 6,
        "created_at": NOW_MS,
        "accessed_at": NOW_MS,
        "access_count": 5,
    }
    row.update(overrides)
    return row


def _scorer(corpus=None) -> MemoryQualityScorer:
    return MemoryQualityScorer(corpus=corpus or [], now_ms=NOW_MS)


# ---------- 权重 ----------


def test_weights_sum_to_one() -> None:
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


# ---------- 清晰度 ----------


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("", 0.0),
        ("嗯", 0.2),  # 少于 4 字 → 残缺
        ("用户偏好简洁回答", 1.0),  # 理想长度
        ("x" * 265, 0.75),  # 线性衰减中点
        ("x" * 500, 0.5),  # 衰减下限
        ("x" * 1000, 0.0),  # 超长继续衰减
        ("用户喜欢简洁回答...", 0.5),  # 截断痕迹 → 减半
        ("嗯...", 0.1),  # 残缺 + 截断叠加
    ],
)
def test_clarity(content: str, expected: float) -> None:
    assert MemoryQualityScorer._score_clarity(content) == pytest.approx(expected)


# ---------- 重要性 ----------


@pytest.mark.parametrize(
    ("importance", "expected"),
    [(10, 1.0), (5, 0.5), (1, 0.1), (0, 0.0), (-5, 0.0), ("bad", 0.0), (None, 0.0)],
)
def test_importance(importance, expected: float) -> None:
    assert MemoryQualityScorer._score_importance(
        {"importance": importance}
    ) == pytest.approx(expected)


# ---------- 新鲜度 ----------


def test_recency_decays_by_half_life() -> None:
    scorer = _scorer()
    assert scorer._score_recency(_mem()) == pytest.approx(1.0)
    older = _mem(created_at=NOW_MS - 60 * DAY_MS)
    assert scorer._score_recency(older) == pytest.approx(0.5)
    very_old = _mem(created_at=NOW_MS - 180 * DAY_MS)
    assert scorer._score_recency(very_old) == pytest.approx(0.125)


def test_recency_normalizes_second_level_timestamps() -> None:
    """遗留秒级时间戳归一后按同一半衰期计算，不会因单位错判为远古。"""
    scorer = _scorer()
    row = _mem(created_at=NOW_MS // 1000 - 30 * 86_400)
    assert scorer._score_recency(row) == pytest.approx(0.5 ** (30 / 60), abs=1e-3)


def test_recency_missing_timestamp_is_zero() -> None:
    assert _scorer()._score_recency({}) == 0.0


# ---------- 使用频率 ----------


@pytest.mark.parametrize(
    ("count", "expected"),
    [(0, 0.0), (5, 0.5), (USAGE_SATURATION, 1.0), (100, 1.0), (-3, 0.0), (None, 0.0)],
)
def test_usage(count, expected: float) -> None:
    assert MemoryQualityScorer._score_usage(
        {"access_count": count}
    ) == pytest.approx(expected)


# ---------- 独特性 ----------


def test_uniqueness_without_corpus_is_neutral() -> None:
    """无法判断时不惩罚 —— 否则空库/单条记忆会被无端判低分。"""
    assert _scorer()._score_uniqueness(_mem()) == 1.0


def test_uniqueness_penalizes_exact_duplicate() -> None:
    row = _mem(id="m1")
    corpus = [_mem(id="m2")]  # 同内容、不同 id
    assert _scorer(corpus)._score_uniqueness(row) == pytest.approx(0.0)


def test_uniqueness_ignores_self() -> None:
    row = _mem(id="m1")
    assert _scorer([row])._score_uniqueness(row) == pytest.approx(1.0)


def test_uniqueness_unrelated_content_scores_high() -> None:
    row = _mem(id="m1")
    corpus = [_mem(id="m2", content="猫在窗台上睡着了")]
    assert _scorer(corpus)._score_uniqueness(row) > 0.8


def test_corpus_is_capped() -> None:
    corpus = [
        {"id": f"c{i}", "content": f"完全不同的话题编号{i}"}
        for i in range(MAX_CORPUS + 50)
    ]
    scorer = _scorer(corpus)
    assert len(scorer._corpus) == MAX_CORPUS


# ---------- 汇总 ----------


def test_score_is_weighted_breakdown() -> None:
    scorer = _scorer()
    row = _mem()
    breakdown = scorer.score_breakdown(row)
    expected = sum(WEIGHTS[key] * value for key, value in breakdown.items())
    assert scorer.calculate_quality_score(row) == pytest.approx(expected)


@pytest.mark.parametrize(
    "row",
    [
        {},
        _mem(),
        _mem(importance=0, content="", created_at=0, access_count=0),
        _mem(importance=10, content="x" * 1000, access_count=99),
    ],
)
def test_score_always_in_unit_range(row) -> None:
    assert 0.0 <= _scorer().calculate_quality_score(row) <= 1.0


# ---------- 距上次访问 ----------


def test_days_since_access_prefers_access_time() -> None:
    row = _mem(
        created_at=NOW_MS - 300 * DAY_MS,
        accessed_at=NOW_MS - 10 * DAY_MS,
    )
    assert _scorer().days_since_access(row) == pytest.approx(10.0)


def test_days_since_access_falls_back_to_created() -> None:
    row = _mem(created_at=NOW_MS - 120 * DAY_MS, accessed_at=None)
    assert _scorer().days_since_access(row) == pytest.approx(120.0)


def test_days_since_access_without_timestamps_is_infinite() -> None:
    assert _scorer().days_since_access({}) == float("inf")


# ---------- 清理判定 ----------


def _bad_stale(**overrides):
    row = _mem(
        id="bad",
        content="嗯...",
        importance=1,
        created_at=NOW_MS - 200 * DAY_MS,
        accessed_at=None,
        access_count=0,
    )
    row.update(overrides)
    return row


def test_should_delete_low_quality_and_stale() -> None:
    scorer = _scorer()
    row = _bad_stale()
    assert scorer.calculate_quality_score(row) < LOW_QUALITY_THRESHOLD
    assert scorer.days_since_access(row) > STALE_DAYS
    assert scorer.should_delete(row) is True


def test_should_not_delete_low_quality_but_recent() -> None:
    """刚建好还没被检索到的记忆天然 access_count=0 —— 不能只看质量分。"""
    row = _bad_stale(created_at=NOW_MS, accessed_at=NOW_MS)
    assert _scorer().should_delete(row) is False


def test_should_not_delete_valuable_but_stale() -> None:
    row = _mem(
        id="good",
        content="用户偏好使用 Python 编写后端服务并强制要求类型注解",
        importance=9,
        created_at=NOW_MS - 400 * DAY_MS,
        accessed_at=None,
        access_count=10,
    )
    assert _scorer().should_delete(row) is False


# ---------- 诊断接口 ----------


def test_rank_lowest_orders_and_limits() -> None:
    rows = [
        _mem(id="high", importance=10, access_count=10),
        _bad_stale(id="bad"),
        _mem(id="mid", importance=5, access_count=2),
    ]
    ranked = _scorer().rank_lowest(rows, limit=2)
    assert [mid for mid, _score in ranked] == ["bad", "mid"]
    assert ranked[0][1] <= ranked[1][1]
