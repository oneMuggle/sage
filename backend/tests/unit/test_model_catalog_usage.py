"""Tests for Task 5: usage tracking with price_snapshot and endpoint_id.

Verifies that UsageTracker.record() accepts optional endpoint_id and
price_snapshot, that old records are not affected by catalog price
changes, and that unknown prices remain None (not zero).
"""


import pytest

from backend.services.usage_tracker import UsageRecord, UsageTracker


class TestPriceSnapshot:
    """PriceSnapshot captures pricing at request time."""

    def test_snapshot_fields(self):
        """Snapshot contains all required fields."""
        from backend.services.usage_tracker import PriceSnapshot

        snap = PriceSnapshot(
            input_per_million="3.00",
            output_per_million="15.00",
            scope="openrouter",
            revision=5,
            source="openrouter",
            currency="USD",
            method="basic_io",
            computed_at="2026-09-15T12:00:00Z",
        )
        assert snap.input_per_million == "3.00"
        assert snap.output_per_million == "15.00"
        assert snap.scope == "openrouter"
        assert snap.revision == 5
        assert snap.source == "openrouter"
        assert snap.currency == "USD"
        assert snap.method == "basic_io"
        assert snap.computed_at == "2026-09-15T12:00:00Z"

    def test_snapshot_to_dict(self):
        """Snapshot serializes to JSON-safe dict."""
        from backend.services.usage_tracker import PriceSnapshot

        snap = PriceSnapshot(
            input_per_million="0.15",
            output_per_million="0.60",
            scope="openai",
            revision=1,
            source="openai",
            currency="USD",
            method="basic_io",
            computed_at="2026-09-15T10:00:00Z",
        )
        d = snap.to_dict()
        assert d["input_per_million"] == "0.15"
        assert d["method"] == "basic_io"
        assert d["currency"] == "USD"


class TestUsageTrackerWithEndpointId:
    """UsageTracker.record accepts optional endpoint_id."""

    def test_record_with_endpoint_id(self):
        """Record stores endpoint_id on the UsageRecord."""
        tracker = UsageTracker()
        entry = tracker.record(
            "gpt-4o",
            1000,
            500,
            endpoint_id="ep-test-123",
        )
        assert entry.endpoint_id == "ep-test-123"

    def test_record_without_endpoint_id(self):
        """Record without endpoint_id has None."""
        tracker = UsageTracker()
        entry = tracker.record("gpt-4o", 1000, 500)
        assert entry.endpoint_id is None

    def test_record_with_price_snapshot(self):
        """Record with price_snapshot uses snapshot pricing, not hardcoded."""
        from backend.services.usage_tracker import PriceSnapshot

        tracker = UsageTracker()
        snap = PriceSnapshot(
            input_per_million="10.00",
            output_per_million="30.00",
            scope="custom",
            revision=1,
            source="custom_json",
            currency="USD",
            method="basic_io",
            computed_at="2026-09-15T12:00:00Z",
        )
        entry = tracker.record(
            "some-model",
            1000,
            500,
            endpoint_id="ep-custom",
            price_snapshot=snap,
        )
        assert entry.price_snapshot is not None
        assert entry.price_snapshot.scope == "custom"
        # Cost should use snapshot rates: 10*1000/1M + 30*500/1M = 0.025
        assert entry.estimated_cost_usd is not None
        assert abs(entry.estimated_cost_usd - 0.025) < 1e-9

    def test_record_unknown_price_remains_none(self):
        """Unknown model with no snapshot -> cost is None, not zero."""
        tracker = UsageTracker()
        entry = tracker.record("totally-unknown-model-xyz", 1000, 500)
        assert entry.estimated_cost_usd is None

    def test_snapshot_price_unknown_fields(self):
        """Snapshot with None prices -> cost is None."""
        from backend.services.usage_tracker import PriceSnapshot

        tracker = UsageTracker()
        snap = PriceSnapshot(
            input_per_million=None,
            output_per_million=None,
            scope="unknown",
            revision=0,
            source="probe",
            currency="USD",
            method="basic_io",
            computed_at="2026-09-15T12:00:00Z",
        )
        entry = tracker.record(
            "some-model",
            1000,
            500,
            price_snapshot=snap,
        )
        assert entry.estimated_cost_usd is None


class TestNoCacheDiscountOnNewRecords:
    """New records do NOT apply the old uniform 0.1 cache discount.

    When a price_snapshot is provided, cost is calculated using basic
    estimate_basic() from model_catalog.pricing — no cache discount.
    Cache token metrics are still preserved for display.
    """

    def test_snapshot_cost_no_cache_discount(self):
        """Price snapshot cost does not apply cache factor."""
        from backend.services.usage_tracker import PriceSnapshot

        tracker = UsageTracker()
        snap = PriceSnapshot(
            input_per_million="10.00",
            output_per_million="20.00",
            scope="test",
            revision=1,
            source="test",
            currency="USD",
            method="basic_io",
            computed_at="2026-09-15T12:00:00Z",
        )
        # With cache: 500 cached out of 1000 prompt tokens
        # basic_io: 10*1000/1M + 20*500/1M = 0.02 (no cache discount)
        entry = tracker.record(
            "test-model",
            1000,
            500,
            cached_tokens=500,
            price_snapshot=snap,
        )
        # basic_io flat rate, no cache discount applied
        expected = (10.0 * 1000 + 20.0 * 500) / 1_000_000
        assert abs(entry.estimated_cost_usd - expected) < 1e-9
        # Cache metrics still preserved
        assert entry.cached_tokens == 500


class TestUsageRecordEndpointId:
    """UsageRecord dataclass has endpoint_id and price_snapshot fields."""

    def test_record_has_new_fields(self):
        entry = UsageRecord(
            model="test",
            prompt_tokens=100,
            completion_tokens=50,
            estimated_cost_usd=None,
            at="2026-09-15T12:00:00+00:00",
        )
        assert entry.endpoint_id is None
        assert entry.price_snapshot is None

    def test_record_with_all_fields(self):
        from backend.services.usage_tracker import PriceSnapshot

        snap = PriceSnapshot(
            input_per_million="1.00",
            output_per_million="2.00",
            scope="test",
            revision=1,
            source="test",
            currency="USD",
            method="basic_io",
            computed_at="2026-09-15T12:00:00Z",
        )
        entry = UsageRecord(
            model="test",
            prompt_tokens=100,
            completion_tokens=50,
            estimated_cost_usd=0.0003,
            at="2026-09-15T12:00:00+00:00",
            endpoint_id="ep-123",
            price_snapshot=snap,
        )
        assert entry.endpoint_id == "ep-123"
        assert entry.price_snapshot.method == "basic_io"


def _patch_memory_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """usage_events 落库/查询走内存 DB (与 test_usage_tracker 同口径)。"""
    from backend.data import database as database_module

    test_db = database_module.Database(":memory:")
    test_db.init_db()
    monkeypatch.setattr(database_module, "_db", test_db)


class TestSummaryWithRangeKnownUnknown:
    """Task 5 regression: summary_with_range exposes known/unknown counts.

    Covers both memory path (today) and DB path (total) to ensure the
    field set is identical regardless of source.
    """

    def test_today_memory_path_known_unknown_counts(self):
        """range=today returns memory state with known/unknown counts."""
        tracker = UsageTracker()
        tracker.record("gpt-4o", 100, 40)  # known (PRICING dict has gpt-4o)
        tracker.record("unknown-model", 10, 2)  # unknown (cost None)
        data = tracker.summary_with_range("today")
        assert data["range"] == "today"
        assert data["known_requests"] == 1
        assert data["unknown_requests"] == 1
        assert data["has_partial_estimates"] is True
        # today 子桶也带 known/unknown
        assert data["today"]["known_requests"] == 1
        assert data["today"]["unknown_requests"] == 1

    def test_today_memory_path_all_known(self):
        """When all records have known cost, has_partial_estimates=False."""
        tracker = UsageTracker()
        tracker.record("gpt-4o", 100, 40)
        tracker.record("claude-haiku", 50, 20)
        data = tracker.summary_with_range("today")
        assert data["known_requests"] == 2
        assert data["unknown_requests"] == 0
        assert data["has_partial_estimates"] is False

    def test_today_memory_path_all_unknown(self):
        """When all records have unknown cost, has_partial_estimates=False."""
        tracker = UsageTracker()
        tracker.record("mystery-a", 10, 2)
        tracker.record("mystery-b", 20, 4)
        data = tracker.summary_with_range("today")
        assert data["known_requests"] == 0
        assert data["unknown_requests"] == 2
        assert data["has_partial_estimates"] is False

    def test_total_db_path_known_unknown_counts(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """range=total aggregates known/unknown from usage_daily_rollups."""
        _patch_memory_db(monkeypatch)
        tracker = UsageTracker()
        tracker.record("gpt-4o", 100, 40)  # known
        tracker.record("unknown-model", 10, 2)  # unknown
        data = tracker.summary_with_range("total")
        assert data["range"] == "total"
        assert data["known_requests"] == 1
        assert data["unknown_requests"] == 1
        assert data["has_partial_estimates"] is True
        # by_model 也分别带 known/unknown
        by_model = {m["model"]: m for m in data["by_model"]}
        assert by_model["gpt-4o"]["known_requests"] == 1
        assert by_model["gpt-4o"]["unknown_requests"] == 0
        assert by_model["unknown-model"]["known_requests"] == 0
        assert by_model["unknown-model"]["unknown_requests"] == 1

    def test_db_path_null_cost_not_conflated_with_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Null cost must stay null in rollup, not be folded into 0.0."""
        _patch_memory_db(monkeypatch)
        tracker = UsageTracker()
        tracker.record("unknown-model", 100, 20)  # cost None
        data = tracker.summary_with_range("total")
        # estimated_cost_usd 是 None (不是 0.0) — null 语义保留
        assert data["totals"]["estimated_cost_usd"] is None
        # 但 known/unknown 计数正确
        assert data["known_requests"] == 0
        assert data["unknown_requests"] == 1
