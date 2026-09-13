# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""web_search 多引擎链单元测试（方案 2026-09-13 批次 1）。

覆盖：Bing/DDG HTML 解析（含跳转 URL 还原）、Tavily/智谱 API 引擎、
resolve_engine_chain 装配规则、search_config fail-safe 与 enc: key 解包、
WebSearchTool 链式 fallback 语义（首个非空胜出 / 全空 W3 / 全挂失败）。
"""

import base64
import json
from unittest.mock import patch

import httpx
import pytest
import respx
from httpx import Response

from backend.tools.search_config import (
    DEFAULT_ENGINE_ORDER,
    SETTINGS_KEY_SEARCH_CONFIG,
    SearchConfig,
    load_search_config,
)
from backend.tools.search_engines import (
    BingEngine,
    DuckDuckGoEngine,
    TavilyEngine,
    ZhipuEngine,
    resolve_engine_chain,
)
from backend.tools.web_tool import WebSearchTool

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def _force_test_secret_scheme(monkeypatch):
    """enc: 加解密走确定性 test 方案（base64），保证 CI 可复现。"""
    monkeypatch.setenv("SAGE_SECRET_SCHEME", "test")


def _b64url(raw: str) -> str:
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


# ---------- BingEngine ----------


class TestBingEngine:
    def test_parses_b_algo_results(self):
        html = (
            "<html><body><ol>"
            '<li class="b_algo"><h2><a href="https://docs.python.org/3/" '
            'h="ID=SERP">Python 3 文档</a></h2>'
            '<div class="b_caption"><p>官方文档与教程</p></div></li>'
            '<li class="b_algo"><h2><a href="https://www.python.org/">Python 官网</a></h2>'
            "<div><p>下载与安装</p></div></li>"
            "</ol></body></html>"
        )
        engine = BingEngine()
        with respx.mock(base_url="https://www.bing.com") as mock:
            mock.get("/search").mock(return_value=Response(200, text=html))
            with httpx.Client() as client:
                results = engine.search("python", 5, client=client)

        assert len(results) == 2
        assert results[0]["title"] == "Python 3 文档"
        assert results[0]["url"] == "https://docs.python.org/3/"
        assert results[0]["snippet"] == "官方文档与教程"
        assert results[1]["url"] == "https://www.python.org/"

    def test_resolves_cka_redirect_url(self):
        """Bing 跳转包装 ``ck/a?...&u=a1<base64url>`` 还原真实 URL。"""
        real = "https://example.org/deep/page"
        encoded = "a1" + _b64url(real)
        html = (
            '<li class="b_algo"><h2><a '
            f'href="https://www.bing.com/ck/a?!&amp;p=abc&amp;u={encoded}&amp;ntb=1"'
            ">示例</a></h2></li>"
        )
        engine = BingEngine()
        with respx.mock(base_url="https://www.bing.com") as mock:
            mock.get("/search").mock(return_value=Response(200, text=html))
            with httpx.Client() as client:
                results = engine.search("q", 5, client=client)

        assert results[0]["url"] == real

    def test_unresolvable_redirect_keeps_href(self):
        """u= 参数缺失/解码失败时原样返回 href（不丢结果）。"""
        html = (
            '<li class="b_algo"><h2><a '
            'href="https://www.bing.com/ck/a?!&amp;p=xyz">示例</a></h2></li>'
        )
        engine = BingEngine()
        with respx.mock(base_url="https://www.bing.com") as mock:
            mock.get("/search").mock(return_value=Response(200, text=html))
            with httpx.Client() as client:
                results = engine.search("q", 5, client=client)

        assert results[0]["url"] == "https://www.bing.com/ck/a?!&p=xyz"

    def test_http_error_raises(self):
        engine = BingEngine()
        with respx.mock(base_url="https://www.bing.com") as mock, httpx.Client() as client:
            mock.get("/search").mock(return_value=Response(403, text="forbidden"))
            with pytest.raises(httpx.HTTPError):
                engine.search("q", 5, client=client)


# ---------- DuckDuckGoEngine（自 web_tool 原样迁入，回归锁） ----------


class TestDuckDuckGoEngine:
    def test_parses_and_resolves_uddg(self):
        html = (
            '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs'
            '.python.org%2F3%2F&amp;rut=abc">Python 文档</a>\n'
            '<a class="result__snippet" href="x">官方文档站点</a>'
        )
        engine = DuckDuckGoEngine()
        with respx.mock(base_url="https://html.duckduckgo.com") as mock:
            mock.get("/html/").mock(return_value=Response(200, text=html))
            with httpx.Client() as client:
                results = engine.search("python docs", 5, client=client)

        assert results[0]["url"] == "https://docs.python.org/3/"
        assert results[0]["title"] == "Python 文档"
        assert results[0]["snippet"] == "官方文档站点"

    def test_empty_html_returns_empty_list(self):
        engine = DuckDuckGoEngine()
        with respx.mock(base_url="https://html.duckduckgo.com") as mock:
            mock.get("/html/").mock(return_value=Response(200, text="<html></html>"))
            with httpx.Client() as client:
                assert engine.search("q", 5, client=client) == []


# ---------- API 引擎 ----------


class TestApiEngines:
    def test_tavily_engine(self):
        engine = TavilyEngine("tvly-key")
        with respx.mock(base_url="https://api.tavily.com") as mock:
            route = mock.post("/search").mock(
                return_value=Response(
                    200,
                    json={
                        "results": [
                            {"title": "T1", "url": "https://a.example", "content": "C1"},
                            {"title": "T2", "url": "https://b.example", "content": "C2"},
                        ]
                    },
                )
            )
            with httpx.Client() as client:
                results = engine.search("q", 2, client=client)

        assert route.called
        request = route.calls.last.request
        assert b"tvly-key" in request.content
        assert results[0] == {"title": "T1", "url": "https://a.example", "snippet": "C1"}

    def test_zhipu_engine(self):
        engine = ZhipuEngine("zp-key")
        with respx.mock(base_url="https://open.bigmodel.cn") as mock:
            route = mock.post("/api/paas/v4/web_search").mock(
                return_value=Response(
                    200,
                    json={
                        "search_result": [
                            {"title": "R1", "link": "https://z.example", "content": "K1"}
                        ]
                    },
                )
            )
            with httpx.Client() as client:
                results = engine.search("q", 5, client=client)

        request = route.calls.last.request
        assert request.headers["Authorization"] == "Bearer zp-key"
        assert results[0]["url"] == "https://z.example"


# ---------- resolve_engine_chain ----------


class TestResolveEngineChain:
    def test_default_order_bing_then_ddg(self):
        chain = resolve_engine_chain(SearchConfig())
        assert [engine.name for engine in chain] == ["bing", "ddg"]

    def test_api_engine_skipped_without_key(self):
        chain = resolve_engine_chain(SearchConfig(engine_order=("tavily", "ddg")))
        assert [engine.name for engine in chain] == ["ddg"]

    def test_api_engine_included_with_key(self):
        chain = resolve_engine_chain(
            SearchConfig(engine_order=("zhipu", "bing"), zhipu_key="k")
        )
        assert [engine.name for engine in chain] == ["zhipu", "bing"]

    def test_none_config_falls_back_to_default(self):
        chain = resolve_engine_chain(None)
        assert [engine.name for engine in chain] == list(DEFAULT_ENGINE_ORDER)


# ---------- load_search_config ----------


class TestLoadSearchConfig:
    def _repo(self, raw):
        class _Repo:
            def get(self, key):
                if key != SETTINGS_KEY_SEARCH_CONFIG:
                    raise AssertionError(f"unexpected key {key}")
                return raw

        return _Repo()

    def test_missing_key_returns_default(self):
        config = load_search_config(self._repo(None))
        assert config.engine_order == DEFAULT_ENGINE_ORDER
        assert config.tavily_key == ""
        assert config.zhipu_key == ""

    def test_invalid_json_fails_safe(self):
        assert load_search_config(self._repo("not json")).engine_order == DEFAULT_ENGINE_ORDER
        assert load_search_config(self._repo("[1,2]")).engine_order == DEFAULT_ENGINE_ORDER

    def test_unknown_engines_filtered_out(self):
        config = load_search_config(
            self._repo(json.dumps({"order": ["bing", "junk", "ddg"]}))
        )
        assert config.engine_order == ("bing", "ddg")

    def test_plain_key_passthrough(self):
        config = load_search_config(
            self._repo(json.dumps({"order": ["tavily"], "tavily_key": "tvly-plain"}))
        )
        assert config.tavily_key == "tvly-plain"

    def test_encrypted_key_unwrapped(self):
        from backend.services.secret_box import encrypt_secret

        wrapped = encrypt_secret("tvly-secret", account="search:tavily")
        assert wrapped.startswith("enc:")
        config = load_search_config(
            self._repo(json.dumps({"order": ["tavily"], "tavily_key": wrapped}))
        )
        assert config.tavily_key == "tvly-secret"

    def test_broken_encrypted_key_treated_as_unconfigured(self):
        config = load_search_config(
            self._repo(json.dumps({"order": ["tavily"], "tavily_key": "enc:test:v1:!!!"}))
        )
        assert config.tavily_key == ""


# ---------- WebSearchTool 链式语义 ----------


class TestWebSearchToolChain:
    def _patch_config(self, config):
        return patch("backend.tools.web_tool.load_search_config", return_value=config)

    def test_first_non_empty_engine_wins_and_records_name(self):
        config = SearchConfig(engine_order=("tavily", "ddg"), tavily_key="k")
        with self._patch_config(config), respx.mock(base_url="https://api.tavily.com") as mock:
            mock.post("/search").mock(
                return_value=Response(
                    200,
                    json={"results": [{"title": "T", "url": "https://a", "content": "C"}]},
                )
            )
            result = WebSearchTool().execute(query="q")

        assert result.success is True
        assert result.content["engine"] == "tavily"
        assert result.content["results"][0]["url"] == "https://a"

    def test_falls_back_to_next_engine_on_error(self):
        """首选引擎异常（respx 未 mock 的 bing）→ 降级 DDG mock。"""
        html = (
            '<a class="result__a" href="https://ddg.example">DDG 结果</a>\n'
            '<a class="result__snippet" href="x">S</a>'
        )
        with self._patch_config(
            SearchConfig(engine_order=("bing", "ddg"))
        ), respx.mock(base_url="https://html.duckduckgo.com") as mock:
            mock.get("/html/").mock(return_value=Response(200, text=html))
            result = WebSearchTool().execute(query="q")

        assert result.success is True
        assert result.content["engine"] == "ddg"
        assert result.content["results"][0]["title"] == "DDG 结果"

    def test_all_engines_empty_is_explicit_with_engine_errors(self):
        """全链正常完成但无结果 → W3 空结果 + note + 各引擎诊断（不伪造）。"""
        with self._patch_config(SearchConfig(engine_order=("ddg",))), respx.mock(
            base_url="https://html.duckduckgo.com"
        ) as mock:
            mock.get("/html/").mock(
                return_value=Response(200, text="<html><body>none</body></html>")
            )
            result = WebSearchTool().execute(query="q")

        assert result.success is True
        assert result.content["results"] == []
        assert "note" in result.content
        assert any("ddg" in item for item in result.content["engine_errors"])

    def test_all_engines_errored_is_failure_with_combined_error(self):
        with self._patch_config(SearchConfig(engine_order=("ddg",))), respx.mock(
            base_url="https://html.duckduckgo.com"
        ) as mock:
            mock.get("/html/").mock(return_value=Response(500, text="down"))
            result = WebSearchTool().execute(query="q")

        assert result.success is False
        assert "ddg" in result.error

    def test_empty_chain_is_failure(self):
        with self._patch_config(SearchConfig(engine_order=("tavily",))):  # 无 key → 空链
            result = WebSearchTool().execute(query="q")
        assert result.success is False
