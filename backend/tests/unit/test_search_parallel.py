# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""web_search 并行聚合单元测试（Round 8 P1）。

默认关闭（串行 fallback 语义不变，由既有用例锁定）；开启后链上前 N 个
引擎并发搜索、按链序合并去重、单引擎失败不阻断。
"""

import pytest

from backend.tools import web_cache
from backend.tools.search_config import SearchConfig
from backend.tools.web_tool import WebSearchTool

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def _clean_search_cache():
    """Q1 查询缓存是模块级进程内存 —— 用例间清空，防跨用例命中污染。"""
    web_cache.clear()
    yield
    web_cache.clear()


class _FakeEngine:
    def __init__(self, name, results=None, error=None):
        self.name = name
        self.results = results
        self.error = error
        self.calls = 0

    def search(self, query, limit, client):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return [dict(item) for item in self.results][:limit]


def _patch(monkeypatch, config, engines):
    monkeypatch.setattr(
        "backend.tools.web_tool.load_search_config", lambda: config
    )
    monkeypatch.setattr(
        "backend.tools.web_tool.resolve_engine_chain", lambda cfg: engines
    )


def _result(url):
    return {"title": f"T:{url}", "url": url, "snippet": "S"}


class TestParallelAggregation:
    def test_merges_by_priority_and_dedups(self, monkeypatch):
        e1 = _FakeEngine("alpha", [_result("https://x/1"), _result("https://x/2")])
        e2 = _FakeEngine("beta", [_result("https://x/2"), _result("https://x/3")])
        config = SearchConfig(engine_order=("alpha", "beta"), parallel=True)
        _patch(monkeypatch, config, [e1, e2])

        result = WebSearchTool().execute(query="q")

        assert result.success is True
        assert result.content["engine"] == "parallel(alpha+beta)"
        urls = [item["url"] for item in result.content["results"]]
        assert urls == ["https://x/1", "https://x/2", "https://x/3"]  # 链序 + 去重

    def test_engine_failure_does_not_block_others(self, monkeypatch):
        e1 = _FakeEngine("alpha", error=RuntimeError("boom"))
        e2 = _FakeEngine("beta", [_result("https://x/1")])
        config = SearchConfig(engine_order=("alpha", "beta"), parallel=True)
        _patch(monkeypatch, config, [e1, e2])

        result = WebSearchTool().execute(query="q")

        assert result.success is True
        assert result.content["engine"] == "parallel(beta)"
        assert result.content["results"] == [_result("https://x/1")]
        errors = result.content["engine_errors"]
        assert any("alpha" in err for err in errors)
        assert result.content["results"] == [_result("https://x/1")]

    def test_fragment_urls_dedupe(self, monkeypatch):
        e1 = _FakeEngine("alpha", [_result("https://x/p")])
        e2 = _FakeEngine("beta", [_result("https://x/p#section")])
        config = SearchConfig(engine_order=("alpha", "beta"), parallel=True)
        _patch(monkeypatch, config, [e1, e2])

        result = WebSearchTool().execute(query="q")

        urls = [item["url"] for item in result.content["results"]]
        assert urls == ["https://x/p"]

    def test_all_empty_is_explicit_w3(self, monkeypatch):
        e1 = _FakeEngine("alpha", [])
        e2 = _FakeEngine("beta", [])
        config = SearchConfig(engine_order=("alpha", "beta"), parallel=True)
        _patch(monkeypatch, config, [e1, e2])

        result = WebSearchTool().execute(query="q")

        assert result.success is True
        assert result.content["results"] == []
        assert "note" in result.content
        assert len(result.content["engine_errors"]) == 2

    def test_all_errored_is_failure(self, monkeypatch):
        e1 = _FakeEngine("alpha", error=RuntimeError("a"))
        e2 = _FakeEngine("beta", error=RuntimeError("b"))
        config = SearchConfig(engine_order=("alpha", "beta"), parallel=True)
        _patch(monkeypatch, config, [e1, e2])

        result = WebSearchTool().execute(query="q")

        assert result.success is False
        assert "alpha" in result.error
        assert "beta" in result.error

    def test_first_n_caps_concurrency_set(self, monkeypatch):
        """parallel_first_n 截断引擎集——链上第 3 个引擎不参与。"""
        e1 = _FakeEngine("alpha", [_result("https://x/1")])
        e2 = _FakeEngine("beta", [_result("https://x/2")])
        e3 = _FakeEngine("gamma", [_result("https://x/3")])
        config = SearchConfig(
            engine_order=("alpha", "beta", "gamma"), parallel=True, parallel_first_n=2
        )
        _patch(monkeypatch, config, [e1, e2, e3])

        result = WebSearchTool().execute(query="q")

        assert result.success is True
        urls = [item["url"] for item in result.content["results"]]
        assert "https://x/3" not in urls
        assert e3.calls == 0

    def test_parallel_results_cached_and_hit(self, monkeypatch):
        from backend.tools import web_cache

        e1 = _FakeEngine("alpha", [_result("https://x/1")])
        e2 = _FakeEngine("beta", [_result("https://x/2")])
        config = SearchConfig(engine_order=("alpha", "beta"), parallel=True)
        _patch(monkeypatch, config, [e1, e2])

        first = WebSearchTool().execute(query="q")
        second = WebSearchTool().execute(query="q")

        web_cache.clear()
        assert first.content["engine"] == "parallel(alpha+beta)"
        assert "cached" not in first.content
        assert second.content["cached"] is True
        assert second.content["results"] == first.content["results"]
        assert e1.calls == 1  # 命中缓存零引擎调用
        assert e2.calls == 1

    def test_default_off_keeps_serial_semantics(self, monkeypatch):
        """parallel 缺省 false → 串行 fallback 原语义（首个非空引擎即返回）。"""
        e1 = _FakeEngine("alpha", [_result("https://x/1")])
        e2 = _FakeEngine("beta", [_result("https://x/2")])
        config = SearchConfig(engine_order=("alpha", "beta"))
        _patch(monkeypatch, config, [e1, e2])

        result = WebSearchTool().execute(query="q")

        assert result.success is True
        assert result.content["engine"] == "alpha"
        assert result.content["results"] == [_result("https://x/1")]
        assert e2.calls == 0  # 串行：首个引擎有结果则不调用后续
