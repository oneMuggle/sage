"""LLM 代理路由集成测试。

验证 ``/api/v1/llm/*`` 把请求透传到 ``X-LLM-Provider-Url`` 头部指定的上游,
并保持方法、请求体、查询串、Authorization 等关键头/体字节级一致。

未引入新依赖 — 使用 conftest.py 已有的 ``client`` fixture + 项目已有的 ``respx``。
"""

from __future__ import annotations

import gzip
import json

import pytest
import respx
from httpx import Response

pytestmark = [pytest.mark.integration]

UPSTREAM = "http://upstream.example.com"
PROXY_BASE = "/api/v1/llm"


@pytest.mark.asyncio()
async def test_get_models_forwards_to_upstream(client):
    """GET /v1/models 应转发到上游 GET /v1/models,响应 JSON 透传。"""
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(host="upstream.example.com", path="/v1/models").mock(
            return_value=Response(
                200,
                json={
                    "object": "list",
                    "data": [{"id": "llama3", "object": "model", "owned_by": "user"}],
                },
            )
        )
        resp = await client.get(
            f"{PROXY_BASE}/v1/models",
            headers={"X-LLM-Provider-Url": UPSTREAM},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "list"
    assert body["data"][0]["id"] == "llama3"
    assert route.called
    assert route.calls[0].request.url.path == "/v1/models"


@pytest.mark.asyncio()
async def test_oversized_request_body_is_rejected_before_upstream(client, monkeypatch):
    """请求体超过代理上限时 fail-closed,且不得触达上游。"""
    import backend.api.llm_proxy_routes as proxy_routes

    monkeypatch.setattr(proxy_routes, "MAX_REQUEST_BODY_BYTES", 4)
    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        route = mock.post("/v1/chat/completions").mock(return_value=Response(200))
        resp = await client.post(
            f"{PROXY_BASE}/v1/chat/completions",
            headers={"X-LLM-Provider-Url": UPSTREAM},
            content=b"12345",
        )

    assert resp.status_code == 413
    assert resp.json()["detail"] == {
        "type": "request_body_too_large",
        "message": "The request body exceeds the maximum allowed size.",
    }
    assert not route.called


@pytest.mark.asyncio()
async def test_non_streaming_response_over_limit_returns_safe_error(client, monkeypatch):
    """非流式上游响应超过上限时不得在 proxy 内无限累积。"""
    import backend.api.llm_proxy_routes as proxy_routes

    monkeypatch.setattr(proxy_routes, "MAX_RESPONSE_BODY_BYTES", 4)
    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        route = mock.get("/v1/models").mock(return_value=Response(200, content=b"12345"))
        resp = await client.get(
            f"{PROXY_BASE}/v1/models",
            headers={"X-LLM-Provider-Url": UPSTREAM},
        )

    assert resp.status_code == 502
    assert resp.json()["detail"] == {
        "type": "response_body_too_large",
        "message": "The upstream response exceeds the maximum allowed size.",
    }
    assert route.called


@pytest.mark.asyncio()
async def test_non_streaming_decoded_response_does_not_forward_content_encoding(client):
    """解码后的非流式响应不能继续声明上游的压缩编码。"""
    body = b'{"object":"list","data":[]}'
    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        mock.get("/v1/models").mock(
            return_value=Response(
                200,
                content=gzip.compress(body),
                headers={"content-type": "application/json", "content-encoding": "gzip"},
            )
        )
        resp = await client.get(
            f"{PROXY_BASE}/v1/models",
            headers={"X-LLM-Provider-Url": UPSTREAM},
        )

    assert resp.status_code == 200
    assert resp.content == body
    assert "content-encoding" not in resp.headers


@pytest.mark.asyncio()
async def test_streaming_response_stops_at_cumulative_limit(client, monkeypatch):
    """流式响应累计越过上限时截断并关闭,不继续转发。"""
    import backend.api.llm_proxy_routes as proxy_routes

    monkeypatch.setattr(proxy_routes, "MAX_RESPONSE_BODY_BYTES", 4)
    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        mock.get("/v1/models").mock(return_value=Response(200, content=b"123456"))
        resp = await client.get(
            f"{PROXY_BASE}/v1/models?stream=true",
            headers={"X-LLM-Provider-Url": UPSTREAM},
        )

    assert resp.status_code == 200
    assert resp.content == b"123456"[:4]


@pytest.mark.asyncio()
async def test_streaming_decoded_response_does_not_forward_content_encoding(client):
    """解码后的流不能继续声明上游的压缩编码。"""
    chunks = b'data: {"choices": []}\n\n'
    compressed_chunks = gzip.compress(chunks)
    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        mock.post("/v1/chat/completions").mock(
            return_value=Response(
                200,
                content=compressed_chunks,
                headers={
                    "content-type": "text/event-stream",
                    "content-encoding": "gzip",
                },
            )
        )
        resp = await client.post(
            f"{PROXY_BASE}/v1/chat/completions?stream=true",
            headers={"X-LLM-Provider-Url": UPSTREAM},
            content=b"{}",
        )

    assert resp.status_code == 200
    assert resp.content == chunks
    assert "content-encoding" not in resp.headers


@pytest.mark.asyncio()
async def test_post_chat_forwards_body(client):
    """POST /v1/chat/completions 应携带 body 字节级转发。"""
    sent_body = {
        "model": "llama3",
        "messages": [{"role": "user", "content": "Hi"}],
        "max_tokens": 10,
    }
    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        route = mock.post("/v1/chat/completions").mock(
            return_value=Response(
                200,
                json={"id": "cmpl-1", "object": "chat.completion", "choices": []},
            )
        )
        resp = await client.post(
            f"{PROXY_BASE}/v1/chat/completions",
            headers={
                "X-LLM-Provider-Url": UPSTREAM,
                "Content-Type": "application/json",
            },
            json=sent_body,
        )

    assert resp.status_code == 200
    assert route.called
    received = json.loads(route.calls[0].request.content)
    assert received == sent_body


@pytest.mark.asyncio()
async def test_missing_header_returns_400(client):
    """缺 X-LLM-Provider-Url 应返 400 + missing_provider_url。"""
    resp = await client.get(f"{PROXY_BASE}/v1/models")

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["type"] == "missing_provider_url"
    assert "X-LLM-Provider-Url" in detail["message"]


@pytest.mark.asyncio()
async def test_invalid_url_returns_400(client):
    """X-LLM-Provider-Url 不是 http/https 应返 400 + invalid_provider_url。"""
    resp = await client.get(
        f"{PROXY_BASE}/v1/models",
        headers={"X-LLM-Provider-Url": "ftp://something"},
    )

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["type"] == "invalid_provider_url"


@pytest.mark.asyncio()
async def test_authorization_header_reaches_upstream(client):
    """Authorization 头应原样转发到上游(API key 透传)。"""
    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        route = mock.get("/v1/models").mock(
            return_value=Response(200, json={"object": "list", "data": []})
        )
        resp = await client.get(
            f"{PROXY_BASE}/v1/models",
            headers={
                "X-LLM-Provider-Url": UPSTREAM,
                "Authorization": "Bearer sk-test-xyz",
            },
        )

    assert resp.status_code == 200
    assert route.called
    assert route.calls[0].request.headers.get("authorization") == "Bearer sk-test-xyz"


@pytest.mark.asyncio()
async def test_local_capability_header_not_forwarded_but_provider_authorization_is(client):
    """本地 capability header 不得到达上游,provider Authorization 必须保留。"""
    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        route = mock.get("/v1/models").mock(
            return_value=Response(200, json={"object": "list", "data": []})
        )
        resp = await client.get(
            f"{PROXY_BASE}/v1/models",
            headers={
                "X-LLM-Provider-Url": UPSTREAM,
                "X-SAGE-LOCAL-AUTHORIZATION": "Bearer test-local-auth-token",
                "Authorization": "Bearer provider-key",
            },
        )

    assert resp.status_code == 200
    assert route.called
    upstream_headers = route.calls[0].request.headers
    assert upstream_headers.get("authorization") == "Bearer provider-key"
    assert "x-sage-local-authorization" not in upstream_headers


@pytest.mark.asyncio()
async def test_canonical_local_authorization_is_not_forwarded(client):
    """本地 canonical Bearer capability 不得泄露到公网 provider。"""
    local_token = "test-local-auth-token"
    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        route = mock.get("/v1/models").mock(
            return_value=Response(200, json={"object": "list", "data": []})
        )
        resp = await client.get(
            f"{PROXY_BASE}/v1/models",
            headers={
                "X-LLM-Provider-Url": UPSTREAM,
                "Authorization": f"bEaReR {local_token}",
            },
        )

    assert resp.status_code == 200
    assert route.called
    upstream_headers = route.calls[0].request.headers
    assert "authorization" not in upstream_headers
    assert local_token not in str(route.calls[0].request.headers)


@pytest.mark.asyncio()
async def test_local_compatibility_authorization_preserves_provider_authorization(client):
    """兼容本地 header 认证时，独立的 provider Authorization 仍应透传。"""
    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        route = mock.get("/v1/models").mock(
            return_value=Response(200, json={"object": "list", "data": []})
        )
        resp = await client.get(
            f"{PROXY_BASE}/v1/models",
            headers={
                "X-LLM-Provider-Url": UPSTREAM,
                "X-SAGE-LOCAL-AUTHORIZATION": "Bearer test-local-auth-token",
                "Authorization": "Bearer provider-key",
            },
        )

    assert resp.status_code == 200
    assert route.called
    upstream_headers = route.calls[0].request.headers
    assert upstream_headers.get("authorization") == "Bearer provider-key"
    assert "x-sage-local-authorization" not in upstream_headers


@pytest.mark.asyncio()
async def test_canonical_provider_authorization_is_forwarded(client):
    """不是本地 capability 的 canonical Authorization 应作为 provider key 透传。"""
    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        route = mock.get("/v1/models").mock(
            return_value=Response(200, json={"object": "list", "data": []})
        )
        resp = await client.get(
            f"{PROXY_BASE}/v1/models",
            headers={
                "X-LLM-Provider-Url": UPSTREAM,
                "Authorization": "Bearer provider-key",
            },
        )

    assert resp.status_code == 200
    assert route.called
    assert route.calls[0].request.headers.get("authorization") == "Bearer provider-key"


@pytest.mark.asyncio()
async def test_query_string_forwarded(client):
    """查询串应原样转发到上游。"""
    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        route = mock.get("/v1/models").mock(
            return_value=Response(200, json={"object": "list", "data": []})
        )
        resp = await client.get(
            f"{PROXY_BASE}/v1/models",
            params={"foo": "bar", "limit": "10"},
            headers={"X-LLM-Provider-Url": UPSTREAM},
        )

    assert resp.status_code == 200
    assert route.called
    assert route.calls[0].request.url.params.get("foo") == "bar"
    assert route.calls[0].request.url.params.get("limit") == "10"


@pytest.mark.asyncio()
async def test_upstream_4xx_returns_safe_error(client):
    """上游 401 保留状态码和错误类型,但不回显敏感 body。"""
    sensitive_body = '{"error":"invalid key sk-upstream-secret"}'
    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        mock.get("/v1/models").mock(return_value=Response(401, text=sensitive_body))
        resp = await client.get(
            f"{PROXY_BASE}/v1/models?token=query-secret",
            headers={"X-LLM-Provider-Url": UPSTREAM},
        )

    assert resp.status_code == 401
    detail = resp.json()["detail"]
    assert detail == {
        "type": "upstream_error",
        "message": "Upstream returned HTTP 401.",
    }
    assert "provider-secret" not in resp.text
    assert "query-secret" not in resp.text
    assert "sk-upstream-secret" not in resp.text


@pytest.mark.asyncio()
async def test_upstream_5xx_returns_safe_error(client):
    """上游 500 保留状态码和错误类型,但不回显错误 body。"""
    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        mock.get("/v1/models").mock(
            return_value=Response(500, text="authorization=Bearer upstream-secret")
        )
        resp = await client.get(
            f"{PROXY_BASE}/v1/models",
            headers={"X-LLM-Provider-Url": UPSTREAM},
        )

    assert resp.status_code == 500
    assert resp.json()["detail"]["type"] == "upstream_error"
    assert "upstream-secret" not in resp.text


@pytest.mark.asyncio()
async def test_provider_url_header_not_forwarded(client):
    """X-LLM-Provider-Url 不应被转发到上游(避免循环引用)。"""
    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        route = mock.get("/v1/models").mock(
            return_value=Response(200, json={"object": "list", "data": []})
        )
        resp = await client.get(
            f"{PROXY_BASE}/v1/models",
            headers={"X-LLM-Provider-Url": UPSTREAM},
        )

    assert resp.status_code == 200
    assert route.called
    assert "x-llm-provider-url" not in route.calls[0].request.headers


@pytest.mark.asyncio()
async def test_dotdot_path_normalized_to_root(client):
    """``..`` 路径段经 ``posixpath.normpath`` 折叠 — 永远不会逃出上游根(根级变 ``/``)。

    裸 ``..`` → normpath → ``/``。本测试验证它会**被规范化**,而不是被 400 拒绝,
    也验证请求不会打到非预期路径。
    """
    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        route = mock.get("/").mock(return_value=Response(200, json={"root": True}))
        resp = await client.get(
            f"{PROXY_BASE}/%2E%2E",
            headers={"X-LLM-Provider-Url": UPSTREAM},
        )

    assert resp.status_code == 200
    assert route.called
    # normpath 之后变成根
    assert route.calls[0].request.url.path == "/"


@pytest.mark.asyncio()
async def test_userinfo_in_provider_url_rejected(client):
    """带 userinfo 的 URL(``user:pass@host``)应被拒绝(防止凭据泄露到 log)。"""
    resp = await client.get(
        f"{PROXY_BASE}/v1/models",
        headers={"X-LLM-Provider-Url": "http://user:secret@host:11434"},
    )

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["type"] == "invalid_provider_url"
    assert "userinfo" in detail["message"]


@pytest.mark.asyncio()
async def test_malformed_provider_url_returns_safe_detail(client):
    """URL 解析异常不得把凭据或完整 URL 放入客户端 detail。"""
    provider = "http://user:pass@upstream.example.com:bad-port?token=bad-url-secret"
    resp = await client.get(
        f"{PROXY_BASE}/v1/models",
        headers={"X-LLM-Provider-Url": provider},
    )

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["type"] == "invalid_provider_url"
    assert detail["message"] == "X-LLM-Provider-Url is not a valid URL"
    assert "pass" not in resp.text
    assert "bad-url-secret" not in resp.text


@pytest.mark.asyncio()
async def test_provider_url_is_redacted_in_proxy_logs(client, caplog):
    """日志不得包含 provider URL 的 userinfo 或完整路径/query。"""
    import logging

    provider = "http://user:secret@upstream.example.com/private/v1?token=secret"
    with caplog.at_level(logging.INFO):
        resp = await client.get(
            f"{PROXY_BASE}/v1/models",
            headers={"X-LLM-Provider-Url": provider},
        )

    assert resp.status_code == 400
    assert "secret" not in caplog.text
    assert "X-LLM-Provider-Url=" not in caplog.text


@pytest.mark.asyncio()
async def test_upstream_timeout_returns_504(client):
    """httpx.TimeoutException 应映射为 504 upstream_timeout。"""
    import httpx as _httpx

    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        mock.get("/v1/models").mock(side_effect=_httpx.TimeoutException("slow"))
        resp = await client.get(
            f"{PROXY_BASE}/v1/models",
            headers={"X-LLM-Provider-Url": UPSTREAM},
        )

    assert resp.status_code == 504
    assert resp.json()["detail"]["type"] == "upstream_timeout"


@pytest.mark.asyncio()
async def test_upstream_connect_error_returns_502(client):
    """httpx.ConnectError 应映射为 502 upstream_unreachable。"""
    import httpx as _httpx

    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        mock.get("/v1/models").mock(side_effect=_httpx.ConnectError("nope"))
        resp = await client.get(
            f"{PROXY_BASE}/v1/models",
            headers={"X-LLM-Provider-Url": UPSTREAM},
        )

    assert resp.status_code == 502
    assert resp.json()["detail"]["type"] == "upstream_unreachable"


@pytest.mark.asyncio()
async def test_upstream_transport_error_returns_502(client):
    """其它 httpx.TransportError(half-close 等)应映射为 502 upstream_transport_error。"""
    import httpx as _httpx

    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        mock.get("/v1/models").mock(side_effect=_httpx.RemoteProtocolError("half close"))
        resp = await client.get(
            f"{PROXY_BASE}/v1/models",
            headers={"X-LLM-Provider-Url": UPSTREAM},
        )

    assert resp.status_code == 502
    assert resp.json()["detail"]["type"] == "upstream_transport_error"


@pytest.mark.asyncio()
async def test_transport_failure_does_not_log_or_return_sensitive_exception_text(client, caplog):
    """传输异常中的 URL/query/token 不得进入日志或客户端 detail。"""
    import logging

    import httpx as _httpx

    sensitive = "https://user:pass@upstream.example.com/v1/models?token=exception-secret"
    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        mock.get("/v1/models").mock(
            side_effect=_httpx.RemoteProtocolError(
                f"connection failed for {sensitive} Authorization=Bearer auth-secret"
            )
        )
        with caplog.at_level(logging.WARNING):
            resp = await client.get(
                f"{PROXY_BASE}/v1/models?token=query-secret",
                headers={
                    "X-LLM-Provider-Url": UPSTREAM,
                    "Authorization": "Bearer auth-secret",
                },
            )

    assert resp.status_code == 502
    assert resp.json()["detail"] == {
        "type": "upstream_transport_error",
        "message": "The upstream request failed during transport.",
    }
    for secret in ("exception-secret", "provider-secret", "query-secret", "auth-secret"):
        assert secret not in resp.text
        assert secret not in caplog.text


@pytest.mark.asyncio()
async def test_nested_path_normalized(client):
    """path 含 ``..`` 但最终不逃出根(``v1/../v1/models`` → ``/v1/models``)应正常转发。"""
    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        route = mock.get("/v1/models").mock(
            return_value=Response(200, json={"object": "list", "data": []})
        )
        resp = await client.get(
            f"{PROXY_BASE}/v1/../v1/models",
            headers={"X-LLM-Provider-Url": UPSTREAM},
        )

    assert resp.status_code == 200
    assert route.called
    # normpath 之后应是 /v1/models
    assert route.calls[0].request.url.path == "/v1/models"


# ============================================================================
# v2: SSE 流式透传
# ============================================================================


@pytest.mark.asyncio()
async def test_streaming_detected_by_accept_header_routes_to_streaming(client):
    """v2: ``Accept: text/event-stream`` 应触发流式分支,proxy 走 httpx.stream().

    由于 respx mock 上游返回的是一次性 Response 而不是真正的 stream,
    这里只验证 proxy 不抛错 + 调用了上游 + 把响应字节级透传(此时上游
    Response 一次性读完,StreamingResponse 也是一次性 yield 整段内容)。
    """
    sent_body = {
        "model": "llama3",
        "messages": [{"role": "user", "content": "Hi"}],
        "stream": True,
    }
    chunks = b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\ndata: [DONE]\n\n'
    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        route = mock.post("/v1/chat/completions").mock(
            return_value=Response(
                200,
                content=chunks,
                headers={"content-type": "text/event-stream"},
            )
        )
        resp = await client.post(
            f"{PROXY_BASE}/v1/chat/completions",
            headers={
                "X-LLM-Provider-Url": UPSTREAM,
                "Accept": "text/event-stream",
                "Content-Type": "application/json",
            },
            content=json.dumps(sent_body).encode(),
        )

    assert resp.status_code == 200
    assert route.called
    # 字节级透传(因为上游一次性返回,StreamingResponse 也是一次性 yield)
    assert resp.content == chunks


@pytest.mark.asyncio()
async def test_streaming_detected_by_query_param_routes_to_streaming(client):
    """v2: query string ``?stream=true`` 应触发流式分支(OpenAI 流式约定)."""
    sent_body = {
        "model": "llama3",
        "messages": [{"role": "user", "content": "Hi"}],
        "stream": True,
    }
    chunks = b'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\ndata: [DONE]\n\n'
    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        route = mock.post("/v1/chat/completions").mock(
            return_value=Response(
                200,
                content=chunks,
                headers={"content-type": "application/json"},
            )
        )
        resp = await client.post(
            f"{PROXY_BASE}/v1/chat/completions?stream=true",
            headers={
                "X-LLM-Provider-Url": UPSTREAM,
                "Content-Type": "application/json",
            },
            content=json.dumps(sent_body).encode(),
        )

    assert resp.status_code == 200
    assert route.called
    assert resp.content == chunks


@pytest.mark.asyncio()
async def test_streaming_upstream_error_returns_status_code(client):
    """v2: 流式分支遇到上游 4xx/5xx,应在 yield 任何 chunk 之前抛 HTTPException,
    让调用方拿到正确的 status code(不是 200)。"""
    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        mock.post("/v1/chat/completions").mock(
            return_value=Response(
                401,
                content=b'{"error":{"message":"Invalid API key"}}',
                headers={"content-type": "application/json"},
            )
        )
        resp = await client.post(
            f"{PROXY_BASE}/v1/chat/completions",
            headers={
                "X-LLM-Provider-Url": UPSTREAM,
                "Accept": "text/event-stream",
                "Content-Type": "application/json",
            },
            content=b'{"model":"x","messages":[],"stream":true}',
        )

    assert resp.status_code == 401
    detail = resp.json()["detail"]
    assert detail["type"] == "upstream_error"
    assert "401" in detail["message"]


@pytest.mark.asyncio()
async def test_non_streaming_path_unchanged(client):
    """回归门禁: 非流式请求(Accept: application/json, 无 stream=true)
    仍然走原有非流式分支 — 不会被误判成 streaming。
    """
    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        route = mock.post("/v1/chat/completions").mock(
            return_value=Response(
                200,
                json={
                    "id": "x",
                    "choices": [{"message": {"role": "assistant", "content": "Hi"}}],
                },
            )
        )
        resp = await client.post(
            f"{PROXY_BASE}/v1/chat/completions",
            headers={
                "X-LLM-Provider-Url": UPSTREAM,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            content=b'{"model":"x","messages":[{"role":"user","content":"hi"}]}',
        )

    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == "Hi"
    assert route.called


@pytest.mark.asyncio()
async def test_dns_rebinding_does_not_connect_to_later_private_answer(client, monkeypatch):
    """Validation and connect use the same public address, never a later private DNS answer."""
    import socket

    import backend.api.llm_proxy_routes as proxy_routes

    answers = [("8.8.8.8",), ("127.0.0.1",)]
    seen = []

    def rebinding_getaddrinfo(host, *args, **kwargs):
        answer = answers[min(len(seen), len(answers) - 1)]
        seen.append(answer[0])
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (answer[0], args[0] if args else 80))]

    monkeypatch.setattr(proxy_routes.socket, "getaddrinfo", rebinding_getaddrinfo)
    with respx.mock(base_url="http://rebinding.example.com", assert_all_called=False) as mock:
        route = mock.get("/v1/models").mock(return_value=Response(200, json={"data": []}))
        response = await client.get(
            f"{PROXY_BASE}/v1/models",
            headers={"X-LLM-Provider-Url": "http://rebinding.example.com"},
        )
    assert response.status_code == 200
    assert route.called
    assert seen == ["8.8.8.8"]


@pytest.mark.asyncio()
async def test_allowlisted_local_host_is_pinned_and_allowed(client, monkeypatch):
    import socket

    import backend.api.llm_proxy_routes as proxy_routes

    monkeypatch.setenv("SAGE_LLM_PROXY_ALLOWED_HOSTS", "local.example.com")
    calls = []

    def local_getaddrinfo(host, *args, **kwargs):
        calls.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", args[0] if args else 80))]

    monkeypatch.setattr(proxy_routes.socket, "getaddrinfo", local_getaddrinfo)
    with respx.mock(base_url="http://local.example.com", assert_all_called=False) as mock:
        route = mock.get("/v1/models").mock(return_value=Response(200, json={"data": []}))
        response = await client.get(
            f"{PROXY_BASE}/v1/models",
            headers={"X-LLM-Provider-Url": "http://local.example.com"},
        )
    assert response.status_code == 200
    assert route.called
    assert calls == ["local.example.com"]


@pytest.mark.asyncio()
async def test_public_https_preserves_hostname_for_host_and_sni(client, monkeypatch):
    import socket

    import backend.api.llm_proxy_routes as proxy_routes

    monkeypatch.setattr(proxy_routes.socket, "getaddrinfo", lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))
    ])
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get("https://secure.example.com/v1/models").mock(return_value=Response(200, json={"data": []}))
        response = await client.get(
            f"{PROXY_BASE}/v1/models",
            headers={"X-LLM-Provider-Url": "https://secure.example.com"},
        )
    assert response.status_code == 200
    assert route.called
    sent = route.calls[0].request
    assert sent.url.host == "secure.example.com"
    assert sent.headers["host"] == "secure.example.com"


#
# 覆盖：
# 1. LM Studio 本地端点 ``http://127.0.0.1:1234/v1`` + 空 Authorization 透传
# 2. baseURL 已含 ``/v1`` + path 以 ``/v1`` 开头 → 不重复 ``/v1/v1``
# 3. SSE ``data:`` chunks 完整透传 (OpenAI 流式协议)
# 4. 非流式 ``/v1/chat/completions`` 接受空 Authorization
# 5. TLS 错误结构化分类 (verify=True 不变 — httpx 永不关闭校验)


LM_STUDIO = "http://127.0.0.1:1234/v1"
# respx ``base_url`` 不含 ``/v1`` 后缀, 否则 base_url + path 会拼出 ``/v1/v1/...``;
# ``build_upstream_url`` 已经把 ``/v1`` 去重, 所以上游 URL 是单 v1。
LM_STUDIO_BASE = "http://127.0.0.1:1234"


@pytest.fixture(autouse=True)
def _allow_test_local_provider(monkeypatch):
    """Model the explicit user opt-in required for local providers."""
    monkeypatch.setenv("SAGE_LLM_PROXY_ALLOWED_HOSTS", "127.0.0.1")


@pytest.fixture(autouse=True)
def _resolve_mock_provider_names(monkeypatch):
    """Give respx-only provider names a deterministic public test address."""
    import socket

    original = socket.getaddrinfo

    def getaddrinfo(host, *args, **kwargs):
        if host in {"upstream.example.com", "public.example.com"}:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", args[0] if args else 80))]
        return original(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


@pytest.mark.asyncio()
async def test_blocked_local_target_requires_explicit_allowlist(client, monkeypatch):
    monkeypatch.delenv("SAGE_LLM_PROXY_ALLOWED_HOSTS", raising=False)
    resp = await client.get(
        f"{PROXY_BASE}/v1/models",
        headers={"X-LLM-Provider-Url": "http://127.0.0.1:11434"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == {
        "type": "blocked_provider_target",
        "message": "The upstream target is not allowed.",
    }


@pytest.mark.asyncio()
async def test_rfc1918_and_metadata_targets_are_blocked(client):
    for host in ("10.0.0.1", "192.168.1.5", "169.254.169.254", "[::1]"):
        resp = await client.get(
            f"{PROXY_BASE}/v1/models",
            headers={"X-LLM-Provider-Url": f"http://{host}:11434"},
        )
        assert resp.status_code == 403


@pytest.mark.asyncio()
async def test_public_provider_remains_allowed(client):
    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        route = mock.get("/v1/models").mock(return_value=Response(200, json={"data": []}))
        resp = await client.get(
            f"{PROXY_BASE}/v1/models",
            headers={"X-LLM-Provider-Url": UPSTREAM},
        )
    assert resp.status_code == 200
    assert route.called



    """LM Studio 本地端点 GET /v1/models: 无 Authorization header 时仍 200,
    且 respx mock 收到上游空 Authorization(浏览器不发 ``Bearer ``)而非 ``null``.
    """
    with respx.mock(base_url=LM_STUDIO_BASE, assert_all_called=False) as mock:
        route = mock.get("/v1/models").mock(
            return_value=Response(
                200,
                json={
                    "object": "list",
                    "data": [{"id": "qwen2.5-7b-instruct", "object": "model"}],
                },
            )
        )
        resp = await client.get(
            f"{PROXY_BASE}/v1/models",
            headers={"X-LLM-Provider-Url": LM_STUDIO},
        )

    assert resp.status_code == 200
    assert resp.json()["data"][0]["id"] == "qwen2.5-7b-instruct"
    assert route.called
    # 上游收到的 Authorization 应为空(None) — 浏览器没发 ``Bearer `` 噪音
    auth = route.calls[0].request.headers.get("authorization")
    assert auth is None or auth == ""


@pytest.mark.asyncio()
async def test_baseurl_with_v1_suffix_does_not_double_v1_in_path(client):
    """LM Studio baseURL 已含 ``/v1``, 浏览器拉 ``/v1/models`` → 上游不应收到 ``/v1/v1/models``.

    ``build_upstream_url`` 已在 ``test_llm_proxy_url.py`` 单元测试覆盖;
    这里验证整条链路: 浏览器请求 → proxy → 上游.
    """
    with respx.mock(base_url=LM_STUDIO_BASE, assert_all_called=False) as mock:
        route = mock.get("/v1/models").mock(
            return_value=Response(200, json={"object": "list", "data": []})
        )
        resp = await client.get(
            f"{PROXY_BASE}/v1/models",
            headers={"X-LLM-Provider-Url": LM_STUDIO},
        )

    assert resp.status_code == 200
    assert route.called
    # 上游 path 应是 ``/v1/models`` (单 v1), 不是 ``/v1/v1/models``
    assert route.calls[0].request.url.path == "/v1/models"


@pytest.mark.asyncio()
async def test_lm_studio_non_streaming_chat_with_empty_authorization(client):
    """LM Studio 非流式 POST /v1/chat/completions: 空 Authorization → 上游收到空."""
    with respx.mock(base_url=LM_STUDIO_BASE, assert_all_called=False) as mock:
        route = mock.post("/v1/chat/completions").mock(
            return_value=Response(
                200,
                json={
                    "id": "cmpl-1",
                    "choices": [{"message": {"role": "assistant", "content": "Hi"}}],
                },
            )
        )
        resp = await client.post(
            f"{PROXY_BASE}/v1/chat/completions",
            headers={
                "X-LLM-Provider-Url": LM_STUDIO,
                "Content-Type": "application/json",
            },
            content=b'{"model":"qwen2.5-7b-instruct","messages":[{"role":"user","content":"hi"}]}',
        )

    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == "Hi"
    assert route.called
    auth = route.calls[0].request.headers.get("authorization")
    assert auth is None or auth == ""


@pytest.mark.asyncio()
async def test_lm_studio_streaming_sse_chunks_preserved(client):
    """LM Studio 流式 SSE: 完整 ``data: {...}\\n\\n`` chunk 序列应字节级透传."""
    chunks = (
        b'data: {"choices":[{"delta":{"content":"Hello"},"index":0}]}\n\n'
        b'data: {"choices":[{"delta":{"content":" LM"},"index":0}]}\n\n'
        b'data: {"choices":[{"delta":{"content":" Studio"},"index":0}]}\n\n'
        b'data: [DONE]\n\n'
    )
    with respx.mock(base_url=LM_STUDIO_BASE, assert_all_called=False) as mock:
        route = mock.post("/v1/chat/completions").mock(
            return_value=Response(
                200,
                content=chunks,
                headers={"content-type": "text/event-stream"},
            )
        )
        resp = await client.post(
            f"{PROXY_BASE}/v1/chat/completions?stream=true",
            headers={
                "X-LLM-Provider-Url": LM_STUDIO,
                "Content-Type": "application/json",
            },
            content=b'{"model":"qwen2.5-7b-instruct","messages":[{"role":"user","content":"hi"}],"stream":true}',
        )

    assert resp.status_code == 200
    assert route.called
    # 字节级透传: 完整 SSE 序列(包括末尾 [DONE])应出现在响应体
    assert resp.content == chunks
    assert b"data: [DONE]\n\n" in resp.content


@pytest.mark.asyncio()
async def test_streaming_upstream_disconnect_after_first_chunk_closes_context(client, monkeypatch):
    """首个 chunk 已发出后上游传输异常只能截断流, 但必须 close 且不二次写 status."""
    import backend.api.llm_proxy_routes as proxy_routes

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/event-stream"}
        is_success = True

        # 2026-09-02 修复: stream_iter 改用 aiter_bytes 让 httpx 透明解压,
        # FakeResponse 需要补 aiter_bytes (与 aiter_raw 行为一致, 测试只关心
        # "上游断开是否能截断流", 不区分 chunk 来源是 raw 还是解压后)。
        async def aiter_raw(self):
            yield b"data: first\\n\\n"
            raise RuntimeError("upstream disconnected after first chunk")

        async def aiter_bytes(self):
            async for chunk in self.aiter_raw():
                yield chunk

    class FakeRequestContext:
        def __init__(self):
            self.exit_calls = []

        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, exc_type, exc, tb):
            self.exit_calls.append((exc_type, exc))
            return False

    fake_ctx = FakeRequestContext()

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def stream(self, *args, **kwargs):
            return fake_ctx

    monkeypatch.setattr(proxy_routes.httpx, "AsyncClient", FakeClient)
    response = await proxy_routes._proxy_streaming(
        "http://upstream.example.com/v1/chat/completions",
        "POST",
        {},
        b"{}",
    )

    chunks = []
    async def collect_chunks():
        async for chunk in response.body_iterator:
            chunks.append(chunk)

    with pytest.raises(RuntimeError, match="upstream disconnected"):
        await collect_chunks()

    assert chunks == [b"data: first\\n\\n"]
    assert len(fake_ctx.exit_calls) == 1
    exc_type, exc = fake_ctx.exit_calls[0]
    assert exc_type is RuntimeError
    assert isinstance(exc, RuntimeError)


@pytest.mark.asyncio()
async def test_proxy_uses_certifi_ca_bundle_for_https(client):
    """Task 1 §4: 代理始终启用证书校验 — ``httpx.AsyncClient`` 走 ``SSL_CERT_FILE``
    / ``REQUESTS_CA_BUNDLE`` / ``CURL_CA_BUNDLE`` 任一环境变量, 由 ``main.py``
    ``configure_ssl_ca_bundle(certifi.where)`` 在 import-time 注入.

    此测试只验证 import-time 注入在测试进程里发生过 (即环境变量被设置),
    不实际建立 TLS 连接(避免本地无 certifi 时 CI flake).
    """
    import os

    # 任一变量非空即可 — 不同平台 certifi 路径不同, 三选一有值就算成功
    bundle_vars = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")
    set_vars = [v for v in bundle_vars if os.environ.get(v)]
    # conftest 已 import backend.main → ``configure_ssl_ca_bundle`` 应跑过
    # 如果 certifi 可用 (sage-backend 依赖里包含 certifi), 至少一个变量被设置
    assert set_vars, (
        "expected at least one of SSL_CERT_FILE/REQUESTS_CA_BUNDLE/CURL_CA_BUNDLE "
        "to be set by configure_ssl_ca_bundle(); backend.main must be imported "
        "before this assertion runs"
    )


@pytest.mark.asyncio()
async def test_tls_certificate_error_returns_structured_detail(client):
    """Task 1 §4: 上游 TLS 证书校验失败应映射为 ``tls_certificate_failed``
    结构化 detail (状态码 502) — 不应被映射成 ``upstream_unreachable`` 把 TLS 错误淹没."""
    import httpx as _httpx

    # ``httpx`` 在证书校验失败时抛 ``httpcore.ConnectError`` 包装的 SSLError.
    # respx 的 side_effect 直接注入 ``httpx.ConnectError`` 即可,
    # 后续 proxy 的 except 分支应识别消息含 ``certificate`` 关键字升级为 tls_certificate_failed.
    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        mock.get("/v1/models").mock(side_effect=_httpx.ConnectError("certificate verify failed"))
        resp = await client.get(
            f"{PROXY_BASE}/v1/models",
            headers={"X-LLM-Provider-Url": UPSTREAM},
        )

    assert resp.status_code == 502
    detail = resp.json()["detail"]
    # Task 1 round 1 (2026-08-24): 收紧断言 — 之前 ``in {tls_certificate_failed, upstream_unreachable}``
    # 太宽松, 让字符串含 "certificate" 的 ConnectError 可能误判走 upstream_unreachable 也能通过.
    # 现在强制要求 ``tls_certificate_failed``, 因为 ``_is_tls_certificate_error`` 的
    # 字符串匹配兜底会把 "certificate verify failed" 升级. 如果这条挂了说明上游 TLS
    # 检测被静默降级为通用连接错误 — 修 proxy, 不要回退断言.
    assert detail["type"] == "tls_certificate_failed", (
        f"expected tls_certificate_failed, got {detail['type']!r}; "
        f"_is_tls_certificate_error must match the 'certificate verify failed' substring"
    )
    # 不论哪种 type, 都不应包含 API key / 凭据
    body_text = resp.text
    assert "sk-" not in body_text
    assert "Bearer " not in body_text
