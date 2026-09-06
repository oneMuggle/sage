"""L4 缓存感知记账单元测试。

覆盖:
- extract_cached_tokens 三种 provider usage 形态归一（OpenAI details / DeepSeek /
  Anthropic 原生透传）/ 缺失 → 0 / 非法值 → 0
- estimate_cost_usd 缓存价折算: 命中部分按全价输入 × 0.1;
  cached > prompt 时钳制; cached=0 与旧口径一致
- UsageTracker.record: cached_tokens 进内存聚合 + usage_events 落库
"""

from __future__ import annotations

import pytest

from backend.core.legacy.llm_client import extract_cached_tokens
from backend.services.usage_tracker import (
    CACHE_INPUT_PRICE_FACTOR,
    UsageTracker,
    estimate_cost_usd,
    pricing_for_model,
)

pytestmark = [pytest.mark.unit]


class TestExtractCachedTokens:
    def test_openai_prompt_tokens_details(self):
        usage = {"prompt_tokens": 100, "prompt_tokens_details": {"cached_tokens": 64}}
        assert extract_cached_tokens(usage) == 64

    def test_deepseek_hit_tokens(self):
        usage = {"prompt_tokens": 100, "prompt_cache_hit_tokens": 32}
        assert extract_cached_tokens(usage) == 32

    def test_anthropic_native_shape(self):
        usage = {"prompt_tokens": 100, "cache_read_input_tokens": 50}
        assert extract_cached_tokens(usage) == 50

    def test_missing_or_invalid(self):
        assert extract_cached_tokens({}) == 0
        assert extract_cached_tokens({"prompt_cache_hit_tokens": None}) == 0
        assert extract_cached_tokens({"prompt_tokens_details": "junk"}) == 0
        assert extract_cached_tokens(None) == 0

    def test_details_wins_over_flat_keys(self):
        usage = {
            "prompt_tokens": 100,
            "prompt_tokens_details": {"cached_tokens": 8},
            "prompt_cache_hit_tokens": 99,
        }
        assert extract_cached_tokens(usage) == 8


class TestCacheAwareCost:
    def test_cached_billed_at_discount(self):
        pricing = pricing_for_model("gpt-4o")
        assert pricing is not None
        input_price, output_price = pricing
        cost = estimate_cost_usd("gpt-4o", 1_000_000, 0, cached_tokens=400_000)
        expected = (600_000 * input_price + 400_000 * input_price * CACHE_INPUT_PRICE_FACTOR) / 1_000_000
        assert cost == pytest.approx(expected, abs=1e-6)

    def test_zero_cached_matches_legacy(self):
        assert estimate_cost_usd("gpt-4o", 1000, 100) == estimate_cost_usd(
            "gpt-4o", 1000, 100, cached_tokens=0
        )

    def test_cached_clamped_to_prompt(self):
        full = estimate_cost_usd("gpt-4o", 1000, 0, cached_tokens=0)
        over = estimate_cost_usd("gpt-4o", 1000, 0, cached_tokens=99999)
        assert full is not None
        assert over is not None
        assert over <= full

    def test_unknown_model_returns_none(self):
        assert estimate_cost_usd("no-such-model", 10, 10, cached_tokens=5) is None


class TestTrackerPersistence:
    def test_record_aggregates_cached_tokens(self):
        tracker = UsageTracker()
        tracker.record("gpt-4o", 100, 10, cached_tokens=60)
        tracker.record("gpt-4o", 100, 10, cached_tokens=40)
        summary = tracker.summary()
        assert summary["totals"]["cached_tokens"] == 100
        assert summary["by_model"][0]["cached_tokens"] == 100

    def test_record_persists_cached_column(self):
        from backend.data.database import get_database

        get_database().init_db()  # 幂等: 保证 usage_events 含 cached_tokens 列
        tracker = UsageTracker()
        tracker.record("gpt-4o", 100, 10, cached_tokens=64)
        row = get_database().get_connection().execute(
            "SELECT cached_tokens FROM usage_events ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        assert row[0] == 64
