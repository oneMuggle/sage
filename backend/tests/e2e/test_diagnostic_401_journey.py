"""E2E: diagnostic 401 journey — 故意注入 401 验证 zip 含 upstream_url.

场景还原:
1. 用户配错 LLM 上游 URL 或 API key → 上游返 401
2. 代理层透传 401 给调用方
3. 用户点"导出诊断包" → 下载 zip
4. zip 内 trace.jsonl 包含 upstream_url(关键排查信息)、
   401 状态码、"Invalid API key" 错误消息,
   且本地 Authorization 已脱敏

注意:代理层在 upstream 返回 4xx/5xx 时会记录 trace,本测试验证代理调用本身产出
诊断记录,再验证诊断导出管道的正确性。

遵循项目现有 e2e/integration 测试风格:
- 使用 conftest.py 的 ``client`` fixture(httpx.AsyncClient + ASGITransport)
- 使用 ``respx`` mock 上游(参考 test_llm_proxy_routes.py)
- pytestmark = [pytest.mark.e2e]
"""
from __future__ import annotations

import io
import json
import socket
import zipfile

import pytest
import respx
from httpx import Response

from backend.services.llm_trace.recorder import LlmTraceRecorder

pytestmark = [pytest.mark.e2e]

UPSTREAM = "http://upstream-401.example.com"
CHAT_PATH = "/v1/chat/completions"


@pytest.fixture(autouse=True)
def _clean_recorder():
    """每个测试前后清空 recorder,防止跨测试泄漏。"""
    LlmTraceRecorder.clear()
    yield
    LlmTraceRecorder.clear()


@pytest.fixture(autouse=True)
def _mock_dns_for_upstream(monkeypatch):
    """Mock DNS: 给 test-only 域名 ``upstream-401.example.com`` 一个公网 IP,
    绕过代理层的 DNS 解析(否则 socket.getaddrinfo 真去查 .example.com 会失败)。

    与 test_llm_proxy_routes.py 的 ``_resolve_mock_provider_names`` 同理。
    """
    original_getaddrinfo = socket.getaddrinfo

    def fake_getaddrinfo(host, *args, **kwargs):
        if host == "upstream-401.example.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80))]
        return original_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


@pytest.mark.asyncio()
async def test_diagnostic_401_journey(client):
    """故意注入 401 → 导出诊断包 → zip 含 upstream_url + 错误信息 + header 脱敏。

    场景: 用户配错 API key → 上游 401 → 一键导出诊断包 →
    支持人员从 zip 中看到 upstream_url 确认 URL 是否配错。
    """
    # ── Step 1: mock 上游始终返 401 ──
    error_body = {"error": {"message": "Invalid API key (mocked)"}}
    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        mock.post(CHAT_PATH).mock(
            return_value=Response(401, json=error_body)
        )

        # ── Step 2: 走代理层 → 确认 401 被透传 ──
        resp = await client.post(
            "/api/v1/llm/v1/chat/completions",
            headers={
                "X-LLM-Provider-Url": UPSTREAM,
                "Content-Type": "application/json",
                "Authorization": "Bearer sk-fake-key-12345",
            },
            json={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert resp.status_code == 401, f"proxy should forward 401, got {resp.status_code}"

    # ── Step 3: 验证 recorder 自动记录了 401 调用 ──
    # 代理层在 upstream 返回 4xx/5xx 时自动调用 _safe_record_trace,
    # 无需手动 seed。验证 recorder 中至少有 1 条记录。
    records = LlmTraceRecorder.snapshot()
    assert len(records) >= 1, "proxy should auto-record 401 trace"

    # ── Step 4: 导出诊断包 ──
    export_resp = await client.post("/api/v1/diagnostic/export")
    assert export_resp.status_code == 200
    assert export_resp.headers["content-type"].startswith("application/zip")

    # ── Step 5: 解 zip 并断言 ──
    zf = zipfile.ZipFile(io.BytesIO(export_resp.content))
    names = zf.namelist()
    assert "trace.jsonl" in names, f"trace.jsonl missing from zip: {names}"

    trace_text = zf.read("trace.jsonl").decode("utf-8").strip()
    assert trace_text, "trace.jsonl should be non-empty"

    first_line = json.loads(trace_text.split("\n")[0])

    # 关键回归断言: upstream_url 可见(用户诊断 URL 配错的关键信息)
    assert first_line["upstream_url"].startswith("http://"), (
        "upstream_url must be visible and start with http://"
    )
    assert "upstream-401.example.com" in first_line["upstream_url"]

    # response 状态码 401 保留
    assert first_line["response"]["status"] == 401

    # 错误消息包含 "Invalid API key"
    error_msg = first_line["response"].get("error")
    assert error_msg is not None, "response.error should not be None for 401"
    assert "Invalid API key" in error_msg, (
        f"error message should contain 'Invalid API key', got: {error_msg!r}"
    )

    # Authorization 已脱敏 — test-local-auth-token 不得出现在 trace 中
    assert "test-local-auth-token" not in trace_text, (
        "local auth token leaked in trace.jsonl!"
    )
    # provider key 也应被脱敏
    assert "sk-fake-key-12345" not in trace_text, (
        "provider API key leaked in trace.jsonl!"
    )
