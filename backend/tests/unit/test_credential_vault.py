# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""cookie 桥单元测试（方案 2026-09-13 批次 4）。

覆盖：credential_vault 存取/加密/域匹配、WebFetchTool 与 HttpDownloadTool
的 credential_domain 接线（含跨域剥离）、BrowserCookiesTool 的
export/list/delete。
"""

import json
from types import SimpleNamespace

import pytest
import respx
from httpx import Response

from backend.domain.tool_policy import ToolPolicy
from backend.tools import browser_tool
from backend.tools.browser_cdp import BrowserSession, BrowserSessionManager
from backend.tools.browser_tool import BrowserCookiesTool
from backend.tools.credential_vault import (
    SETTINGS_KEY_CREDENTIAL_VAULT,
    cookie_domain_matches,
    cookie_header_for,
    cookie_path_matches,
    delete_credential,
    list_credentials,
    load_credential,
    looks_like_login_html,
    looks_like_login_url,
    merge_set_cookies,
    parse_set_cookie,
    resolve_credential,
    save_credential,
    save_header_credential,
)
from backend.tools.download_tool import HttpDownloadTool
from backend.tools.web_tool import WebFetchTool

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def _no_http_sleep(monkeypatch):
    """B2/AB5 重试退避不真睡。"""
    from backend.tools import http_factory

    monkeypatch.setattr(http_factory, "_sleep", lambda _s: None)
    http_factory.get_host_rate_limiter().reset()


_COOKIES = [
    {"name": "SID", "value": "s3cret", "domain": ".example.com", "path": "/"},
    {"name": "AUTH", "value": "token1", "domain": ".example.com", "path": "/"},
]


@pytest.fixture(autouse=True)
def _force_test_secret_scheme(monkeypatch):
    """enc: 加解密走确定性 test 方案（base64），保证 CI 可复现。"""
    monkeypatch.setenv("SAGE_SECRET_SCHEME", "test")


class _MemRepo:
    """内存版 SettingsRepository（只实现 vault 相关语义）。"""

    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, value_type="string", category="general"):
        self.data[key] = value


@pytest.fixture
def repo():
    return _MemRepo()


# ---------- credential_vault ----------


class TestCredentialVault:
    def test_save_load_roundtrip(self, repo):
        save_credential(".example.com", _COOKIES, repo=repo)
        assert SETTINGS_KEY_CREDENTIAL_VAULT in repo.data
        raw = json.loads(repo.data[SETTINGS_KEY_CREDENTIAL_VAULT])
        assert raw[".example.com"]["cookies_enc"].startswith("enc:")  # 静态加密落库
        cookies = load_credential(".example.com", repo=repo)
        assert cookies == _COOKIES

    def test_cookie_header_joins_pairs(self, repo):
        save_credential(".example.com", _COOKIES, repo=repo)
        header = cookie_header_for(".example.com", repo=repo)
        assert header == "SID=s3cret; AUTH=token1"

    def test_missing_archive_returns_none(self, repo):
        assert load_credential(".other.com", repo=repo) is None
        assert cookie_header_for(".other.com", repo=repo) is None

    def test_corrupt_archive_returns_none(self, repo):
        save_credential(".example.com", _COOKIES, repo=repo)
        raw = json.loads(repo.data[SETTINGS_KEY_CREDENTIAL_VAULT])
        raw[".example.com"]["cookies_enc"] = "enc:test:v1:!!!"
        repo.data[SETTINGS_KEY_CREDENTIAL_VAULT] = json.dumps(raw)
        assert load_credential(".example.com", repo=repo) is None

    def test_delete(self, repo):
        save_credential(".example.com", _COOKIES, repo=repo)
        assert delete_credential(".example.com", repo=repo) is True
        assert delete_credential(".example.com", repo=repo) is False
        assert load_credential(".example.com", repo=repo) is None

    def test_list_is_masked(self, repo):
        save_credential(".example.com", _COOKIES, repo=repo)
        entries = list_credentials(repo=repo)
        assert entries[0]["domain"] == ".example.com"
        assert entries[0]["cookie_names"] == ["SID", "AUTH"]
        assert "s3cret" not in json.dumps(entries)  # 值不回显

    def test_save_rejects_empty(self, repo):
        with pytest.raises(ValueError, match="domain 与 cookies"):
            save_credential(".example.com", [], repo=repo)
        with pytest.raises(ValueError, match="domain 与 cookies"):
            save_credential("", _COOKIES, repo=repo)


class TestCookieDomainMatches:
    @pytest.mark.parametrize(
        ("hostname", "domain", "expected"),
        [
            ("www.example.com", ".example.com", True),
            ("example.com", ".example.com", True),
            ("example.com", "example.com", True),
            ("a.b.example.com", ".example.com", True),
            ("evilc.example.com.evil.net", ".example.com", False),
            ("evilexample.com", ".example.com", False),
            ("other.com", ".example.com", False),
            ("", ".example.com", False),
        ],
    )
    def test_cases(self, hostname, domain, expected):
        assert cookie_domain_matches(hostname, domain) is expected


# ---------- WebFetchTool credential_domain ----------


def _fetch_tool():
    return WebFetchTool()


class TestWebFetchCredential:
    def test_credential_not_found(self):
        result = _fetch_tool().execute(
            url="https://www.example.com/paper", credential_domain=".example.com"
        )
        assert result.success is False
        assert "credential_not_found" in result.error

    def test_credential_domain_mismatch(self, repo):
        save_credential(".example.com", _COOKIES, repo=repo)
        with patch_vault_repo(repo):
            result = _fetch_tool().execute(
                url="https://other.org/paper", credential_domain=".example.com"
            )
        assert result.success is False
        assert "credential_domain_mismatch" in result.error

    def test_cookie_attached_on_matched_hop(self, repo):
        save_credential(".example.com", _COOKIES, repo=repo)
        with patch_vault_repo(repo), respx.mock(base_url="https://www.example.com") as mock:
            route = mock.get("/paper").mock(
                return_value=Response(
                    200,
                    text="<html>订阅内容</html>",
                    headers={"content-type": "text/html; charset=utf-8"},
                )
            )
            result = _fetch_tool().execute(
                url="https://www.example.com/paper", credential_domain=".example.com"
            )

        assert result.success is True
        request = route.calls.last.request
        assert request.headers["Cookie"] == "SID=s3cret; AUTH=token1"

    def test_cookie_stripped_on_cross_domain_redirect(self, repo):
        save_credential(".example.com", _COOKIES, repo=repo)
        with patch_vault_repo(repo), respx.mock(assert_all_called=False) as mock:
            first = mock.get("https://www.example.com/paper").mock(
                return_value=Response(302, headers={"location": "https://ads.other.net/final"})
            )
            second = mock.get("https://ads.other.net/final").mock(
                return_value=Response(
                    200,
                    text="<html>第三方页</html>",
                    headers={"content-type": "text/html; charset=utf-8"},
                )
            )
            result = _fetch_tool().execute(
                url="https://www.example.com/paper", credential_domain=".example.com"
            )

        assert result.success is True
        # 跨域 hop 不携带凭据 cookie
        final_request = second.calls.last.request
        assert "Cookie" not in final_request.headers
        assert first.calls.last.request.headers["Cookie"] == "SID=s3cret; AUTH=token1"
        assert "credential_stripped" in (result.content.get("note") or "")

    def test_no_credential_no_cookie_header(self):
        with respx.mock(base_url="https://www.example.com", assert_all_called=False) as mock:
            route = mock.get("/open").mock(
                return_value=Response(
                    200,
                    text="<html>公开页</html>",
                    headers={"content-type": "text/html; charset=utf-8"},
                )
            )
            result = _fetch_tool().execute(url="https://www.example.com/open")

        assert result.success is True
        assert "Cookie" not in route.calls.last.request.headers


# ---------- HttpDownloadTool credential_domain ----------


class TestDownloadCredential:
    def _tool(self, tmp_path):
        return HttpDownloadTool(policy=ToolPolicy(workspace_root=str(tmp_path)))

    def test_credential_not_found(self, tmp_path):
        result = self._tool(tmp_path).execute(
            url="https://www.example.com/a.pdf", credential_domain=".example.com"
        )
        assert result.success is False
        assert "credential_not_found" in result.error

    def test_cookie_attached_on_download(self, tmp_path, repo):
        save_credential(".example.com", _COOKIES, repo=repo)
        with (
            patch_vault_repo(repo),
            respx.mock(base_url="https://www.example.com") as mock,
        ):
            route = mock.get("/a.pdf").mock(return_value=Response(200, content=b"%PDF-1.4 fake"))
            result = self._tool(tmp_path).execute(
                url="https://www.example.com/a.pdf", credential_domain=".example.com"
            )

        assert result.success is True
        assert route.calls.last.request.headers["Cookie"] == "SID=s3cret; AUTH=token1"
        assert (tmp_path / "a.pdf").read_bytes() == b"%PDF-1.4 fake"


# ---------- BrowserCookiesTool ----------


def _fake_session():
    process = SimpleNamespace(
        poll=lambda: None, terminate=lambda: None, kill=lambda: None, wait=lambda timeout=None: None
    )
    return BrowserSession(
        browser_id="b1",
        executable="fake-browser",
        headless=True,
        user_data_dir="/tmp/unused",
        process=process,
        port=1,
        ws_path="/devtools/browser/x",
    )


class TestBrowserCookiesTool:
    def test_export_saves_grouped_and_masked(self, repo, monkeypatch):
        manager = BrowserSessionManager()
        manager.register(_fake_session())
        monkeypatch.setattr(browser_tool, "get_browser_manager", lambda: manager)

        def _fake_cdp(session_, method, params=None, target_id=None):
            assert method == "Network.getCookies"
            return {
                "cookies": [
                    {"name": "SID", "value": "s3cret", "domain": ".example.com"},
                    {"name": "TRACK", "value": "t", "domain": ".tracker.net"},
                ]
            }

        monkeypatch.setattr(browser_tool, "cdp_command", _fake_cdp)
        with patch_vault_repo(repo):
            result = BrowserCookiesTool().execute(action="export")

        assert result.success is True
        saved = {item["domain"]: item for item in result.content["saved"]}
        assert set(saved) == {".example.com", ".tracker.net"}
        assert sorted(saved[".example.com"]["cookie_names"]) == ["SID"]
        assert "s3cret" not in json.dumps(result.content)  # 脱敏：值不回显
        # 密文落库
        raw = json.loads(repo.data[SETTINGS_KEY_CREDENTIAL_VAULT])
        assert raw[".example.com"]["cookies_enc"].startswith("enc:")

    def test_export_no_cookies(self, repo, monkeypatch):
        manager = BrowserSessionManager()
        manager.register(_fake_session())
        monkeypatch.setattr(browser_tool, "get_browser_manager", lambda: manager)
        monkeypatch.setattr(browser_tool, "cdp_command", lambda *a, **kw: {"cookies": []})
        with patch_vault_repo(repo):
            result = BrowserCookiesTool().execute(action="export")
        assert result.success is False
        assert "no_cookies" in result.error

    def test_list_and_delete(self, repo, monkeypatch):
        save_credential(".example.com", _COOKIES, repo=repo)
        with patch_vault_repo(repo):
            listed = BrowserCookiesTool().execute(action="list")
            assert listed.success is True
            assert listed.content["credentials"][0]["domain"] == ".example.com"

            deleted = BrowserCookiesTool().execute(action="delete", domain=".example.com")
            assert deleted.success is True
            again = BrowserCookiesTool().execute(action="delete", domain=".example.com")
            assert again.success is False
            assert "credential_not_found" in again.error

    def test_invalid_action(self):
        result = BrowserCookiesTool().execute(action="steal")
        assert result.success is False


# ---------- 测试辅助 ----------


def patch_vault_repo(repo):
    """把 credential_vault 的默认 SettingsRepository 指到内存 repo。"""
    import unittest.mock

    return unittest.mock.patch("backend.data.settings_repo.SettingsRepository", return_value=repo)


# ---------- Round 5 B3 / AU1：cookie 元数据与过期 ----------

_FUTURE = 4102444800  # 2100-01-01
_PAST = 946684800  # 2000-01-01


class TestCookieExpiry:
    def test_save_keeps_metadata(self, repo):
        save_credential(
            ".example.com",
            [
                {
                    "name": "SID",
                    "value": "v",
                    "domain": ".example.com",
                    "path": "/app",
                    "expires": 1_900_000_000.5,
                    "secure": True,
                    "httpOnly": True,
                    "sameSite": "Lax",
                },
                {"name": "SESS", "value": "s", "domain": ".example.com", "expires": -1},
            ],
            repo=repo,
        )
        cookies = load_credential(".example.com", repo=repo)
        assert cookies[0]["expires"] == 1_900_000_000
        assert cookies[0]["secure"] is True
        assert cookies[0]["path"] == "/app"
        assert "expires" not in cookies[1]  # session cookie

    def test_expired_cookie_not_sent(self, repo):
        save_credential(
            ".example.com",
            [
                {"name": "OLD", "value": "1", "domain": ".example.com", "expires": _PAST},
                {"name": "NEW", "value": "2", "domain": ".example.com", "expires": _FUTURE},
            ],
            repo=repo,
        )
        assert cookie_header_for(".example.com", repo=repo) == "NEW=2"
        resolution = resolve_credential(".example.com", repo=repo)
        assert resolution.ok
        assert resolution.headers == {"Cookie": "NEW=2"}
        assert resolution.expired_names == ["OLD"]
        assert resolution.expires_in is not None
        assert resolution.expires_in > 0

    def test_all_expired_is_expired_status(self, repo):
        save_credential(
            ".example.com",
            [{"name": "OLD", "value": "1", "domain": ".example.com", "expires": _PAST}],
            repo=repo,
        )
        assert cookie_header_for(".example.com", repo=repo) is None
        resolution = resolve_credential(".example.com", repo=repo)
        assert resolution.status == "expired"
        assert resolution.expired_names == ["OLD"]
        listed = list_credentials(repo=repo)
        assert listed[0]["expired"] is True
        assert listed[0]["kind"] == "cookie"

    def test_secure_cookie_only_on_https_and_path_match(self, repo):
        save_credential(
            ".example.com",
            [
                {"name": "S", "value": "1", "domain": ".example.com", "secure": True},
                {"name": "P", "value": "2", "domain": ".example.com", "path": "/admin"},
                {"name": "A", "value": "3", "domain": ".example.com"},
            ],
            repo=repo,
        )
        assert cookie_header_for(".example.com", repo=repo, url="http://www.example.com/x") == "A=3"
        assert (
            cookie_header_for(".example.com", repo=repo, url="https://www.example.com/admin/p")
            == "S=1; P=2; A=3"
        )
        # url 缺省：不按协议 / path 过滤
        assert cookie_header_for(".example.com", repo=repo) == "S=1; P=2; A=3"

    @pytest.mark.parametrize(
        ("request_path", "cookie_path", "expected"),
        [
            ("/", "/", True),
            ("/admin/x", "/admin", True),
            ("/admin", "/admin/", False),
            ("/administrator", "/admin", False),
            ("/a/b", "/a/", True),
        ],
    )
    def test_cookie_path_matches(self, request_path, cookie_path, expected):
        assert cookie_path_matches(request_path, cookie_path) is expected

    def test_legacy_entry_without_kind_is_cookie(self, repo):
        save_credential(".example.com", _COOKIES, repo=repo)
        raw = json.loads(repo.data[SETTINGS_KEY_CREDENTIAL_VAULT])
        del raw[".example.com"]["kind"]
        repo.data[SETTINGS_KEY_CREDENTIAL_VAULT] = json.dumps(raw)
        assert resolve_credential(".example.com", repo=repo).headers == {
            "Cookie": "SID=s3cret; AUTH=token1"
        }
        assert list_credentials(repo=repo)[0]["kind"] == "cookie"

    def test_list_shows_min_expires_in(self, repo):
        save_credential(
            ".example.com",
            [
                {"name": "A", "value": "1", "domain": ".example.com", "expires": _FUTURE},
                {"name": "B", "value": "2", "domain": ".example.com", "expires": _FUTURE - 1000},
            ],
            repo=repo,
        )
        entry = list_credentials(repo=repo)[0]
        assert entry["expired"] is False
        assert entry["expires_in_seconds"] < _FUTURE - 1000


class TestWebFetchExpiredCredential:
    def test_web_fetch_reports_credential_expired(self, repo):
        save_credential(
            ".example.com",
            [{"name": "OLD", "value": "1", "domain": ".example.com", "expires": _PAST}],
            repo=repo,
        )
        with patch_vault_repo(repo):
            result = _fetch_tool().execute(
                url="https://www.example.com/paper", credential_domain=".example.com"
            )
        assert result.success is False
        assert result.error.startswith("credential_expired")
        assert "OLD" in result.error

    def test_download_reports_credential_expired(self, repo, tmp_path):
        save_credential(
            ".example.com",
            [{"name": "OLD", "value": "1", "domain": ".example.com", "expires": _PAST}],
            repo=repo,
        )
        with patch_vault_repo(repo):
            result = HttpDownloadTool(policy=ToolPolicy(workspace_root=str(tmp_path))).execute(
                url="https://www.example.com/a.pdf", credential_domain=".example.com"
            )
        assert result.success is False
        assert result.error.startswith("credential_expired")


# ---------- Round 5 B3 / AU2：Set-Cookie 回写 + 登录墙 ----------


class TestSetCookieWriteback:
    def test_parse_set_cookie_attributes(self):
        cookie = parse_set_cookie(
            "SID=new; Domain=example.com; Path=/app; Max-Age=3600; Secure; HttpOnly; SameSite=Lax",
            "https://www.example.com/x",
        )
        assert cookie["name"] == "SID"
        assert cookie["value"] == "new"
        assert cookie["domain"] == ".example.com"
        assert cookie["path"] == "/app"
        assert cookie["secure"] is True
        assert cookie["httpOnly"] is True
        assert cookie["sameSite"] == "Lax"
        assert cookie["expires"] > 0
        assert cookie["delete"] is False

    def test_parse_set_cookie_host_only_and_expires(self):
        cookie = parse_set_cookie(
            "A=1; Expires=Wed, 21 Oct 2015 07:28:00 GMT", "https://www.example.com/"
        )
        assert cookie["domain"] == "www.example.com"
        assert cookie["host_only"] is True
        assert cookie["delete"] is True  # 已过期 → 删除
        assert parse_set_cookie("garbage", "https://x/") is None

    def test_merge_updates_deletes_and_ignores_foreign(self, repo):
        save_credential(".example.com", _COOKIES, repo=repo)
        changed = merge_set_cookies(
            ".example.com",
            [
                "SID=rotated; Domain=.example.com; Path=/; Max-Age=600",
                "AUTH=; Max-Age=0",
                "TRACK=1; Domain=.tracker.net",
                "NEW=n; Path=/",
            ],
            "https://www.example.com/paper",
            repo=repo,
        )
        assert changed == ["SID", "AUTH", "NEW"]
        cookies = {c["name"]: c for c in load_credential(".example.com", repo=repo)}
        assert set(cookies) == {"SID", "NEW"}
        assert cookies["SID"]["value"] == "rotated"
        assert cookies["SID"]["expires"] > 0
        assert cookies["NEW"]["domain"] == "www.example.com"

    def test_merge_noop_without_archive(self, repo):
        assert (
            merge_set_cookies(".example.com", ["A=1"], "https://www.example.com/", repo=repo) == []
        )

    def test_web_fetch_writes_back_set_cookie(self, repo):
        save_credential(".example.com", _COOKIES, repo=repo)
        with patch_vault_repo(repo), respx.mock(base_url="https://www.example.com") as mock:
            mock.get("/paper").mock(
                return_value=Response(
                    200,
                    text="<html><body>订阅内容 订阅内容</body></html>",
                    headers=[
                        ("content-type", "text/html; charset=utf-8"),
                        ("set-cookie", "SID=rotated; Path=/; Max-Age=3600"),
                        ("set-cookie", "EXTRA=1; Domain=.example.com"),
                    ],
                )
            )
            result = _fetch_tool().execute(
                url="https://www.example.com/paper", credential_domain=".example.com"
            )
        assert result.success is True
        assert "credential_refreshed" in result.content["note"]
        cookies = {c["name"]: c["value"] for c in load_credential(".example.com", repo=repo)}
        assert cookies == {"SID": "rotated", "AUTH": "token1", "EXTRA": "1"}

    def test_web_fetch_does_not_write_back_cross_domain_set_cookie(self, repo):
        save_credential(".example.com", _COOKIES, repo=repo)
        with patch_vault_repo(repo), respx.mock(assert_all_called=False) as mock:
            mock.get("https://www.example.com/paper").mock(
                return_value=Response(302, headers={"location": "https://ads.other.net/final"})
            )
            mock.get("https://ads.other.net/final").mock(
                return_value=Response(
                    200,
                    text="<html>第三方页 第三方页</html>",
                    headers=[
                        ("content-type", "text/html; charset=utf-8"),
                        ("set-cookie", "SID=hijack; Domain=.other.net"),
                    ],
                )
            )
            result = _fetch_tool().execute(
                url="https://www.example.com/paper", credential_domain=".example.com"
            )
        assert result.success is True
        assert load_credential(".example.com", repo=repo) == _COOKIES

    def test_download_writes_back_set_cookie(self, repo, tmp_path):
        save_credential(".example.com", _COOKIES, repo=repo)
        with patch_vault_repo(repo), respx.mock(base_url="https://www.example.com") as mock:
            mock.get("/a.pdf").mock(
                return_value=Response(
                    200,
                    content=b"%PDF-1.4 fake",
                    headers=[("set-cookie", "SID=rotated; Path=/")],
                )
            )
            result = HttpDownloadTool(policy=ToolPolicy(workspace_root=str(tmp_path))).execute(
                url="https://www.example.com/a.pdf", credential_domain=".example.com"
            )
        assert result.success is True
        cookies = {c["name"]: c["value"] for c in load_credential(".example.com", repo=repo)}
        assert cookies["SID"] == "rotated"


class TestLoginWall:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://login.example.com/?next=/x", True),
            ("https://sso.example.com/saml", True),
            ("https://www.example.com/login", True),
            ("https://www.example.com/user/signin?ret=1", True),
            ("https://www.example.com/cas/login", True),
            ("https://www.example.com/oauth2/authorize", True),
            ("https://www.example.com/paper/123", False),
            ("https://www.example.com/blogin", False),
            ("https://www.example.com/authors", False),
        ],
    )
    def test_looks_like_login_url(self, url, expected):
        assert looks_like_login_url(url) is expected

    def test_looks_like_login_html(self):
        assert looks_like_login_html('<form><input type="password" name="p"></form>') is True
        assert looks_like_login_html("<input type=password>") is True
        assert looks_like_login_html("<p>hello</p>") is False

    def test_web_fetch_redirect_to_login_is_login_required(self, repo):
        save_credential(".example.com", _COOKIES, repo=repo)
        with patch_vault_repo(repo), respx.mock(assert_all_called=False) as mock:
            mock.get("https://www.example.com/paper").mock(
                return_value=Response(
                    302, headers={"location": "https://www.example.com/login?next=/paper"}
                )
            )
            mock.get("https://www.example.com/login").mock(
                return_value=Response(
                    200,
                    text="<html><body>请登录</body></html>",
                    headers={"content-type": "text/html; charset=utf-8"},
                )
            )
            result = _fetch_tool().execute(
                url="https://www.example.com/paper", credential_domain=".example.com"
            )
        assert result.success is False
        assert result.error.startswith("login_required")
        assert ".example.com" in result.error

    def test_web_fetch_password_form_is_login_required(self, repo):
        save_credential(".example.com", _COOKIES, repo=repo)
        html = (
            '<html><body><form><input name=u><input type="password" name=p>'
            "<button>登录</button></form></body></html>"
        )
        with patch_vault_repo(repo), respx.mock(base_url="https://www.example.com") as mock:
            mock.get("/paper").mock(
                return_value=Response(
                    200, text=html, headers={"content-type": "text/html; charset=utf-8"}
                )
            )
            result = _fetch_tool().execute(
                url="https://www.example.com/paper", credential_domain=".example.com"
            )
        assert result.success is False
        assert result.error.startswith("login_required")

    def test_web_fetch_article_with_login_widget_is_not_login_wall(self, repo):
        save_credential(".example.com", _COOKIES, repo=repo)
        body = " ".join(f"word{i}" for i in range(600))
        html = f'<html><body><form><input type="password"></form><article>{body}</article></body></html>'
        with patch_vault_repo(repo), respx.mock(base_url="https://www.example.com") as mock:
            mock.get("/paper").mock(
                return_value=Response(
                    200, text=html, headers={"content-type": "text/html; charset=utf-8"}
                )
            )
            result = _fetch_tool().execute(
                url="https://www.example.com/paper", credential_domain=".example.com"
            )
        assert result.success is True
        assert "word599" in result.content["content"]

    def test_web_fetch_without_credential_never_login_required(self):
        html = '<html><body><form><input type="password"></form></body></html>'
        with respx.mock(base_url="https://www.example.com") as mock:
            mock.get("/login").mock(
                return_value=Response(
                    200, text=html, headers={"content-type": "text/html; charset=utf-8"}
                )
            )
            result = _fetch_tool().execute(url="https://www.example.com/login")
        assert result.success is True  # 无凭据：登录页就是普通页面

    def test_download_redirect_to_sso_is_login_required(self, repo, tmp_path):
        save_credential(".example.com", _COOKIES, repo=repo)
        with patch_vault_repo(repo), respx.mock(assert_all_called=False) as mock:
            mock.get("https://www.example.com/a.pdf").mock(
                return_value=Response(302, headers={"location": "https://sso.example.com/idp"})
            )
            result = HttpDownloadTool(policy=ToolPolicy(workspace_root=str(tmp_path))).execute(
                url="https://www.example.com/a.pdf", credential_domain=".example.com"
            )
        assert result.success is False
        assert result.error.startswith("login_required")
        assert "sso.example.com" in result.error

    def test_download_login_page_instead_of_pdf_is_login_required(self, tmp_path):
        html = b'<html><body><form><input type="password"></form></body></html>'
        with respx.mock(base_url="https://www.example.com") as mock:
            mock.get("/a.pdf").mock(
                return_value=Response(200, content=html, headers={"content-type": "text/html"})
            )
            result = HttpDownloadTool(policy=ToolPolicy(workspace_root=str(tmp_path))).execute(
                url="https://www.example.com/a.pdf"
            )
        assert result.success is False
        assert result.error.startswith("login_required")
        assert "credential_domain" in result.error


# ---------- Round 5 B3 / AU4：头部型凭据 ----------


class TestHeaderCredential:
    def test_save_and_resolve(self, repo):
        save_header_credential("api.example.com", {"Authorization": "Bearer tok"}, repo=repo)
        raw = json.loads(repo.data[SETTINGS_KEY_CREDENTIAL_VAULT])["api.example.com"]
        assert raw["kind"] == "header"
        assert raw["headers_enc"].startswith("enc:")
        assert "tok" not in json.dumps(raw)
        resolution = resolve_credential("api.example.com", repo=repo)
        assert resolution.ok
        assert resolution.kind == "header"
        assert resolution.headers == {"Authorization": "Bearer tok"}
        # cookie 视角的读接口对 header 档案返回 None
        assert load_credential("api.example.com", repo=repo) is None
        assert cookie_header_for("api.example.com", repo=repo) is None

    def test_rejects_forbidden_or_malformed(self, repo):
        with pytest.raises(ValueError, match="不允许"):
            save_header_credential("x.com", {"Cookie": "a=b"}, repo=repo)
        with pytest.raises(ValueError, match="不允许|非法"):
            save_header_credential("x.com", {"Bad Name": "v"}, repo=repo)
        with pytest.raises(ValueError, match="换行"):
            save_header_credential("x.com", {"X-Key": "a\r\nInjected: 1"}, repo=repo)

    def test_ttl_expiry(self, repo):
        save_header_credential(
            "api.example.com", {"X-API-Key": "zzsecretzz"}, repo=repo, ttl_seconds=60
        )
        ok = resolve_credential("api.example.com", repo=repo)
        assert ok.ok
        assert 0 < ok.expires_in <= 60
        later = resolve_credential(
            "api.example.com", repo=repo, now=__import__("time").time() + 120
        )
        assert later.status == "expired"
        assert later.expired_names == ["X-API-Key"]
        listed = list_credentials(repo=repo)[0]
        assert listed["kind"] == "header"
        assert listed["header_names"] == ["X-API-Key"]
        assert "zzsecretzz" not in json.dumps(listed)

    def test_web_fetch_attaches_header_and_strips_cross_domain(self, repo):
        save_header_credential(".example.com", {"Authorization": "Bearer tok"}, repo=repo)
        with patch_vault_repo(repo), respx.mock(assert_all_called=False) as mock:
            first = mock.get("https://api.example.com/v1/doc").mock(
                return_value=Response(302, headers={"location": "https://cdn.other.net/doc"})
            )
            second = mock.get("https://cdn.other.net/doc").mock(
                return_value=Response(
                    200,
                    text="<html>doc doc</html>",
                    headers={"content-type": "text/html; charset=utf-8"},
                )
            )
            result = _fetch_tool().execute(
                url="https://api.example.com/v1/doc", credential_domain=".example.com"
            )
        assert result.success is True
        assert first.calls.last.request.headers["Authorization"] == "Bearer tok"
        assert "Authorization" not in second.calls.last.request.headers
        assert "credential_stripped" in result.content["note"]

    def test_download_attaches_header(self, repo, tmp_path):
        save_header_credential("api.example.com", {"X-API-Key": "k"}, repo=repo)
        with patch_vault_repo(repo), respx.mock(base_url="https://api.example.com") as mock:
            route = mock.get("/f.pdf").mock(return_value=Response(200, content=b"%PDF-1.4 x"))
            result = HttpDownloadTool(policy=ToolPolicy(workspace_root=str(tmp_path))).execute(
                url="https://api.example.com/f.pdf", credential_domain="api.example.com"
            )
        assert result.success is True
        assert route.calls.last.request.headers["X-API-Key"] == "k"

    def test_web_fetch_header_credential_expired(self, repo):
        save_header_credential("api.example.com", {"X-API-Key": "k"}, repo=repo, ttl_seconds=1)
        raw = json.loads(repo.data[SETTINGS_KEY_CREDENTIAL_VAULT])
        raw["api.example.com"]["expires_at"] = 1000
        repo.data[SETTINGS_KEY_CREDENTIAL_VAULT] = json.dumps(raw)
        with patch_vault_repo(repo):
            result = _fetch_tool().execute(
                url="https://api.example.com/v1", credential_domain="api.example.com"
            )
        assert result.success is False
        assert result.error.startswith("credential_expired")


class TestBrowserCookiesSetHeader:
    def test_set_header_saves_masked(self, repo):
        with patch_vault_repo(repo):
            result = BrowserCookiesTool().execute(
                action="set_header",
                domain="api.example.com",
                header_name="Authorization",
                header_value="Bearer s3cret",
                ttl_seconds=3600,
            )
        assert result.success is True
        assert result.content["kind"] == "header"
        assert result.content["header_names"] == ["Authorization"]
        assert "s3cret" not in json.dumps(result.content)
        assert resolve_credential("api.example.com", repo=repo).headers == {
            "Authorization": "Bearer s3cret"
        }

    def test_set_header_validation(self, repo):
        with patch_vault_repo(repo):
            missing = BrowserCookiesTool().execute(action="set_header", domain="a.com")
            assert missing.success is False
            bad = BrowserCookiesTool().execute(
                action="set_header", domain="a.com", header_name="Cookie", header_value="x"
            )
            assert bad.success is False
            assert "invalid_header" in bad.error

    def test_export_reports_expires_in(self, repo, monkeypatch):
        manager = BrowserSessionManager()
        manager.register(_fake_session())
        monkeypatch.setattr(browser_tool, "get_browser_manager", lambda: manager)
        monkeypatch.setattr(
            browser_tool,
            "cdp_command",
            lambda *a, **kw: {
                "cookies": [
                    {"name": "SID", "value": "v", "domain": ".example.com", "expires": _FUTURE},
                    {"name": "SESS", "value": "v", "domain": ".example.com", "expires": -1},
                ]
            },
        )
        with patch_vault_repo(repo):
            result = BrowserCookiesTool().execute(action="export")
        assert result.success is True
        assert result.content["saved"][0]["expires_in_seconds"] > 0
        cookies = load_credential(".example.com", repo=repo)
        assert cookies[0]["expires"] == _FUTURE
