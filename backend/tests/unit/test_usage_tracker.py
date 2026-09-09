"""
M6 用量追踪单元测试

覆盖 tracker 计算 / ring cap / 未知模型成本 None / 定价前缀匹配 /
LLMResponse usage 提取 (respx mock) + tracker 记录联动。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.legacy.llm_client import LLMClient, LLMConfig
from backend.services.usage_tracker import (
    RECORD_CAP,
    UsageTracker,
    estimate_cost_usd,
    pricing_for_model,
    usage_tracker,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_global_tracker():
    usage_tracker.reset()
    yield
    usage_tracker.reset()


# ==================== tracker 计算 ====================


def test_record_and_summary_totals():
    tracker = UsageTracker()
    tracker.record("gpt-4o", 1_000_000, 500_000)
    summary = tracker.summary()
    totals = summary["totals"]
    assert totals["requests"] == 1
    assert totals["prompt_tokens"] == 1_000_000
    assert totals["completion_tokens"] == 500_000
    # gpt-4o: $2.5/M in + $10/M out → 2.5 + 5.0
    assert totals["estimated_cost_usd"] == pytest.approx(7.5)


def test_unknown_model_cost_is_none():
    tracker = UsageTracker()
    record = tracker.record("my-local-model", 100, 50)
    assert record.estimated_cost_usd is None
    summary = tracker.summary()
    assert summary["totals"]["estimated_cost_usd"] is None
    assert summary["by_model"][0]["estimated_cost_usd"] is None
    assert summary["today"]["requests"] == 1


def test_mixed_known_and_unknown_costs_sum_priced_only():
    tracker = UsageTracker()
    tracker.record("unknown-model", 1_000_000, 0)  # 无定价, 不计成本
    tracker.record("gpt-4o-mini", 1_000_000, 0)  # $0.15/M
    assert tracker.summary()["totals"]["estimated_cost_usd"] == pytest.approx(0.15)


def test_ring_buffer_caps_records_but_totals_keep_counting():
    tracker = UsageTracker(cap=5)
    for i in range(7):
        tracker.record("gpt-4o", 10 + i, 1)
    assert len(tracker.recent(limit=100)) == 5
    assert tracker.summary()["totals"]["requests"] == 7
    # recent() 新 → 旧
    assert tracker.recent(limit=1)[0].prompt_tokens == 16


def test_default_cap_is_1000():
    assert RECORD_CAP == 1000
    tracker = UsageTracker()
    for _ in range(1001):
        tracker.record("gpt-4o", 1, 1)
    assert len(tracker.recent(limit=2000)) == 1000
    assert tracker.summary()["totals"]["requests"] == 1001


def test_by_model_grouping_sorted_by_requests():
    tracker = UsageTracker()
    tracker.record("gpt-4o", 10, 5)
    tracker.record("gpt-4o", 10, 5)
    tracker.record("deepseek-chat", 10, 5)
    by_model = tracker.summary()["by_model"]
    assert [m["model"] for m in by_model] == ["gpt-4o", "deepseek-chat"]
    assert by_model[0]["requests"] == 2
    assert by_model[0]["prompt_tokens"] == 20


def test_today_bucket_aggregates():
    tracker = UsageTracker()
    tracker.record("gpt-4o", 100, 20)
    tracker.record("gpt-4o", 50, 10)
    today = tracker.summary()["today"]
    assert today["requests"] == 2
    assert today["prompt_tokens"] == 150
    assert today["completion_tokens"] == 30


def test_reset_clears_everything():
    tracker = UsageTracker()
    tracker.record("gpt-4o", 1, 1)
    tracker.reset()
    summary = tracker.summary()
    assert summary["totals"]["requests"] == 0
    assert summary["by_model"] == []
    assert summary["today"]["requests"] == 0


# ==================== 定价 ====================


def test_pricing_prefix_match_longest_wins():
    assert pricing_for_model("gpt-4o-mini") == (0.15, 0.60)
    assert pricing_for_model("gpt-4o") == (2.50, 10.00)
    assert pricing_for_model("gpt-4o-2024-08-06") == (2.50, 10.00)
    assert pricing_for_model("claude-sonnet-4-20250514") == (3.00, 15.00)
    assert pricing_for_model("GPT-4O") == (2.50, 10.00)  # 大小写不敏感


def test_pricing_unknown_model_returns_none():
    assert pricing_for_model("totally-custom-llm") is None
    assert pricing_for_model("") is None


def test_estimate_cost_math():
    cost = estimate_cost_usd("claude-haiku", 1_000_000, 500_000)
    assert cost == pytest.approx(0.80 + 2.00)
    assert estimate_cost_usd("nope", 10, 10) is None


# ==================== LLMClient usage 提取 ====================


def _openai_body(model: str = "gpt-4o", with_usage: bool = True) -> dict:
    body = {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "hello"},
                "finish_reason": "stop",
            }
        ],
    }
    if with_usage:
        body["usage"] = {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19}
    return body


def _make_client() -> LLMClient:
    return LLMClient(
        LLMConfig(
            provider="openai",
            api_key="test-key",
            base_url="https://api.example.com",
            model="gpt-4o",
            use_proxy=False,
        )
    )


def _mock_http(body: dict) -> AsyncMock:
    """mock 掉 _get_client() 返回的 httpx 客户端 (避开 respx 不兼容)。"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value=body)
    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=mock_response)
    return mock_http


@pytest.mark.asyncio()
async def test_llm_response_carries_usage_and_tracker_records():
    client = _make_client()
    with patch.object(client, "_get_client", return_value=_mock_http(_openai_body())):
        response = await client.chat([{"role": "user", "content": "hi"}])

    # L4: usage 携带 cached_tokens（无缓存命中时为 0）
    assert response.usage == {
        "prompt_tokens": 12,
        "completion_tokens": 7,
        "total_tokens": 19,
        "cached_tokens": 0,
    }
    summary = usage_tracker.summary()
    assert summary["totals"]["requests"] == 1
    assert summary["totals"]["prompt_tokens"] == 12
    assert summary["by_model"][0]["model"] == "gpt-4o"
    await client.close()


@pytest.mark.asyncio()
async def test_llm_response_usage_none_when_absent():
    client = _make_client()
    body = _openai_body(with_usage=False)
    with patch.object(client, "_get_client", return_value=_mock_http(body)):
        response = await client.chat([{"role": "user", "content": "hi"}])

    assert response.usage is None
    assert usage_tracker.summary()["totals"]["requests"] == 0
    await client.close()


# ==================== U17: last_* 透出 (round4 批次 B) ====================


def _patch_memory_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """usage_events 落库/查询走内存 DB（与集成测试同口径）。"""
    from backend.data import database as database_module

    test_db = database_module.Database(":memory:")
    test_db.init_db()
    monkeypatch.setattr(database_module, "_db", test_db)


def test_session_summary_exposes_last_request(monkeypatch: pytest.MonkeyPatch):
    import time

    _patch_memory_db(monkeypatch)
    tracker = UsageTracker()
    tracker.record("gpt-4o", 100, 10, session_id="sess-u17", cached_tokens=40)
    time.sleep(0.003)  # created_at 毫秒精度,错开保证"最近一行"确定
    tracker.record("claude-sonnet", 200, 20, session_id="sess-u17", cached_tokens=50)

    summary = tracker.session_summary("sess-u17")
    assert summary["requests"] == 2
    assert summary["last_model"] == "claude-sonnet"
    assert summary["last_prompt_tokens"] == 200
    assert summary["last_cached_tokens"] == 50
    assert summary["last_at_ms"] > 0
    assert tracker.last_request("sess-u17") is not None


def test_session_summary_without_rows_returns_none_last(monkeypatch: pytest.MonkeyPatch):
    _patch_memory_db(monkeypatch)
    summary = UsageTracker().session_summary("no-such-session")
    assert summary["requests"] == 0
    assert summary["last_model"] is None
    assert summary["last_prompt_tokens"] is None
    assert summary["last_cached_tokens"] is None
    assert summary["last_at_ms"] is None
    assert UsageTracker().last_request("no-such-session") is None


# ==================== L8 PR-A (2026-09-09): cache 拆分 + hit_rate 派生 ====================


def test_record_accepts_split_cache_fields():
    """record() 显式接受 cache_read / cache_creation 两个拆分字段。"""
    tracker = UsageTracker()
    record = tracker.record(
        "claude-sonnet-4",
        prompt_tokens=1000,
        completion_tokens=200,
        cache_read_tokens=600,
        cache_creation_tokens=400,
    )
    # 拆分字段落到 record 与 totals bucket
    assert record.cache_read_tokens == 600
    assert record.cache_creation_tokens == 400
    totals = tracker.summary()["totals"]
    assert totals["cache_read_tokens"] == 600
    assert totals["cache_creation_tokens"] == 400


def test_cache_hit_rate_derived_when_split_fields_used():
    """eligible = prompt + cache_creation, hit_rate = cache_read / eligible。"""
    tracker = UsageTracker()
    # prompt=200, creation=300, read=400 → eligible=500 → 0.8
    tracker.record(
        "claude-sonnet-4",
        prompt_tokens=200,
        completion_tokens=50,
        cache_read_tokens=400,
        cache_creation_tokens=300,
    )
    summary = tracker.summary()
    assert summary["cache_hit_rate"] == pytest.approx(0.8)


def test_cache_hit_rate_zero_when_no_cache_interaction():
    """无 read/creation 时 hit_rate = 0.0 (避免除零)。"""
    tracker = UsageTracker()
    tracker.record("gpt-4o", prompt_tokens=100, completion_tokens=10)
    assert tracker.summary()["cache_hit_rate"] == 0.0


def test_cache_hit_rate_legacy_cached_tokens_fallback():
    """旧调用只填 cached_tokens, 把 cached_tokens 当作 cache_read 回退。"""
    tracker = UsageTracker()
    # prompt=100, cached_tokens=25 → fallback hit_rate = 25/100 = 0.25
    tracker.record("gpt-4o", prompt_tokens=100, completion_tokens=10, cached_tokens=25)
    assert tracker.summary()["cache_hit_rate"] == pytest.approx(0.25)


def test_session_summary_includes_cache_split_and_hit_rate(monkeypatch: pytest.MonkeyPatch):
    """session_summary 持久化层同样拆分 read/creation 并派生 hit_rate。"""
    _patch_memory_db(monkeypatch)
    tracker = UsageTracker()
    tracker.record(
        "claude-sonnet-4",
        prompt_tokens=500,
        completion_tokens=100,
        cache_read_tokens=300,
        cache_creation_tokens=200,
        session_id="sess-cache",
    )
    summary = tracker.session_summary("sess-cache")
    assert summary["cache_read_tokens"] == 300
    assert summary["cache_creation_tokens"] == 200
    # eligible = 500 + 200 = 700, hit = 300/700
    assert summary["cache_hit_rate"] == pytest.approx(300 / 700)


def test_today_bucket_aggregates_cache_split():
    """today bucket 也累计 cache_read/creation 拆分。"""
    tracker = UsageTracker()
    tracker.record(
        "claude-sonnet-4",
        prompt_tokens=100,
        completion_tokens=10,
        cache_read_tokens=70,
        cache_creation_tokens=30,
    )
    tracker.record(
        "claude-sonnet-4",
        prompt_tokens=50,
        completion_tokens=5,
        cache_read_tokens=40,
        cache_creation_tokens=10,
    )
    today = tracker.summary()["today"]
    assert today["cache_read_tokens"] == 110
    assert today["cache_creation_tokens"] == 40
