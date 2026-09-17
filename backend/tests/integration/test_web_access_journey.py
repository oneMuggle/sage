"""Round 17：登录态全链路 journey 集成测试。

把 R10-R15 的互锁改动串成一条真实调用链（仅 HTTP 层用 respx 假体、浏览器层用
monkeypatch，vault / 指标 / 凭据解析全部走真实现 + 共享假 SettingsRepository）：

J1  cookie 桥全链路：export 形态的档案 → web_fetch 附加 Cookie → 响应 Set-Cookie
    回写续期 → per-host 指标累计
J2  JS 壳渲染 + AU5 注入 + AU7 登录墙 → AU3 自愈重放 → 成功
J3  渲染失败 → RenderError 语义 + 指标记 fail

防回归目标：R10（注入）/R11（AU3/AU7）/R13（net+指标）/R15（per-host）的接缝。
"""

from __future__ import annotations

from typing import Dict

import httpx
import pytest
import respx

from backend.tools import web_metrics, web_render
from backend.tools.credential_vault import (
    load_credential,
    save_credential,
)
from backend.tools.web_tool import WebFetchTool

pytestmark = pytest.mark.unit

_SPA_SHELL = (
    "<html><head><title>App</title></head><body><div id=root></div>"
    "<script>var x=1;</script></body></html>"
)
_LOGIN_PAGE = "<html><body><input type=password></body></html>"


class _SharedRepo:
    """进程内共享的假 SettingsRepository（类属性存状态，实例随意建）。"""

    data: Dict[str, str] = {}

    def get(self, key):
        return type(self).data.get(key)

    def set(self, key, value, value_type="string", category="general"):
        type(self).data[key] = value


@pytest.fixture(autouse=True)
def _journey_env(monkeypatch):
    """共享假 repo + 确定性加密 + 指标清零。"""
    monkeypatch.setenv("SAGE_SECRET_SCHEME", "test")
    monkeypatch.setattr(
        "backend.data.settings_repo.SettingsRepository", _SharedRepo
    )
    _SharedRepo.data.clear()
    from backend.tools import http_factory

    http_factory.get_host_rate_limiter().reset()
    web_metrics.reset()
    yield
    web_metrics.reset()


def _seed_credential(value: str = "old") -> None:
    save_credential(
        ".example.com",
        [{"name": "SID", "value": value, "domain": ".example.com", "path": "/"}],
        source_profile="default",
    )


def test_j1_cookie_bridge_full_chain(monkeypatch):
    """export 档案 → 附加 Cookie → Set-Cookie 回写续期 → 指标累计。"""
    _seed_credential("old")
    tool = WebFetchTool()

    seen_headers = []

    def capture_request(request):
        seen_headers.append(dict(request.headers))
        return httpx.Response(
            200,
            text="hello data",
            headers={
                "content-type": "text/plain",
                "set-cookie": "SID=fresh; Path=/; Domain=.example.com",
            },
        )

    with respx.mock(base_url="https://example.com", assert_all_called=False) as mock:
        mock.get("/data").mock(side_effect=capture_request)
        result = tool.execute(url="https://example.com/data", credential_domain=".example.com")

    # 附加了登录态
    assert result.success is True
    assert any(h.get("cookie") == "SID=old" for h in seen_headers)
    # AU2：响应 Set-Cookie 回写续期 + note 提示
    assert load_credential(".example.com")[0]["value"] == "fresh"
    assert "credential_refreshed" in (result.content.get("note") or "")
    # R15：per-host 指标记成功
    snap = web_metrics.snapshot()
    assert snap["example.com"]["ok"] == 1


def test_j1_credential_expired_reports_without_hop(monkeypatch):
    """档案全部过期 → credential_expired，不发请求。"""
    import json
    import time

    _seed_credential("stale")
    # 直接把档案 cookie 置为已过期（走假共享 repo）
    from backend.services.secret_box import encrypt_secret
    from backend.tools.credential_vault import (
        SETTINGS_KEY_CREDENTIAL_VAULT,
        load_credential,
    )

    repo = _SharedRepo()
    cookies = load_credential(".example.com", repo=repo)
    for c in cookies:
        c["expires"] = int(time.time()) - 10
    repo.set(
        SETTINGS_KEY_CREDENTIAL_VAULT,
        json.dumps(
            {
                ".example.com": {
                    "kind": "cookie",
                    "cookies_enc": encrypt_secret(
                        json.dumps(cookies), account="browser-cookie:.example.com"
                    ),
                }
            }
        ),
    )

    tool = WebFetchTool()
    with respx.mock(base_url="https://example.com", assert_all_called=False) as mock:
        mock.get("/data").mock(return_value=httpx.Response(200, text="x"))
        result = tool.execute(url="https://example.com/data", credential_domain=".example.com")

    assert result.success is False
    assert "credential_expired" in result.error


def test_j2_render_login_wall_then_auto_refresh_success(monkeypatch):
    """JS 壳渲染带凭据 → 渲染遇登录墙（AU7）→ AU3 自愈重渲染 → 成功。"""

    _seed_credential("stale-but-refreshable")
    tool = WebFetchTool()
    render_calls = []

    def fake_render(url, network_policy, wait_for="", credential_domain="", repo=None):
        render_calls.append(credential_domain)
        if len(render_calls) == 1:
            return {
                "url": url,
                "title": "t",
                "content": "x",
                "rendered": True,
                "login_wall": True,
            }
        return {
            "url": url,
            "title": "t",
            "content": "登录后正文",
            "rendered": True,
            "credential_refreshed": ["SID"],
        }

    monkeypatch.setattr(web_render, "render_page", fake_render)
    monkeypatch.setattr(
        WebFetchTool,
        "_try_auto_refresh",
        lambda self, d, u: "credential_auto_refreshed: 已用持久 profile 静默重导登录态（SID）",
    )

    static = {
        "status_code": 200,
        "content_type": "text/html",
        "encoding": "utf-8",
        "mode": "text",
    }
    content = tool._render_dynamic(
        "https://example.com/app",
        __import__("backend.domain.network_policy", fromlist=["NetworkPolicy"]).NetworkPolicy(
            mode=__import__(
                "backend.domain.network_policy", fromlist=["NetworkMode"]
            ).NetworkMode.ONLINE
        ),
        "text",
        10000,
        static,
        "",
        ".example.com",
    )
    assert len(render_calls) == 2
    assert render_calls == [".example.com", ".example.com"]
    assert content["content"] == "登录后正文"
    assert "credential_auto_refreshed" in (content.get("note") or "")


def test_j3_render_failure_counts_fail_metric(monkeypatch):
    """渲染失败经 execute → RenderError 语义 + per-host 指标记 fail。"""

    tool = WebFetchTool()

    def boom(url, network_policy, wait_for="", credential_domain="", repo=None):
        raise web_render.RenderError("JS 渲染失败: boom")

    monkeypatch.setattr(web_render, "render_page", boom)
    with respx.mock(base_url="https://example.com", assert_all_called=False) as mock:
        mock.get("/app").mock(
            return_value=httpx.Response(
                200, text=_SPA_SHELL, headers={"content-type": "text/html"}
            )
        )
        result = tool.execute(url="https://example.com/app", render="always")

    assert result.success is False
    assert "JS 渲染失败" in result.error
    snap = web_metrics.snapshot()
    assert snap["example.com"]["fail"] == 1
