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
    assert set(body.keys()) == {"totals", "by_model", "today"}
    assert body["totals"] == {
        "requests": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "estimated_cost_usd": None,
    }
    assert body["by_model"] == []
    assert body["today"]["requests"] == 0


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
