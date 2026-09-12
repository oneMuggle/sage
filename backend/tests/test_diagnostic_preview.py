from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.main import app  # 触发 include_router
from backend.services.llm_trace.recorder import LlmTraceRecorder, TraceRecord


@pytest.fixture(autouse=True)
def _clean_recorder():
    LlmTraceRecorder.clear()
    yield
    LlmTraceRecorder.clear()


@pytest.fixture()
def client():
    # TestClient 触发 startup;若需要 SAGE_LOCAL_AUTH_TOKEN,fixture 注入
    return TestClient(app)


def _record_with_url(url: str, ts_offset_sec: int = 0) -> TraceRecord:
    return TraceRecord(
        trace_id=f"t-{url}-{ts_offset_sec}",
        ts=datetime.now(timezone.utc) + timedelta(seconds=ts_offset_sec),  # noqa: UP017 — py38: datetime.UTC is 3.11+
        endpoint="/api/v1/chat/completions",
        upstream_url=url,
        upstream_method="POST",
        request_headers={},
        request_body=b"{}",
        response_status=200,
        response_headers={},
        response_body=b"{}",
        response_streamed=False,
        duration_ms=10,
    )


def test_preview_returns_zero_when_empty(client):
    r = client.get("/api/v1/diagnostic/preview")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 0
    assert data["oldestTs"] is None
    assert data["sampleUrls"] == []


def test_preview_returns_count_and_sample_urls(client):
    for i in range(5):
        LlmTraceRecorder.append(
            _record_with_url(
                f"https://internal-{i}.example/v1/chat/completions",
                ts_offset_sec=i,
            )
        )
    data = client.get("/api/v1/diagnostic/preview").json()
    assert data["count"] == 5
    assert data["oldestTs"] is not None
    assert data["newestTs"] is not None
    assert len(data["sampleUrls"]) == 5
    # 样例 URL 已被 redactor 走一遍(无 userinfo 时不变)
    assert "internal-0.example" in data["sampleUrls"][0]
