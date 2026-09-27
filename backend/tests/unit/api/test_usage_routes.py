"""R66 — Usage/cost 路由单元测试。

直接调用路由函数（与 r166 惯例一致）。summary/session 端点 monkeypatch
模块级 usage_tracker 单例；requests/trend/export.csv 端点用真实 sqlite3
内存表 + monkeypatch backend.data.database.get_database，覆盖：分页与
session 过滤、known_cost/price_snapshot 语义、trend 时间桶与缓存命中率、
CSV 表头与空值列、异常降级路径。
"""

from __future__ import annotations

import csv
import io
import sqlite3
import time
from types import SimpleNamespace

import pytest

from backend.api import usage_routes as ur

pytestmark = pytest.mark.unit


NOW_MS = int(time.time() * 1000)

_SCHEMA = """
CREATE TABLE usage_events (
    id INTEGER PRIMARY KEY,
    session_id TEXT,
    model TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    cached_tokens INTEGER,
    cache_read_tokens INTEGER,
    cache_creation_tokens INTEGER,
    estimated_cost_usd REAL,
    created_at INTEGER,
    endpoint_id TEXT,
    price_snapshot REAL,
    first_token_ms INTEGER,
    latency_ms INTEGER
)
"""

_COLS = (
    "id, session_id, model, prompt_tokens, completion_tokens, total_tokens,"
    " cached_tokens, cache_read_tokens, cache_creation_tokens,"
    " estimated_cost_usd, created_at, endpoint_id, price_snapshot,"
    " first_token_ms, latency_ms"
)


def _seed_row(**overrides):
    row = {
        "id": None,
        "session_id": "sess-a",
        "model": "test-model",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
        "cached_tokens": 0,
        "cache_read_tokens": 40,
        "cache_creation_tokens": 10,
        "estimated_cost_usd": 0.25,
        "created_at": NOW_MS,
        "endpoint_id": "ep-1",
        "price_snapshot": 1.5,
        "first_token_ms": 120,
        "latency_ms": 1500,
    }
    row.update(overrides)
    return row


def _install_db(monkeypatch, rows):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    for r in rows:
        conn.execute(
            "INSERT INTO usage_events ({cols}) VALUES ({ph})".format(
                cols=_COLS, ph=",".join("?" * 15)
            ),
            tuple(r[c] for c in (
                "id", "session_id", "model", "prompt_tokens",
                "completion_tokens", "total_tokens", "cached_tokens",
                "cache_read_tokens", "cache_creation_tokens",
                "estimated_cost_usd", "created_at", "endpoint_id",
                "price_snapshot", "first_token_ms", "latency_ms",
            )),
        )
    conn.commit()
    fake = SimpleNamespace(get_connection=lambda: conn)
    monkeypatch.setattr("backend.data.database.get_database", lambda: fake)
    return conn


# ---------------------------------------------------------------------------
# summary / session —— tracker 委派
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_summary_delegates_with_range(monkeypatch):
    seen = {}
    sentinel = {"totals": {}, "range": "x"}

    def fake_summary(rng):
        seen["range"] = rng
        return sentinel

    monkeypatch.setattr(ur.usage_tracker, "summary_with_range", fake_summary)
    out = await ur.get_usage_summary(range="30d")
    assert seen["range"] == "30d"
    assert out is sentinel


@pytest.mark.asyncio()
async def test_summary_default_range_is_today(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        ur.usage_tracker,
        "summary_with_range",
        lambda rng: seen.setdefault("range", rng),
    )
    await ur.get_usage_summary(range="today")
    assert seen["range"] == "today"


@pytest.mark.asyncio()
async def test_session_usage_delegates(monkeypatch):
    sentinel = {"total_tokens": 7}

    def fake_summary(session_id):
        assert session_id == "sess-9"
        return sentinel

    monkeypatch.setattr(ur.usage_tracker, "session_summary", fake_summary)
    out = await ur.get_session_usage("sess-9")
    assert out is sentinel


# ---------------------------------------------------------------------------
# _iso_from_ms
# ---------------------------------------------------------------------------


def test_iso_from_ms_zero_and_negative():
    assert ur._iso_from_ms(0) == ""
    assert ur._iso_from_ms(-5) == ""


def test_iso_from_ms_known_value():
    # 1970-01-01T00:01:00Z
    assert ur._iso_from_ms(60_000) == "1970-01-01T00:01:00Z"


# ---------------------------------------------------------------------------
# /requests —— 分页 / 过滤 / 字段映射 / 降级
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_requests_empty_db(monkeypatch):
    _install_db(monkeypatch, [])
    out = await ur.list_usage_requests(limit=50, offset=0, session_id=None)
    assert out == {"items": [], "total": 0, "limit": 50, "offset": 0}


@pytest.mark.asyncio()
async def test_requests_field_mapping_and_ordering(monkeypatch):
    _install_db(
        monkeypatch,
        [
            _seed_row(id=1, created_at=NOW_MS - 1000),
            _seed_row(id=2, created_at=NOW_MS, session_id="sess-b"),
        ],
    )
    out = await ur.list_usage_requests(limit=50, offset=0, session_id=None)
    assert out["total"] == 2
    assert [i["id"] for i in out["items"]] == ["2", "1"]  # created_at DESC
    item = out["items"][0]
    assert item["session_id"] == "sess-b"
    assert item["model"] == "test-model"
    assert item["total_tokens"] == 150
    assert item["known_cost"] is True
    assert item["estimated_cost_usd"] == 0.25
    assert item["has_price_snapshot"] is True
    assert item["endpoint_id"] == "ep-1"
    assert item["created_at_ms"] == NOW_MS
    assert item["created_at_iso"].endswith("Z")


@pytest.mark.asyncio()
async def test_requests_unknown_cost_flags(monkeypatch):
    _install_db(
        monkeypatch,
        [_seed_row(id=1, estimated_cost_usd=None, price_snapshot=None)],
    )
    out = await ur.list_usage_requests(limit=50, offset=0, session_id=None)
    item = out["items"][0]
    assert item["known_cost"] is False
    assert item["estimated_cost_usd"] is None
    assert item["has_price_snapshot"] is False


@pytest.mark.asyncio()
async def test_requests_session_filter(monkeypatch):
    _install_db(
        monkeypatch,
        [
            _seed_row(id=1),
            _seed_row(id=2, session_id="sess-other"),
        ],
    )
    out = await ur.list_usage_requests(limit=50, offset=0, session_id="sess-other")
    assert out["total"] == 1
    assert out["items"][0]["session_id"] == "sess-other"


@pytest.mark.asyncio()
async def test_requests_paging(monkeypatch):
    _install_db(
        monkeypatch,
        [_seed_row(id=i, created_at=NOW_MS - i * 1000) for i in range(1, 6)],
    )
    out = await ur.list_usage_requests(limit=2, offset=1, session_id=None)
    assert out["total"] == 5
    assert [i["id"] for i in out["items"]] == ["2", "3"]
    assert out["limit"] == 2
    assert out["offset"] == 1


@pytest.mark.asyncio()
async def test_requests_db_error_degrades(monkeypatch):
    def boom():
        raise RuntimeError("db gone")

    monkeypatch.setattr("backend.data.database.get_database", boom)
    out = await ur.list_usage_requests(limit=7, offset=3, session_id=None)
    assert out["items"] == []
    assert out["total"] == 0
    assert out["limit"] == 7
    assert out["offset"] == 3
    assert "db gone" in out["error"]


# ---------------------------------------------------------------------------
# /trend —— 时间桶 / 命中率 / 过滤 / 降级
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_trend_day_bucket_and_hit_rate(monkeypatch):
    _install_db(monkeypatch, [_seed_row(id=1)])
    out = await ur.get_usage_trend(range="7d", session_id=None)
    assert out["range"] == "7d"
    assert out["bucket"] == "day"
    assert len(out["series"]) == 1
    point = out["series"][0]
    assert point["ts"].endswith("T00:00:00Z")
    assert point["requests"] == 1
    assert point["prompt_tokens"] == 100
    assert point["completion_tokens"] == 50
    assert point["cost_usd"] == 0.25
    # eligible = prompt + cache_creation = 110; read = 40
    assert point["cache_hit_rate"] == round(40 / 110, 4)


@pytest.mark.asyncio()
async def test_trend_zero_eligible_hit_rate(monkeypatch):
    _install_db(
        monkeypatch,
        [_seed_row(id=1, prompt_tokens=0, cache_read_tokens=0,
                   cache_creation_tokens=0)],
    )
    out = await ur.get_usage_trend(range="today", session_id=None)
    assert out["bucket"] == "hour"
    assert out["series"][0]["cache_hit_rate"] == 0.0


@pytest.mark.asyncio()
async def test_trend_session_filter_excludes(monkeypatch):
    _install_db(
        monkeypatch,
        [_seed_row(id=1), _seed_row(id=2, session_id="sess-other")],
    )
    out = await ur.get_usage_trend(range="7d", session_id="sess-other")
    assert len(out["series"]) == 1
    assert out["series"][0]["requests"] == 1


@pytest.mark.asyncio()
async def test_trend_db_error_degrades(monkeypatch):
    def boom():
        raise RuntimeError("nope")

    monkeypatch.setattr("backend.data.database.get_database", boom)
    out = await ur.get_usage_trend(range="30d", session_id=None)
    assert out["series"] == []
    assert out["range"] == "30d"
    assert out["bucket"] == "day"
    assert "nope" in out["error"]


# ---------------------------------------------------------------------------
# /export.csv —— 表头 / 语义列 / 过滤
# ---------------------------------------------------------------------------


def _csv_rows(text):
    return list(csv.reader(io.StringIO(text)))


@pytest.mark.asyncio()
async def test_export_csv_header_and_known_cost_columns(monkeypatch):
    _install_db(
        monkeypatch,
        [
            _seed_row(id=1),
            _seed_row(id=2, estimated_cost_usd=None, price_snapshot=None,
                      first_token_ms=None, latency_ms=None),
        ],
    )
    text = await ur.export_usage_csv(range="total", session_id=None)
    rows = _csv_rows(text)
    assert rows[0] == [
        "id", "session_id", "model", "prompt_tokens", "completion_tokens",
        "total_tokens", "cached_tokens", "cache_read_tokens",
        "cache_creation_tokens", "estimated_cost_usd", "endpoint_id",
        "known_cost", "first_token_ms", "latency_ms", "created_at_iso",
    ]
    known = rows[1]
    assert known[0] == "1"
    assert known[9] == "0.25"
    assert known[10] == "ep-1"
    assert known[11] == "TRUE"
    assert known[12] == "120"
    assert known[13] == "1500"
    unknown = rows[2]
    assert unknown[9] == ""  # null 成本写空串而非 0.0
    assert unknown[11] == "FALSE"
    assert unknown[12] == ""
    assert unknown[13] == ""


@pytest.mark.asyncio()
async def test_export_csv_session_filter(monkeypatch):
    _install_db(
        monkeypatch,
        [_seed_row(id=1), _seed_row(id=2, session_id="sess-other")],
    )
    text = await ur.export_usage_csv(range="total", session_id="sess-other")
    rows = _csv_rows(text)
    assert len(rows) == 2  # 表头 + 1 行
    assert rows[1][1] == "sess-other"


@pytest.mark.asyncio()
async def test_export_csv_error_degrades(monkeypatch):
    def boom():
        raise RuntimeError("kaput")

    monkeypatch.setattr("backend.data.database.get_database", boom)
    text = await ur.export_usage_csv(range="total", session_id=None)
    assert text.startswith("# export failed:")
    assert "kaput" in text
