"""
M6 GET /api/v1/usage 路由契约测试
"""

from __future__ import annotations

import pytest

from backend.services.usage_tracker import usage_tracker

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_tracker():
    usage_tracker.reset()
    yield
    usage_tracker.reset()


@pytest.mark.asyncio()
async def test_usage_summary_contract_empty(client):
    resp = await client.get("/api/v1/usage")
    assert resp.status_code == 200
    body = resp.json()
    # L8 PR-A/B: summary 顶层扩 cache_hit_rate + range
    # Task 5 (2026-09-15): 追加 known/unknown 聚合字段
    assert set(body.keys()) == {
        "totals",
        "by_model",
        "today",
        "cache_hit_rate",
        "range",
        "known_requests",
        "unknown_requests",
        "has_partial_estimates",
        "known_requests_today",
        "unknown_requests_today",
    }
    assert body["range"] == "today"
    # L4 cached_tokens + L8 cache_read_tokens / cache_creation_tokens 维度
    # Task 5: 增 known_requests / unknown_requests 计数器
    assert body["totals"] == {
        "requests": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cached_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "estimated_cost_usd": None,
        "known_requests": 0,
        "unknown_requests": 0,
    }
    assert body["by_model"] == []
    assert body["today"]["requests"] == 0
    # Task 5: 空表时 known/unknown 都 0, has_partial_estimates false
    assert body["known_requests"] == 0
    assert body["unknown_requests"] == 0
    assert body["has_partial_estimates"] is False


@pytest.mark.asyncio()
async def test_usage_summary_reflects_records(client):
    usage_tracker.record("gpt-4o", 100, 40)
    usage_tracker.record("unknown-model", 10, 2)

    resp = await client.get("/api/v1/usage")
    assert resp.status_code == 200
    body = resp.json()

    assert body["totals"]["requests"] == 2
    assert body["totals"]["prompt_tokens"] == 110
    assert body["totals"]["completion_tokens"] == 42
    # 仅 gpt-4o 计入成本: 100/1e6*2.5 + 40/1e6*10
    assert body["totals"]["estimated_cost_usd"] == pytest.approx(0.00065)
    assert [m["model"] for m in body["by_model"]] == ["gpt-4o", "unknown-model"]
    assert body["today"]["requests"] == 2
    # Task 5: known/unknown 聚合 — gpt-4o 已知, unknown-model 未知
    assert body["known_requests"] == 1
    assert body["unknown_requests"] == 1
    assert body["has_partial_estimates"] is True
