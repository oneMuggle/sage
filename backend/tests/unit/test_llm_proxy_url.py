"""``backend.api.llm_proxy_routes.build_upstream_url`` 纯函数单元测试。

设计背景:
  - 用户在「端点」UI 输入 baseURL(常见: ``https://api.openai.com/v1``)
  - 前端 ``fetchModels`` 固定请求 ``/v1/models``
  - 后端代理要把 baseURL + path 拼成上游 URL
  - 若 baseURL 已含 ``/v1`` 后缀,path 又以 ``/v1`` 开头,会拼成
    ``.../v1/v1/models`` 触发上游 404 (Invalid URL)。

修复策略(方案 A):
  在 ``build_upstream_url(provider_url, path)`` 里:
    1. 归一化 provider_url(去末尾 ``/``)
    2. 归一化 path(``posixpath.normpath('/' + path.lstrip('/'))``)
    3. 若 provider_url 以 ``/v1`` 结尾,且 normalized path 以 ``/v1/`` 开头
       (或 path == ``/v1``),剥掉 path 前导的 ``/v1`` 段。

覆盖场景:
  - 用户填 baseURL 含 ``/v1`` + 前端拉模型列表 → 不能变成 ``/v1/v1/models``
  - 用户填裸 host + 前端拉模型列表 → 行为不变(向后兼容)
  - 用户填 baseURL 含 ``/v1`` + 自定义 path(非 /v1) → path 应原样保留
  - query string 应原样附加
"""

from __future__ import annotations

import socket

import httpcore
import pytest

from backend.api.llm_proxy_routes import build_upstream_url


class _RecordingBackend(httpcore.AsyncNetworkBackend):
    def __init__(self):
        self.calls = []

    async def connect_tcp(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return object()

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise NotImplementedError

    async def sleep(self, seconds):
        return None


@pytest.mark.asyncio()
async def test_fixed_ip_backend_always_connects_to_pinned_address():
    from backend.api.llm_proxy_routes import _FixedIPNetworkBackend

    backend = _FixedIPNetworkBackend("203.0.113.8")
    delegate = _RecordingBackend()
    backend._delegate = delegate

    await backend.connect_tcp("provider.example", 443, timeout=2.0)

    assert delegate.calls == [
        (("203.0.113.8", 443), {"timeout": 2.0, "local_address": None, "socket_options": None})
    ]


@pytest.mark.asyncio()
async def test_resolver_validates_all_addresses_and_pins_deterministically(monkeypatch):
    import backend.api.llm_proxy_routes as proxy_routes

    monkeypatch.setattr(
        proxy_routes,
        "_resolve_addresses",
        lambda host, port: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", port)),
        ],
    )
    parsed = proxy_routes.urlparse("https://provider.example")

    assert await proxy_routes._resolve_and_validate_upstream_host(parsed) == "1.1.1.1"


@pytest.mark.asyncio()
async def test_resolver_allows_private_addresses_only_for_allowlisted_host(monkeypatch):
    import backend.api.llm_proxy_routes as proxy_routes

    monkeypatch.setattr(
        proxy_routes,
        "_resolve_addresses",
        lambda host, port: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.20", port))
        ],
    )
    parsed = proxy_routes.urlparse("http://lan.example")
    with pytest.raises(proxy_routes.HTTPException) as blocked:
        await proxy_routes._resolve_and_validate_upstream_host(parsed)
    assert blocked.value.status_code == 403

    monkeypatch.setenv("SAGE_LLM_PROXY_ALLOWED_HOSTS", "lan.example")
    assert await proxy_routes._resolve_and_validate_upstream_host(parsed) == "192.168.1.20"

@pytest.mark.asyncio()
async def test_resolver_dns_timeout_maps_to_gaierror(monkeypatch):
    import asyncio

    import backend.api.llm_proxy_routes as proxy_routes

    async def delayed_wait_for(*args, **kwargs):
        raise asyncio.TimeoutError()  # noqa: UP041

    monkeypatch.setattr(proxy_routes.asyncio, "wait_for", delayed_wait_for)
    with pytest.raises(socket.gaierror):
        await proxy_routes._resolve_and_validate_upstream_host(
            proxy_routes.urlparse("https://timeout.example")
        )


@pytest.mark.asyncio()
async def test_resolver_rejects_when_dns_concurrency_is_saturated(monkeypatch):
    """DNS waiters fail closed instead of growing an unbounded queue."""
    import asyncio
    import backend.api.llm_proxy_routes as proxy_routes

    monkeypatch.setattr(proxy_routes, "_DNS_SEMAPHORE", asyncio.Semaphore(0))
    with pytest.raises(socket.gaierror, match="DNS resolution capacity"):
        await proxy_routes._resolve_and_validate_upstream_host(
            proxy_routes.urlparse("https://busy.example")
        )


def test_provider_url_with_v1_suffix_and_v1_models_path_does_not_duplicate():
    """base URL 和 path 都含 ``/v1`` 时不得重复拼接。"""
    url = build_upstream_url(
        provider_url="https://apihub.agnes-ai.com/v1",
        path="v1/models",
    )

    assert url == "https://apihub.agnes-ai.com/v1/models"


def test_provider_url_with_v1_suffix_and_chat_completions_path_does_not_duplicate():
    """同样的去重要对 ``/v1/chat/completions`` 生效。"""
    url = build_upstream_url(
        provider_url="https://api.openai.com/v1/",
        path="v1/chat/completions",
    )

    assert url == "https://api.openai.com/v1/chat/completions"


# === 向后兼容:裸 host 不能被新逻辑破坏 ===


def test_bare_host_provider_url_with_v1_models_path_still_works():
    """兼容已有集成测试 ``UPSTREAM = 'http://upstream.example.com'``(裸 host)。"""
    url = build_upstream_url(
        provider_url="http://upstream.example.com",
        path="v1/models",
    )

    assert url == "http://upstream.example.com/v1/models"


# === 非 /v1 路径:不应被错误剥前缀 ===


def test_provider_url_with_v1_suffix_and_non_v1_path_preserves_path():
    """若 path 不是 ``/v1`` 开头,即使 baseURL 含 ``/v1`` 也不应去重。"""
    url = build_upstream_url(
        provider_url="https://example.com/v1",
        path="custom/models",
    )

    assert url == "https://example.com/v1/custom/models"


# === query string ===


def test_query_string_is_appended():
    url = build_upstream_url(
        provider_url="https://api.openai.com/v1",
        path="v1/models",
        query="limit=10&after=foo",
    )

    assert url == "https://api.openai.com/v1/models?limit=10&after=foo"


# === Task 1 (2026-08-23): LM Studio / edge cases ===


def test_lm_studio_baseurl_with_v1_suffix_and_v1_models():
    """LM Studio 本地 ``http://127.0.0.1:1234/v1`` + 拉 ``/v1/models`` → 不能拼成 ``/v1/v1/models``."""
    url = build_upstream_url(
        provider_url="http://127.0.0.1:1234/v1",
        path="v1/models",
    )

    assert url == "http://127.0.0.1:1234/v1/models"


def test_provider_url_with_v1_suffix_and_path_just_v1_collapse_to_root():
    """baseURL 含 ``/v1`` + path 仅为 ``/v1`` → 折叠到根 ``/`` (允许尾部 ``/``)."""
    url = build_upstream_url(
        provider_url="https://api.example.com/v1",
        path="v1",
    )

    assert url.rstrip("/") == "https://api.example.com/v1"


def test_provider_url_with_v1_suffix_and_chat_completions_stream_query():
    """baseURL 含 ``/v1`` + 流式 ``/v1/chat/completions?stream=true`` → 单 v1 + query 保留."""
    url = build_upstream_url(
        provider_url="http://127.0.0.1:1234/v1",
        path="v1/chat/completions",
        query="stream=true",
    )

    assert url == "http://127.0.0.1:1234/v1/chat/completions?stream=true"
