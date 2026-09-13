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
        config = load_proxy_config(
            _repo(json.dumps({"http": " http://p:8080 ", "https": None}))
        )
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
        with patch(
            "backend.tools.http_factory.load_proxy_config", return_value=dict(_PROXY)
        ):
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
        with patch(
            "backend.tools.http_factory.load_proxy_config", return_value=dict(_PROXY)
        ):
            client = build_client(mounts={"https://": sentinel})
        try:
            merged = captured["mounts"]
            assert merged["https://"] is sentinel
            assert isinstance(merged["http://"], httpx.HTTPTransport)
        finally:
            client.close()

    def test_build_client_end_to_end_request(self):
        """带代理配置的 client 仍能正常发请求（respx 拦截传输层，不真走代理）。"""
        with patch(
            "backend.tools.http_factory.load_proxy_config", return_value=dict(_PROXY)
        ), respx.mock(base_url="https://example.com") as mock:
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
        flag = browser_proxy_flag(
            {"http": "http://p:8080", "https": "socks5://p:1080"}
        )
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
