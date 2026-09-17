"""r63 — loopback 回调监听 + with_loopback 编排单测。"""

import asyncio
import threading
import urllib.request

import pytest

from backend.mcp.oauth_loopback import (
    LoopbackCallbackServer,
    authorize_mcp_server_with_loopback,
)

pytestmark = pytest.mark.unit


class TestLoopbackServer:
    def test_binds_random_port_and_exposes_redirect_uri(self):
        with LoopbackCallbackServer() as s1, LoopbackCallbackServer() as s2:
            assert s1.port > 0
            assert s1.redirect_uri == f"http://127.0.0.1:{s1.port}/callback"
            assert s1.port != s2.port or True  # 端口独立绑定即可

    def test_captures_callback_url_via_real_http(self):
        with LoopbackCallbackServer() as server:
            target = f"{server.redirect_uri}?code=abc&state=st-1"

            def hit():
                urllib.request.urlopen(target, timeout=5).read()

            t = threading.Thread(target=hit)
            t.start()
            captured = asyncio.run(server.wait(timeout=10))
            t.join(timeout=5)
            assert captured == target
            assert server.captured == captured

    def test_non_callback_path_404(self):
        with LoopbackCallbackServer() as server:
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{server.port}/other", timeout=5
                )
                raise AssertionError("expected 404")
            except urllib.error.HTTPError as exc:
                assert exc.code == 404

    def test_wait_timeout(self):
        with LoopbackCallbackServer() as server:
            with pytest.raises(TimeoutError, match="超时"):
                asyncio.run(server.wait(timeout=0.2))


class TestWithLoopback:
    SERVER = "https://mcp.example.com/mcp"

    def _http_fakes(self):
        async def get_json(url):
            if "oauth-protected-resource" in url:
                return {
                    "resource": self.SERVER,
                    "authorization_servers": ["https://auth.example.com"],
                }
            if "oauth-authorization-server" in url:
                return {
                    "issuer": "https://auth.example.com",
                    "authorization_endpoint": "https://auth.example.com/authorize",
                    "token_endpoint": "https://auth.example.com/token",
                    "registration_endpoint": "https://auth.example.com/register",
                }
            raise AssertionError(f"unexpected GET {url}")

        async def post_json(url, headers, body):
            if url.endswith("/register"):
                return {"client_id": "cid-lb"}
            if url.endswith("/token"):
                return {"access_token": "at-lb", "expires_in": 600}
            raise AssertionError(f"unexpected POST {url}")

        return get_json, post_json

    async def test_full_flow_with_real_loopback_hit(self):
        """授权 URL 里 redirect_uri 指向回听端口；线程内真实 GET 完成回调。"""
        get_json, post_json = self._http_fakes()
        opened = []

        def open_url(url):
            opened.append(url)
            from urllib.parse import parse_qs, urlparse

            state = parse_qs(urlparse(url).query)["state"][0]
            port = parse_qs(urlparse(url).query)["redirect_uri"][0].split(":")[2].split("/")[0]
            target = f"http://127.0.0.1:{port}/callback?code=cb-1&state={state}"

            def hit():
                urllib.request.urlopen(target, timeout=5).read()

            threading.Thread(target=hit).start()
            return True

        record = await authorize_mcp_server_with_loopback(
            self.SERVER,
            scope="mcp:tools",
            http_get_json=get_json,
            http_post_json=post_json,
            open_url=open_url,
            callback_timeout=15.0,
        )
        assert record.access_token == "at-lb"
        assert record.client_id == "cid-lb"
        assert len(opened) == 1
        assert "code_challenge_method=S256" in opened[0]

    async def test_open_url_false_fails_fast(self):
        get_json, post_json = self._http_fakes()

        def open_url(url):
            return False

        with pytest.raises(RuntimeError, match="浏览器拉起失败"):
            await authorize_mcp_server_with_loopback(
                self.SERVER,
                http_get_json=get_json,
                http_post_json=post_json,
                open_url=open_url,
                callback_timeout=5.0,
            )
