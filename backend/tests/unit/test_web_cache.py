# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Round 2 单元测试：反爬路由指引（G1）+ UA 现代化（U1）+ TTL 缓存（C1）。"""

from unittest.mock import patch

import pytest
import respx
from httpx import Response

from backend.tools import http_factory, web_cache, web_tool
from backend.tools.search_config import SearchConfig
from backend.tools.web_tool import WebFetchTool, WebSearchTool

pytestmark = [pytest.mark.unit]


@pytest.fixture()(autouse=True)
def _clean_cache(monkeypatch):
    web_cache.clear()
    # B2/AB5：重试退避不真睡
    monkeypatch.setattr(http_factory, "_sleep", lambda _s: None)
    http_factory.get_host_rate_limiter().reset()
    yield
    web_cache.clear()


def _fetch_tool():
    return WebFetchTool()


_HTML_OK = "<html><body><p>" + "静态正文内容" * 100 + "</p></body></html>"

_OK = {"status_code": 200, "content_type": "text/html; charset=utf-8"}


def _mock_ok(mock, path, text=_HTML_OK):
    return mock.get(path).mock(
        return_value=Response(200, text=text, headers={"content-type": _OK["content_type"]})
    )


# ---------- G1 反爬路由指引 ----------


class TestAntibotGuidance:
    @pytest.mark.parametriz()e("status", [403, 429, 503])
    def test_antibot_status_guides_browser_channel(self, status):
        with respx.mock(base_url="https://hard.example", assert_all_called=False) as mock:
            mock.get("/p").mock(
                return_value=Response(status, text="denied", headers={"content-type": "text/html"})
            )
            result = _fetch_tool().execute(url="https://hard.example/p")

        assert result.success is False
        assert f"http_{status}" in result.error
        assert "browser_launch" in result.error
        assert "代理" in result.error

    def test_other_status_keeps_generic_message(self):
        with respx.mock(base_url="https://down.example", assert_all_called=False) as mock:
            mock.get("/p").mock(
                return_value=Response(500, text="boom", headers={"content-type": "text/html"})
            )
            result = _fetch_tool().execute(url="https://down.example/p")

        assert result.success is False
        assert "HTTP 请求失败" in result.error
        assert "browser_launch" not in result.error

    def test_search_chain_failure_403_appends_guidance(self):
        """引擎链 403 类失败 → 指引代理/API 引擎出路。"""
        from backend.tools.search_engines import SearchEngine

        class _Forbidden(SearchEngine):
            name = "ddg"

            def search(self, query, limit, client):
                raise RuntimeError("Client error '403 Forbidden'")

        with (
            patch(
                "backend.tools.web_tool.resolve_engine_chain",
                return_value=[_Forbidden()],
            ),
            patch("backend.tools.web_tool.load_search_config", return_value=SearchConfig()),
        ):
            result = WebSearchTool().execute(query="q")

        assert result.success is False
        assert "browser_launch" in result.error or "代理" in result.error


# ---------- U1 UA 现代化 ----------


class TestUserAgent:
    def test_ua_is_modern_chrome(self):
        ua = web_tool._DEFAULT_HEADERS["User-Agent"]
        assert "Chrome/" in ua
        # 版本必须高于 Round 1 前的过时 Chrome/120
        major = int(ua.split("Chrome/")[1].split(".")[0])
        assert major > 120

    def test_fetch_request_carries_ua(self):
        with respx.mock(base_url="https://example.com", assert_all_called=False) as mock:
            route = mock.get("/ua").mock(
                return_value=Response(200, text=_HTML_OK, headers={"content-type": "text/html"})
            )
            _fetch_tool().execute(url="https://example.com/ua")

        assert route.calls.last.request.headers["user-agent"].startswith("Mozilla/5.0")


# ---------- C1 TTL 缓存 ----------


class TestWebCacheUnit:
    def test_put_get_roundtrip(self):
        web_cache.put("https://a.example/", "text", {"content": "正文"})
        assert web_cache.get("https://a.example/", "text") == {"content": "正文"}

    def test_fragment_and_whitespace_normalize(self):
        web_cache.put("https://a.example/page#top", "text", {"content": "x"})
        assert web_cache.get("https://a.example/page ", "text") is not None

    def test_mode_is_part_of_key(self):
        web_cache.put("https://a.example/", "text", {"content": "x"})
        assert web_cache.get("https://a.example/", "links") is None

    def test_ttl_expiry(self, monkeypatch):
        clock = {"now": 0.0}
        monkeypatch.setattr(web_cache.time, "monotonic", lambda: clock["now"])
        web_cache.put("https://a.example/", "text", {"content": "x"})
        clock["now"] += web_cache.CACHE_TTL_SECONDS + 1
        assert web_cache.get("https://a.example/", "text") is None

    def test_lru_eviction(self):
        for i in range(web_cache.CACHE_MAX_ENTRIES + 5):
            web_cache.put(f"https://a.example/{i}", "text", {"content": str(i)})
        assert web_cache.size() <= web_cache.CACHE_MAX_ENTRIES
        assert web_cache.get("https://a.example/0", "text") is None  # 最旧被淘汰
        assert (
            web_cache.get(f"https://a.example/{web_cache.CACHE_MAX_ENTRIES + 4}", "text")
            is not None
        )


class TestWebFetchCache:
    def test_second_fetch_hits_cache_without_network(self):
        with respx.mock(base_url="https://example.com", assert_all_called=False) as mock:
            route = _mock_ok(mock, "/cached")
            first = _fetch_tool().execute(url="https://example.com/cached")
            second = _fetch_tool().execute(url="https://example.com/cached")

        assert first.success is True
        assert "cached" not in first.content
        assert second.success is True
        assert second.content["cached"] is True
        assert second.content["content"] == first.content["content"]
        assert route.call_count == 1  # 第二次零网络请求

    def test_refresh_bypasses_cache(self):
        with respx.mock(base_url="https://example.com", assert_all_called=False) as mock:
            route = _mock_ok(mock, "/r")
            _fetch_tool().execute(url="https://example.com/r")
            _fetch_tool().execute(url="https://example.com/r", refresh=True)

        assert route.call_count == 2

    def test_max_length_applied_on_cache_hit(self):
        with respx.mock(base_url="https://example.com", assert_all_called=False) as mock:
            _mock_ok(mock, "/long")
            _fetch_tool().execute(url="https://example.com/long", max_length=10**6)
            hit = _fetch_tool().execute(url="https://example.com/long", max_length=8)

        assert hit.success is True
        assert len(hit.content["content"]) == 8

    def test_raw_mode_not_cached(self):
        with respx.mock(base_url="https://example.com", assert_all_called=False) as mock:
            route = mock.get("/raw").mock(
                return_value=Response(200, text=_HTML_OK, headers={"content-type": "text/html"})
            )
            _fetch_tool().execute(url="https://example.com/raw", mode="raw")
            _fetch_tool().execute(url="https://example.com/raw", mode="raw")

        assert route.call_count == 2

    def test_credential_requests_not_cached(self, monkeypatch):
        """credential_domain 请求不入缓存（登录态时效语义）。"""
        from backend.tools.credential_vault import save_credential

        class _Repo:
            def __init__(self):
                self.data = {}

            def get(self, key):
                return self.data.get(key)

            def set(self, key, value, **kw):
                self.data[key] = value

        import os

        os.environ["SAGE_SECRET_SCHEME"] = "test"
        repo = _Repo()
        save_credential(
            ".example.com",
            [{"name": "SID", "value": "s", "domain": ".example.com", "path": "/"}],
            repo=repo,
        )
        import unittest.mock

        with (
            unittest.mock.patch("backend.data.settings_repo.SettingsRepository", return_value=repo),
            respx.mock(base_url="https://www.example.com", assert_all_called=False) as mock,
        ):
            route = mock.get("/paper").mock(
                return_value=Response(200, text=_HTML_OK, headers={"content-type": "text/html"})
            )
            _fetch_tool().execute(
                url="https://www.example.com/paper", credential_domain=".example.com"
            )
            _fetch_tool().execute(
                url="https://www.example.com/paper", credential_domain=".example.com"
            )

        assert route.call_count == 2  # 凭据请求每次真抓

    def test_failures_not_cached(self):
        with respx.mock(base_url="https://err.example", assert_all_called=False) as mock:
            route = mock.get("/e").mock(
                return_value=Response(500, text="boom", headers={"content-type": "text/html"})
            )
            _fetch_tool().execute(url="https://err.example/e")
            _fetch_tool().execute(url="https://err.example/e")

        # 负结果不缓存：两次 execute 都真抓；B2/AB5 起 5xx 会自动重试
        # （1 + DEFAULT_FETCH_RETRIES 次），所以总命中 = 2 × (1 + retries)。
        assert route.call_count == 2 * (1 + http_factory.DEFAULT_FETCH_RETRIES)


# ---------- Q1 web_search 查询缓存 ----------


class _CountingEngine:
    """可计数假引擎：验证缓存命中时引擎零调用。"""

    name = "fake"

    def __init__(self, results):
        self.results = results
        self.calls = 0

    def search(self, query, limit, client):
        self.calls += 1
        return list(self.results)


class TestWebSearchQueryCache:
    def _tool_with_engine(self, monkeypatch, engine):
        from backend.tools.search_config import SearchConfig

        monkeypatch.setattr("backend.tools.web_tool.resolve_engine_chain", lambda config: [engine])
        monkeypatch.setattr(
            "backend.tools.web_tool.load_search_config",
            lambda: SearchConfig(engine_order=("fake",)),
        )

    def test_second_search_hits_cache_engine_not_called(self, monkeypatch):
        engine = _CountingEngine([{"title": "T", "url": "https://a", "snippet": "S"}])
        self._tool_with_engine(monkeypatch, engine)

        first = WebSearchTool().execute(query="python")
        second = WebSearchTool().execute(query="python")

        assert first.success is True
        assert "cached" not in first.content
        assert second.success is True
        assert second.content["cached"] is True
        assert second.content["results"] == first.content["results"]
        assert engine.calls == 1  # 第二次零引擎调用

    def test_different_limit_is_different_key(self, monkeypatch):
        engine = _CountingEngine([{"title": "T", "url": "https://a", "snippet": "S"}])
        self._tool_with_engine(monkeypatch, engine)

        WebSearchTool().execute(query="q", limit=3)
        WebSearchTool().execute(query="q", limit=5)

        assert engine.calls == 2

    def test_refresh_bypasses_cache(self, monkeypatch):
        engine = _CountingEngine([{"title": "T", "url": "https://a", "snippet": "S"}])
        self._tool_with_engine(monkeypatch, engine)

        WebSearchTool().execute(query="q")
        WebSearchTool().execute(query="q", refresh=True)

        assert engine.calls == 2

    def test_empty_results_not_cached(self, monkeypatch):
        engine = _CountingEngine([])
        self._tool_with_engine(monkeypatch, engine)

        WebSearchTool().execute(query="q")
        WebSearchTool().execute(query="q")

        assert engine.calls == 2  # 空结果不缓存（负结果语义保持）

    def test_search_ttl_expiry(self, monkeypatch):
        clock = {"now": 0.0}
        monkeypatch.setattr(web_cache.time, "monotonic", lambda: clock["now"])
        engine = _CountingEngine([{"title": "T", "url": "https://a", "snippet": "S"}])
        self._tool_with_engine(monkeypatch, engine)

        WebSearchTool().execute(query="q")
        clock["now"] += web_cache.SEARCH_CACHE_TTL_SECONDS + 1
        WebSearchTool().execute(query="q")

        assert engine.calls == 2  # 5 分钟 TTL 过期后重新出网
