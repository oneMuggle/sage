"""Round 15 per-host 出网指标单元测试（web_metrics）。"""

from __future__ import annotations

import pytest

from backend.tools import web_metrics

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    web_metrics.reset()
    yield
    web_metrics.reset()


def test_record_and_snapshot():
    web_metrics.record("example.com", True, 100)
    web_metrics.record("example.com", True, 300, escalated=True)
    web_metrics.record("example.com", False, 50)
    snap = web_metrics.snapshot()
    assert snap["example.com"] == {
        "ok": 2,
        "fail": 1,
        "escalated": 1,
        "avg_elapsed_ms": 200,  # 仅成功样本计均值：(100+300)/2
    }


def test_host_normalized_and_empty_ignored():
    web_metrics.record("Example.COM", True, 10)
    web_metrics.record("", True, 10)
    snap = web_metrics.snapshot()
    assert list(snap) == ["example.com"]


def test_per_host_ring_capacity():
    for i in range(web_metrics.RECORDS_PER_HOST + 10):
        web_metrics.record("example.com", True, i)
    snap = web_metrics.snapshot()
    assert snap["example.com"]["ok"] == web_metrics.RECORDS_PER_HOST


def test_global_host_lru_cap(monkeypatch):
    monkeypatch.setattr(web_metrics, "MAX_HOSTS", 3)
    for h in ("a.com", "b.com", "c.com"):
        web_metrics.record(h, True, 1)
    # 刷新 a.com 的 LRU 序
    web_metrics.record("a.com", True, 1)
    # 新域名挤掉最久未更新的 b.com
    web_metrics.record("d.com", True, 1)
    snap = web_metrics.snapshot()
    assert set(snap) == {"a.com", "c.com", "d.com"}


def test_reset_clears():
    web_metrics.record("example.com", True, 1)
    web_metrics.reset()
    assert web_metrics.snapshot() == {}
