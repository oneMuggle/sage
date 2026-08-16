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

    assert response.usage == {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19}
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
