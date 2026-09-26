"""R154 — LLM 调用追踪 ring buffer 单元测试。

覆盖：TraceRecord frozen、ring buffer FIFO 淘汰与顺序保持、snapshot
副本语义、clear、facade append 的脱敏（url/请求响应头）、facade 委托。
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from backend.services.llm_trace.recorder import (
    LlmTraceRecorder,
    TraceRecord,
    _Recorder,
)

pytestmark = pytest.mark.unit


def _record(trace_id="t1", url="https://upstream/v1", headers=None):
    return TraceRecord(
        trace_id=trace_id,
        ts=datetime(2026, 9, 26, tzinfo=UTC),
        endpoint="/v1/chat",
        upstream_url=url,
        upstream_method="POST",
        request_headers=headers or {},
        request_body=b"{}",
        response_status=200,
        response_headers={},
        response_body=b"ok",
        response_streamed=False,
        duration_ms=12,
    )


# ---------------------------------------------------------------------------
# _Recorder ring buffer
# ---------------------------------------------------------------------------


def test_append_count_snapshot_order():
    rec = _Recorder(maxlen=5)
    rec.append(_record("a"))
    rec.append(_record("b"))
    assert rec.count() == 2
    assert [r.trace_id for r in rec.snapshot()] == ["a", "b"]


def test_ring_buffer_fifo_eviction():
    rec = _Recorder(maxlen=2)
    rec.append(_record("a"))
    rec.append(_record("b"))
    rec.append(_record("c"))
    assert rec.count() == 2
    assert [r.trace_id for r in rec.snapshot()] == ["b", "c"]  # 最旧淘汰


def test_snapshot_returns_copy():
    rec = _Recorder(maxlen=5)
    rec.append(_record("a"))
    snap = rec.snapshot()
    snap.clear()
    assert rec.count() == 1  # 内部不受外部修改影响


def test_clear_empties_buffer():
    rec = _Recorder(maxlen=5)
    rec.append(_record("a"))
    rec.clear()
    assert rec.count() == 0


def test_trace_record_frozen():
    rec = _record("a")
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.trace_id = "b"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# facade：脱敏 + 委托
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_global():
    LlmTraceRecorder.clear()
    yield
    LlmTraceRecorder.clear()


def test_facade_append_redacts_url_and_headers(monkeypatch):
    from backend.services.llm_trace import redactor

    monkey_calls = {}

    def fake_redact_url(url):
        monkey_calls["url"] = True
        return url + "?redacted=1"

    def fake_redact_headers(headers):
        monkey_calls["headers"] = True
        return {"X-Sanitized": "1"}

    monkeypatch.setattr(redactor, "redact_url", fake_redact_url)
    monkeypatch.setattr(redactor, "redact_headers", fake_redact_headers)

    LlmTraceRecorder.append(_record("t1", url="https://up/stream?key=secret"))
    snap = LlmTraceRecorder.snapshot()
    assert len(snap) == 1
    rec = snap[0]
    assert rec.upstream_url.endswith("redacted=1")  # redact_url 已应用
    assert rec.request_headers == {"X-Sanitized": "1"}  # 请求头脱敏
    assert rec.response_headers == {"X-Sanitized": "1"}  # 响应头脱敏
    assert rec.request_body == b"{}"  # body 在写入前不脱敏（exporter 前再脱）
    assert monkey_calls == {"url": True, "headers": True}


def test_facade_count_and_clear_delegate():
    LlmTraceRecorder.append(_record("t1"))
    LlmTraceRecorder.append(_record("t2"))
    assert LlmTraceRecorder.count() == 2
    LlmTraceRecorder.clear()
    assert LlmTraceRecorder.count() == 0
    assert LlmTraceRecorder.snapshot() == []
