# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""http_factory 单元测试（方案 2026-09-13 批次 2：用户级代理）。"""

import json
from unittest.mock import patch

import httpx
import pytest
import respx
from httpx import Response

from backend.tools.http_factory import (
    SETTINGS_KEY_WEB_PROXY,
    browser_proxy_flag,
    build_client,
    build_proxy_mounts,
    load_proxy_config,
)

pytestmark = [pytest.mark.unit]

_PROXY = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}


def _repo(raw):
    class _Repo:
        def get(self, key):
            if key != SETTINGS_KEY_WEB_PROXY:
                raise AssertionError(f"unexpected key {key}")
            return raw

    return _Repo()


# ---------- load_proxy_config ----------


class TestLoadProxyConfig:
    def test_missing_key_returns_empty(self):
        assert load_proxy_config(_repo(None)) == {"http": "", "https": ""}

    def test_invalid_json_fails_safe(self):
        assert load_proxy_config(_repo("nope")) == {"http": "", "https": ""}
        assert load_proxy_config(_repo("[]")) == {"http": "", "https": ""}

    def test_valid_config_strips_whitespace(self):
        config = load_proxy_config(_repo(json.dumps({"http": " http://p:8080 ", "https": None})))
        assert config == {"http": "http://p:8080", "https": ""}

    def test_read_error_fails_safe(self):
        class _BrokenRepo:
            def get(self, key):
                raise RuntimeError("db gone")

        assert load_proxy_config(_BrokenRepo()) == {"http": "", "https": ""}


# ---------- build_proxy_mounts / build_client ----------


class TestBuildClient:
    def test_no_config_no_mounts(self):
        assert build_proxy_mounts({"http": "", "https": ""}) == {}

    def test_mounts_per_scheme(self):
        mounts = build_proxy_mounts({"http": "http://p:8080", "https": "http://p:8443"})
        assert set(mounts) == {"http://", "https://"}
        assert all(isinstance(t, httpx.HTTPTransport) for t in mounts.values())

    @staticmethod
    def _capture_client(monkeypatch):
        """捕获 build_client 传给 httpx.Client 的 kwargs（httpx 默认自带
        http/https 两个 None-mount，直接探 _mounts 无法区分注入与否）。"""
        captured = {}

        class CapturingClient(httpx.Client):
            def __init__(self, **kwargs):
                captured.update(kwargs)
                super().__init__(**kwargs)

        monkeypatch.setattr(httpx, "Client", CapturingClient)
        return captured

    def test_build_client_injects_proxy_mounts(self, monkeypatch):
        captured = self._capture_client(monkeypatch)
        with patch("backend.tools.http_factory.load_proxy_config", return_value=dict(_PROXY)):
            client = build_client(timeout=5.0)
        try:
            mounts = captured.get("mounts") or {}
            assert set(mounts) == {"http://", "https://"}
            assert all(isinstance(t, httpx.HTTPTransport) for t in mounts.values())
            assert captured["timeout"] == 5.0
        finally:
            client.close()

    def test_build_client_without_config_passes_no_mounts(self, monkeypatch):
        captured = self._capture_client(monkeypatch)
        with patch(
            "backend.tools.http_factory.load_proxy_config",
            return_value={"http": "", "https": ""},
        ):
            client = build_client()
        try:
            assert "mounts" not in captured
        finally:
            client.close()

    def test_explicit_mounts_win_over_proxy(self, monkeypatch):
        captured = self._capture_client(monkeypatch)
        sentinel = httpx.HTTPTransport()
        with patch("backend.tools.http_factory.load_proxy_config", return_value=dict(_PROXY)):
            client = build_client(mounts={"https://": sentinel})
        try:
            merged = captured["mounts"]
            assert merged["https://"] is sentinel
            assert isinstance(merged["http://"], httpx.HTTPTransport)
        finally:
            client.close()

    def test_build_client_end_to_end_request(self):
        """带代理配置的 client 仍能正常发请求（respx 拦截传输层，不真走代理）。"""
        with (
            patch("backend.tools.http_factory.load_proxy_config", return_value=dict(_PROXY)),
            respx.mock(base_url="https://example.com") as mock,
        ):
            mock.get("/").mock(return_value=Response(200, text="ok"))
            client = build_client(timeout=5.0)
            try:
                response = client.get("https://example.com/")
            finally:
                client.close()
        assert response.status_code == 200


# ---------- browser_proxy_flag ----------


class TestBrowserProxyFlag:
    def test_both_schemes_use_paired_form(self):
        flag = browser_proxy_flag({"http": "http://p:8080", "https": "socks5://p:1080"})
        assert flag == "http=http://p:8080;https=socks5://p:1080"

    def test_single_scheme_applies_to_all(self):
        assert browser_proxy_flag({"http": "", "https": "http://p:8443"}) == "http://p:8443"

    def test_unconfigured_returns_empty(self):
        assert browser_proxy_flag({"http": "", "https": ""}) == ""


# ---------- launch 命令构造 ----------


class TestLaunchCommand:
    def test_command_without_proxy(self):
        from backend.tools.browser_cdp import _build_launch_command

        command = _build_launch_command("/usr/bin/chrome", True, "/tmp/profile")
        assert "--headless=new" in command
        assert not any(arg.startswith("--proxy-server") for arg in command)
        assert command[-1] == "about:blank"

    def test_command_with_proxy(self):
        from backend.tools.browser_cdp import _build_launch_command

        command = _build_launch_command(
            "/usr/bin/chrome", False, "/tmp/profile", "http=http://p:8080"
        )
        assert "--headless=new" not in command
        assert "--proxy-server=http=http://p:8080" in command


# ---------- Round 5 B2：默认头 / 版本探测 / 重试 / 限速 ----------


from backend.tools import http_factory  # noqa: E402


@pytest.fixture()
def no_sleep(monkeypatch):
    waits = []
    monkeypatch.setattr(http_factory, "_sleep", waits.append)
    http_factory.get_host_rate_limiter().reset()
    return waits


def test_default_headers_include_client_hints_with_consistent_version(monkeypatch):
    monkeypatch.setattr(http_factory, "_probe_chrome_major", lambda: 131)
    http_factory.chrome_major_version(refresh=True)
    headers = http_factory.default_headers()

    assert "Chrome/131.0.0.0" in headers["User-Agent"]
    assert 'v="131"' in headers["Sec-CH-UA"]
    assert headers["Sec-Fetch-Dest"] == "document"
    assert headers["Upgrade-Insecure-Requests"] == "1"
    http_factory.chrome_major_version(refresh=True)  # 恢复真实探测


def test_default_headers_fallback_when_probe_fails(monkeypatch):
    monkeypatch.setattr(http_factory, "_probe_chrome_major", lambda: None)
    assert http_factory.chrome_major_version(refresh=True) == http_factory.FALLBACK_CHROME_MAJOR
    http_factory.chrome_major_version(refresh=True)


def test_default_headers_never_advertise_older_than_fallback(monkeypatch):
    """win7 本机 Chrome 109 → 仍声明兜底版本（过旧版本号是 bot 信号）。"""
    monkeypatch.setattr(http_factory, "_probe_chrome_major", lambda: 109)
    assert http_factory.chrome_major_version(refresh=True) == http_factory.FALLBACK_CHROME_MAJOR
    http_factory.chrome_major_version(refresh=True)


def test_default_headers_alias_behaves_like_dict():
    assert http_factory.DEFAULT_HEADERS["User-Agent"].startswith("Mozilla/")
    assert "Accept-Language" in http_factory.DEFAULT_HEADERS
    assert dict(http_factory.DEFAULT_HEADERS) == http_factory.default_headers()


def test_probe_chrome_major_reads_version_dir(tmp_path, monkeypatch):
    exe = tmp_path / "chrome.exe"
    exe.write_bytes(b"")
    (tmp_path / "128.0.6613.84").mkdir()
    (tmp_path / "130.0.6723.58").mkdir()
    import backend.tools.browser_cdp as cdp

    monkeypatch.setattr(cdp, "discover_browser_executable", lambda: str(exe))
    assert http_factory._probe_chrome_major() == 130


@pytest.mark.parametriz()e(
    ("value", "expected"),
    [("5", 5.0), ("  12 ", 12.0), ("", None), (None, None), ("garbage", None)],
)
def test_parse_retry_after(value, expected):
    assert http_factory.parse_retry_after(value) == expected


def test_retrying_send_retries_status_then_returns(no_sleep):
    with respx.mock(base_url="https://x.test") as mock:
        route = mock.get("/p").mock(
            side_effect=[Response(503), Response(500), Response(200, text="ok")]
        )
        with httpx.Client() as client:
            response = http_factory.retrying_send(
                client, client.build_request("GET", "https://x.test/p")
            )

    assert response.status_code == 200
    assert route.call_count == 3
    assert len(no_sleep) == 2
    assert 0.8 <= no_sleep[0] <= 1.0
    assert 1.6 <= no_sleep[1] <= 2.0


def test_retrying_send_returns_last_status_when_exhausted(no_sleep):
    with respx.mock(base_url="https://x.test") as mock:
        route = mock.get("/p").mock(return_value=Response(503))
        with httpx.Client() as client:
            response = http_factory.retrying_send(
                client, client.build_request("GET", "https://x.test/p"), retries=1
            )

    assert response.status_code == 503
    assert route.call_count == 2


def test_retrying_send_honors_retry_after_cap(no_sleep):
    with respx.mock(base_url="https://x.test") as mock:
        mock.get("/p").mock(
            side_effect=[Response(429, headers={"retry-after": "999"}), Response(200)]
        )
        with httpx.Client() as client:
            http_factory.retrying_send(client, client.build_request("GET", "https://x.test/p"))

    assert no_sleep == [30.0]


def test_retrying_send_raises_after_exception_retries(no_sleep):
    with respx.mock(base_url="https://x.test") as mock:
        route = mock.get("/p").mock(side_effect=httpx.ConnectError("down"))
        with httpx.Client() as client, pytest.raises(httpx.ConnectError):
            http_factory.retrying_send(
                client, client.build_request("GET", "https://x.test/p"), retries=2
            )

    assert route.call_count == 3


def test_retrying_send_does_not_retry_4xx(no_sleep):
    with respx.mock(base_url="https://x.test") as mock:
        route = mock.get("/p").mock(return_value=Response(403))
        with httpx.Client() as client:
            response = http_factory.retrying_send(
                client, client.build_request("GET", "https://x.test/p")
            )

    assert response.status_code == 403
    assert route.call_count == 1
    assert no_sleep == []


def test_host_rate_limiter_spaces_requests(monkeypatch):
    waits = []
    monkeypatch.setattr(http_factory, "_sleep", waits.append)
    limiter = http_factory.HostRateLimiter(rate=2.0, burst=2)
    clock = {"t": 100.0}
    monkeypatch.setattr(http_factory.time, "monotonic", lambda: clock["t"])

    assert limiter.acquire("a.test") == 0.0
    assert limiter.acquire("a.test") == 0.0  # 突发额度
    third = limiter.acquire("a.test")
    assert third == pytest.approx(0.5)
    assert limiter.acquire("b.test") == 0.0  # 不同 host 独立
    clock["t"] += 5
    assert limiter.acquire("a.test") == 0.0  # 令牌已回填


def test_build_client_accepts_client_class(monkeypatch):
    class Marker(httpx.Client):
        pass

    client = http_factory.build_client(client_class=Marker, timeout=1.0)
    try:
        assert isinstance(client, Marker)
    finally:
        client.close()
