"""LLM 代理路由集成测试。

验证 ``/api/v1/llm/*`` 把请求透传到 ``X-LLM-Provider-Url`` 头部指定的上游,
并保持方法、请求体、查询串、Authorization 等关键头/体字节级一致。

未引入新依赖 — 使用 conftest.py 已有的 ``client`` fixture + 项目已有的 ``respx``。
"""

from __future__ import annotations

import json

import pytest
import respx
from httpx import Response

pytestmark = pytest.mark.integration

UPSTREAM = "http://upstream.example.com"
PROXY_BASE = "/api/v1/llm"


@pytest.mark.asyncio()
async def test_get_models_forwards_to_upstream(client):
    """GET /v1/models 应转发到上游 GET /v1/models,响应 JSON 透传。"""
    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        route = mock.get("/v1/models").mock(
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
async def test_upstream_4xx_passes_through(client):
    """上游 401 应原样透传给客户端(状态码 + body)。"""
    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        mock.get("/v1/models").mock(return_value=Response(401, json={"error": "bad key"}))
        resp = await client.get(
            f"{PROXY_BASE}/v1/models",
            headers={"X-LLM-Provider-Url": UPSTREAM},
        )

    assert resp.status_code == 401
    assert resp.json() == {"error": "bad key"}


@pytest.mark.asyncio()
async def test_upstream_5xx_passes_through(client):
    """上游 500 应原样透传给客户端。"""
    with respx.mock(base_url=UPSTREAM, assert_all_called=False) as mock:
        mock.get("/v1/models").mock(return_value=Response(500, text="internal error"))
        resp = await client.get(
            f"{PROXY_BASE}/v1/models",
            headers={"X-LLM-Provider-Url": UPSTREAM},
        )

    assert resp.status_code == 500
    assert "internal error" in resp.text


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
