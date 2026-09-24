"""R117 — upstream_security（SSRF 防护层）单元测试。

覆盖：私网/环回/链路本地地址判定、env 白名单归一、DNS 解析校验全路径
（无 host / 字面量私网 / rebinding / 解析失败 / 超时 / 空结果 / 容量耗尽 /
端口默认值 / pinned IP 成功）、固定 IP 传输后端的连接重定向与版本门、
响应体限额读（content-length 预检 / 非法值忽略 / 流式累计超限 / 恰好上限）。
全部用 fake resolver 与 duck-typed 响应替身，不发真实网络请求。
"""

from __future__ import annotations

import asyncio
import re
import socket
import time
from urllib.parse import urlparse

import httpcore
import httpx
import pytest

import backend.api.upstream_security as us
from backend.api.upstream_security import (
    _DANGEROUS_NETWORK_ERROR,
    _is_dangerous_address,
    client_for_resolved_address,
    read_response_body_limited,
    resolve_and_validate_upstream_host,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_dns_module_state():
    """隔离模块级信号量/执行器单例，避免跨用例状态泄漏。"""
    us._dns_semaphore = None
    us._dns_executor_instance = None
    yield
    if us._dns_executor_instance is not None:
        us._dns_executor_instance.shutdown(wait=False)
    us._dns_semaphore = None
    us._dns_executor_instance = None


def _fake_resolver(addresses, calls=None, fail=False, delay=0.0):
    """返回 getaddrinfo 形状的替身解析器（5 元组列表）。"""

    def _resolve(host, port):
        if calls is not None:
            calls.append((host, port))
        if delay:
            time.sleep(delay)
        if fail:
            raise socket.gaierror("resolver boom")
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, port))
            for addr in addresses
        ]

    return _resolve


# ---------------------------------------------------------------------------
# _is_dangerous_address
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "target",
    [
        "127.0.0.1",  # loopback v4
        "::1",  # loopback v6
        "10.0.0.5",  # 私网 A 类
        "192.168.1.1",  # 私网 C 类
        "172.16.0.9",  # 私网 B 类
        "169.254.1.1",  # 链路本地
        "169.254.169.254",  # AWS metadata（同时是链路本地）
        "240.0.0.1",  # reserved
        "0.0.0.0",  # unspecified
    ],
)
def test_dangerous_addresses_blocked(target):
    assert _is_dangerous_address(target) is True


@pytest.mark.parametrize("target", ["93.184.216.34", "8.8.8.8", "example.com", ""])
def test_benign_targets_not_flagged(target):
    assert _is_dangerous_address(target) is False


# ---------------------------------------------------------------------------
# _configured_allowed_hosts
# ---------------------------------------------------------------------------


def test_allowed_hosts_empty_by_default(monkeypatch):
    monkeypatch.delenv("SAGE_ALLOWED_UPSTREAM_HOSTS", raising=False)
    assert us._configured_allowed_hosts() == frozenset()


def test_allowed_hosts_split_strip_lower(monkeypatch):
    monkeypatch.setenv("SAGE_ALLOWED_UPSTREAM_HOSTS", " LocalHost , 10.0.0.5 ,")
    assert us._configured_allowed_hosts() == frozenset({"localhost", "10.0.0.5"})


# ---------------------------------------------------------------------------
# resolve_and_validate_upstream_host
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_missing_host_rejected():
    with pytest.raises(ValueError, match="URL must include a host"):
        await resolve_and_validate_upstream_host(urlparse("https:///path"))


@pytest.mark.asyncio()
async def test_literal_private_host_blocked(monkeypatch):
    """host 字面量即私网：即使解析出公网地址也按 host 拒绝。"""
    calls = []
    monkeypatch.setattr(us, "_resolve_addresses", _fake_resolver(["1.2.3.4"], calls))
    with pytest.raises(ValueError, match=re.escape(_DANGEROUS_NETWORK_ERROR)) as excinfo:
        await resolve_and_validate_upstream_host(urlparse("http://10.0.0.5/x"))
    assert str(excinfo.value) == _DANGEROUS_NETWORK_ERROR
    assert "10.0.0.5" not in str(excinfo.value)  # 错误文案刻意模糊，不泄漏目标
    assert calls == [("10.0.0.5", 80)]  # 解析先于校验执行，但结论仍由 host 判定


@pytest.mark.asyncio()
async def test_hostname_trailing_dot_normalized(monkeypatch):
    calls = []
    monkeypatch.setattr(
        us, "_resolve_addresses", _fake_resolver(["93.184.216.34"], calls)
    )
    pinned = await resolve_and_validate_upstream_host(
        urlparse("https://example.com./x")
    )
    assert pinned == "93.184.216.34"
    assert calls == [("example.com", 443)]  # 尾点剥离 + https 默认 443


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    ("url", "port"),
    [
        ("http://example.com/x", 80),
        ("https://example.com/x", 443),
        ("http://example.com:8080/x", 8080),
    ],
)
async def test_port_defaults(monkeypatch, url, port):
    calls = []
    monkeypatch.setattr(
        us, "_resolve_addresses", _fake_resolver(["93.184.216.34"], calls)
    )
    await resolve_and_validate_upstream_host(urlparse(url))
    assert calls == [("example.com", port)]


@pytest.mark.asyncio()
async def test_dns_rebinding_resolved_private_address_blocked(monkeypatch):
    """公网 host 解析到私网地址（rebinding 场景）必须拒绝。"""
    monkeypatch.setattr(
        us,
        "_resolve_addresses",
        _fake_resolver(["93.184.216.34", "192.168.1.50"]),
    )
    with pytest.raises(ValueError, match=re.escape(_DANGEROUS_NETWORK_ERROR)) as excinfo:
        await resolve_and_validate_upstream_host(urlparse("https://example.com/x"))
    assert "192.168.1.50" not in str(excinfo.value)


@pytest.mark.asyncio()
async def test_allowed_host_bypasses_dangerous_check(monkeypatch):
    monkeypatch.setenv("SAGE_ALLOWED_UPSTREAM_HOSTS", "localhost")
    monkeypatch.setattr(us, "_resolve_addresses", _fake_resolver(["127.0.0.1"]))
    pinned = await resolve_and_validate_upstream_host(
        urlparse("http://localhost:8000/meta")
    )
    assert pinned == "127.0.0.1"


@pytest.mark.asyncio()
async def test_resolution_failure_maps_to_value_error(monkeypatch):
    monkeypatch.setattr(us, "_resolve_addresses", _fake_resolver([], fail=True))
    with pytest.raises(ValueError, match="DNS resolution failed"):
        await resolve_and_validate_upstream_host(urlparse("https://nx.example/x"))
    assert us._dns_semaphore is not None
    assert not us._dns_semaphore.locked()


@pytest.mark.asyncio()
async def test_resolution_timeout_maps_to_value_error(monkeypatch):
    monkeypatch.setattr(us, "DNS_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(
        us, "_resolve_addresses", _fake_resolver(["1.2.3.4"], delay=0.6)
    )
    with pytest.raises(ValueError, match="DNS resolution failed"):
        await resolve_and_validate_upstream_host(urlparse("https://slow.example/x"))
    assert not us._dns_semaphore.locked()  # 超时路径也必须归还信号量


@pytest.mark.asyncio()
async def test_empty_resolution_results_rejected(monkeypatch):
    monkeypatch.setattr(us, "_resolve_addresses", _fake_resolver([]))
    with pytest.raises(ValueError, match="no addresses found"):
        await resolve_and_validate_upstream_host(urlparse("https://example.com/x"))


@pytest.mark.asyncio()
async def test_dns_capacity_exhausted_short_circuits(monkeypatch):
    """信号量占满时立即拒绝，不进入解析（有界并发护栏）。"""
    monkeypatch.setattr(us, "_resolve_addresses", _fake_resolver(["1.2.3.4"]))
    us._dns_semaphore = asyncio.Semaphore(1)
    await us._dns_semaphore.acquire()
    try:
        with pytest.raises(ValueError, match="DNS resolution capacity exhausted"):
            await resolve_and_validate_upstream_host(urlparse("https://example.com"))
    finally:
        us._dns_semaphore.release()


@pytest.mark.asyncio()
async def test_pinned_address_is_sorted_first(monkeypatch):
    monkeypatch.setattr(
        us, "_resolve_addresses", _fake_resolver(["93.184.216.99", "93.184.216.10"])
    )
    pinned = await resolve_and_validate_upstream_host(urlparse("https://example.com"))
    assert pinned == "93.184.216.10"
    assert not us._dns_semaphore.locked()


# ---------------------------------------------------------------------------
# client_for_resolved_address / _FixedIPNetworkBackend
# ---------------------------------------------------------------------------


def test_client_rejects_unsupported_httpcore(monkeypatch):
    monkeypatch.setattr(httpcore, "__version__", "0.15.0")
    with pytest.raises(RuntimeError, match="Unsupported httpcore version"):
        client_for_resolved_address("93.184.216.34")


@pytest.mark.asyncio()
async def test_client_rejects_next_minor_series(monkeypatch):
    monkeypatch.setattr(httpcore, "__version__", "1.1.0")
    with pytest.raises(RuntimeError, match="Unsupported httpcore version"):
        client_for_resolved_address("93.184.216.34")


@pytest.mark.asyncio()
@pytest.mark.parametrize("version", ["1.0.0", "1.0.9"])
async def test_client_accepts_httpcore_1_0_series(monkeypatch, version):
    """回归：1.0.x 补丁版必须放行（曾因 startswith("1.0.0") 误拒 1.0.9）。"""
    monkeypatch.setattr(httpcore, "__version__", version)
    client = client_for_resolved_address("93.184.216.34")
    try:
        backend = client._transport._pool._network_backend
        assert isinstance(backend, us._FixedIPNetworkBackend)
    finally:
        await client.aclose()


@pytest.mark.asyncio()
async def test_fixed_ip_backend_redirects_connect_tcp(monkeypatch):
    """connect_tcp 的 hostname 实参被替换为 pinned IP（防 rebinding 核心）。"""
    recorded = []

    async def fake_connect_tcp(
        self, host, port, timeout=None, local_address=None, socket_options=None
    ):
        recorded.append((host, port))
        return "fake-socket"

    monkeypatch.setattr(
        "httpcore._backends.auto.AutoBackend.connect_tcp", fake_connect_tcp
    )
    client = client_for_resolved_address("93.184.216.34")
    try:
        backend = client._transport._pool._network_backend
        assert isinstance(backend, us._FixedIPNetworkBackend)
        sock = await backend.connect_tcp("evil.example", 443)
        assert sock == "fake-socket"
        assert recorded == [("93.184.216.34", 443)]
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# read_response_body_limited
# ---------------------------------------------------------------------------


async def _explode_once():
    """首读即失败的哨兵异步生成器：验证超限时 body 从未被消费。"""
    raise AssertionError("body must not be read when content-length exceeds limit")
    yield b""  # pragma: no cover


@pytest.mark.asyncio()
async def test_content_length_over_limit_skips_body_read():
    resp = httpx.Response(
        200,
        headers={"content-length": str(11 * 1024 * 1024)},
        content=_explode_once(),
    )
    with pytest.raises(ValueError, match="exceeds configured limit"):
        await read_response_body_limited(resp, max_bytes=1024)


@pytest.mark.asyncio()
async def test_invalid_content_length_ignored_then_streamed():
    resp = httpx.Response(
        200, headers={"content-length": "not-a-number"}, content=b"hello"
    )
    body = await read_response_body_limited(resp, max_bytes=1024)
    assert body == b"hello"


@pytest.mark.asyncio()
async def test_streaming_over_limit_without_content_length():
    async def _chunks():
        yield b"a" * 600
        yield b"b" * 600

    resp = httpx.Response(200, content=_chunks())  # 异步迭代 content → 无 content-length
    with pytest.raises(ValueError, match="exceeds configured limit"):
        await read_response_body_limited(resp, max_bytes=1000)


@pytest.mark.asyncio()
async def test_exactly_at_limit_passes():
    body = b"x" * 100
    resp = httpx.Response(200, content=body)
    assert await read_response_body_limited(resp, max_bytes=100) == body


@pytest.mark.asyncio()
async def test_one_byte_over_limit_raises():
    body = b"x" * 101
    resp = httpx.Response(200, content=body)
    with pytest.raises(ValueError, match="exceeds configured limit"):
        await read_response_body_limited(resp, max_bytes=100)


@pytest.mark.asyncio()
async def test_normal_read_returns_joined_body():
    async def _chunks():
        yield b"hel"
        yield b"lo "

    resp = httpx.Response(200, content=_chunks())
    assert await read_response_body_limited(resp, max_bytes=1024) == b"hello "
