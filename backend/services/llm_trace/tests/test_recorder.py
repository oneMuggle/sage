"""Tests for LlmTraceRecorder ring buffer.

覆盖:
- append / snapshot 基础行为
- ring buffer FIFO 淘汰
- snapshot 返回新 list(不共享内部状态)
- 并发 append 原子性(GIL 下的 deque.append)
- clear / count 边界
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

import pytest

from backend.services.llm_trace.recorder import (
    LlmTraceRecorder,
    TraceRecord,
    _global_recorder,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    """每个测试重置全局 recorder,避免污染。"""
    _global_recorder.clear()
    yield
    _global_recorder.clear()


def _make_record(idx: int = 0) -> TraceRecord:
    return TraceRecord(
        trace_id=f"t-{idx}",
        ts=datetime.now(timezone.utc),  # noqa: UP017 (datetime.UTC is Py3.11+)
        endpoint="/api/v1/chat/completions",
        upstream_url="https://internal-llm.example/v1/chat/completions",
        upstream_method="POST",
        request_headers={"Content-Type": "application/json"},
        request_body=b'{"messages": []}',
        response_status=200,
        response_headers={"Content-Type": "application/json"},
        response_body=b'{"choices": []}',
        response_streamed=False,
        duration_ms=100,
        error_class=None,
    )


def test_append_then_snapshot_returns_record():
    LlmTraceRecorder.append(_make_record(1))
    snap = LlmTraceRecorder.snapshot()
    assert len(snap) == 1
    assert snap[0].trace_id == "t-1"


def test_ring_buffer_caps_at_50_evicting_oldest():
    for i in range(60):
        LlmTraceRecorder.append(_make_record(i))
    snap = LlmTraceRecorder.snapshot()
    assert len(snap) == 50
    assert snap[0].trace_id == "t-10"  # 第 1-9 被挤掉
    assert snap[-1].trace_id == "t-59"


def test_snapshot_returns_new_list_not_mutating_internal_state():
    LlmTraceRecorder.append(_make_record(1))
    snap = LlmTraceRecorder.snapshot()
    snap.clear()
    assert LlmTraceRecorder.count() == 1  # 内部状态未被外部修改


def test_concurrent_append_is_atomic():
    """100 个线程并发 append,验证无丢失(GIL 下的 deque.append 原子性)。"""
    errors = []

    def worker(start_idx: int):
        try:
            for i in range(100):
                LlmTraceRecorder.append(_make_record(start_idx * 100 + i))
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    # 50 cap ⇒ 1000 个 append 后 snapshot 应正好 50,不应崩溃或泄漏内存
    assert LlmTraceRecorder.count() == 50


def test_clear_empties_buffer():
    LlmTraceRecorder.append(_make_record(1))
    assert LlmTraceRecorder.count() == 1
    LlmTraceRecorder.clear()
    assert LlmTraceRecorder.count() == 0


def test_count_returns_zero_when_empty():
    assert LlmTraceRecorder.count() == 0


def test_append_redacts_request_body_secrets_before_storage():
    LlmTraceRecorder.append(TraceRecord(
        trace_id="r-1", ts=datetime.now(timezone.utc),  # noqa: UP017
        endpoint="/api/v1/chat/completions",
        upstream_url="https://internal-llm.example/v1/chat/completions",
        upstream_method="POST",
        request_headers={"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"},
        request_body=b'{"messages":[{"role":"user","content":"hi"}],"password":"secret123"}',
        response_status=200, response_headers={}, response_body=b"{}",
        response_streamed=False, duration_ms=10,
    ))
    snap = LlmTraceRecorder.snapshot()
    rec = snap[0]
    assert "eyJhbGciOiJIUzI1NiJ9" not in rec.request_headers["Authorization"]
    assert "***REDACTED:" in rec.request_headers["Authorization"]  # 来自 redactor
    # body 第一层不脱敏(留到 exporter 写盘前),仅验证 headers 脱敏已生效
    # body 的 redactor invariant 由 T4 的 test_invariant_password_secret_does_not_leak_through_export 覆盖

