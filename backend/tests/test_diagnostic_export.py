"""Tests for POST /api/v1/diagnostic/export endpoint.

Validates:
- zip bytes returned with correct content-type
- trace.jsonl + manifest.json present in zip
- Authorization header redacted, upstream_url preserved (401 regression)
- include_prompts=true/false controls prompt text redaction
- empty recorder still returns valid zip
"""
import io
import zipfile
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.llm_trace.recorder import LlmTraceRecorder, TraceRecord


@pytest.fixture(autouse=True)
def _clean():
    LlmTraceRecorder.clear()
    yield
    LlmTraceRecorder.clear()


@pytest.fixture()
def client():
    return TestClient(app)


def _seed_one_401():
    LlmTraceRecorder.append(TraceRecord(
        trace_id="t-401", ts=datetime.now(timezone.utc),  # noqa: UP017 — py38: datetime.UTC is 3.11+
        endpoint="/api/v1/chat/completions",
        upstream_url="http://wrong-host.example/v1/chat/completions",
        upstream_method="POST",
        request_headers={"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c", "Content-Type": "application/json"},
        request_body=b'{"messages":[{"role":"user","content":"hi"}]}',
        response_status=401,
        response_headers={"Content-Type": "application/json"},
        response_body=b'{"error":{"message":"Invalid API key"}}',
        response_streamed=False, duration_ms=120, error_class="upstream_401",
    ))


def test_export_returns_zip_bytes(client):
    _seed_one_401()
    r = client.post("/api/v1/diagnostic/export")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/zip")
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert "trace.jsonl" in zf.namelist()
    assert "manifest.json" in zf.namelist()


def test_export_zip_contains_redacted_auth_and_visible_upstream_url(client):
    """关键回归用例:针对 2026-09-11 401 bug。"""
    _seed_one_401()
    r = client.post("/api/v1/diagnostic/export")
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    line = zf.read("trace.jsonl").decode("utf-8")
    # Authorization 已脱敏
    assert "eyJhbGciOiJIUzI1NiJ9" not in line
    assert "***REDACTED:bearer***" in line
    # upstream_url 保留(关键!)
    assert "wrong-host.example" in line
    # 响应状态码 401 保留
    assert '"status": 401' in line


def test_export_with_include_prompts_true_keeps_prompt_text(client):
    LlmTraceRecorder.append(TraceRecord(
        trace_id="t-p", ts=datetime.now(timezone.utc),  # noqa: UP017 — py38: datetime.UTC is 3.11+
        endpoint="/api/v1/chat/completions",
        upstream_url="http://x/v1/chat/completions", upstream_method="POST",
        request_headers={},
        request_body=b'{"messages":[{"role":"user","content":"please debug this"}]}',
        response_status=200, response_headers={}, response_body=b"{}",
        response_streamed=False, duration_ms=10,
    ))
    r = client.post("/api/v1/diagnostic/export?include_prompts=true")
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    line = zf.read("trace.jsonl").decode("utf-8")
    assert "please debug this" in line


def test_export_with_include_prompts_false_redacts_prompt(client):
    LlmTraceRecorder.append(TraceRecord(
        trace_id="t-p", ts=datetime.now(timezone.utc),  # noqa: UP017 — py38: datetime.UTC is 3.11+
        endpoint="/api/v1/chat/completions",
        upstream_url="http://x/v1/chat/completions", upstream_method="POST",
        request_headers={},
        request_body=b'{"messages":[{"role":"user","content":"please debug this"}]}',
        response_status=200, response_headers={}, response_body=b"{}",
        response_streamed=False, duration_ms=10,
    ))
    r = client.post("/api/v1/diagnostic/export?include_prompts=false")
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    line = zf.read("trace.jsonl").decode("utf-8")
    assert "please debug this" not in line
    assert "***REDACTED:prompt***" in line


def test_export_with_empty_recorder_still_returns_zip(client):
    r = client.post("/api/v1/diagnostic/export")
    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    line = zf.read("trace.jsonl").decode("utf-8").strip()
    assert line == ""  # 0 条记录
