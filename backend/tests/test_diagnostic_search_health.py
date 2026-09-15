"""搜索引擎健康自检端点测试（Round 9 R9-2）。

GET /api/v1/diagnostic/search-engines —— 逐个探测配置链上的引擎，
未配置 key 的 API 引擎如实话报"未配置"。引擎链与配置均 monkeypatch，
探测结果用假引擎直接返回（不触网）。
"""

import pytest
from fastapi.testclient import TestClient

from backend.main import app

pytestmark = [pytest.mark.unit]


class _FakeEngine:
    """假引擎：check 返回预置结果（绕过基类的真实 search 探测）。"""

    def __init__(self, name, outcome):
        self.name = name
        self._outcome = outcome

    def check(self, client):
        return self._outcome


def _patch_chain(monkeypatch, engines, config=None):
    import backend.tools.search_config as sc
    import backend.tools.search_engines as se

    monkeypatch.setattr(se, "resolve_engine_chain", lambda cfg: engines)
    if config is None:
        config = type(
            "_Cfg",
            (),
            {"engine_order": ("bing", "ddg", "tavily", "zhipu"), "parallel": False},
        )()
    monkeypatch.setattr(sc, "load_search_config", lambda: config)


def test_reports_configured_and_unconfigured(monkeypatch):
    ok_engine = _FakeEngine("bing", {"ok": True, "latency_ms": 120, "detail": "返回 1 条结果"})
    fail_engine = _FakeEngine("ddg", {"ok": False, "latency_ms": 900, "detail": "连接失败"})
    _patch_chain(monkeypatch, [ok_engine, fail_engine])

    with TestClient(app) as client:
        r = client.get("/api/v1/diagnostic/search-engines")

    assert r.status_code == 200
    data = r.json()
    by_name = {e["name"]: e for e in data["engines"]}
    assert set(by_name) == {"bing", "ddg", "tavily", "zhipu"}
    assert by_name["bing"]["ok"] is True
    assert by_name["bing"]["latencyMs"] == 120
    assert by_name["ddg"]["ok"] is False
    assert by_name["ddg"]["detail"] == "连接失败"
    # 未配 key 的 API 引擎：如实上报"未配置"
    assert by_name["tavily"]["configured"] is False
    assert by_name["tavily"]["ok"] is False
    assert by_name["zhipu"]["configured"] is False


def test_reports_api_engines_with_keys(monkeypatch):
    tavily = _FakeEngine("tavily", {"ok": True, "latency_ms": 300, "detail": "返回 1 条结果"})
    zhipu = _FakeEngine("zhipu", {"ok": False, "latency_ms": 50, "detail": "key 无效"})
    _patch_chain(monkeypatch, [tavily, zhipu])

    with TestClient(app) as client:
        r = client.get("/api/v1/diagnostic/search-engines")

    by_name = {e["name"]: e for e in r.json()["engines"]}
    assert by_name["tavily"]["configured"] is True
    assert by_name["tavily"]["ok"] is True
    assert by_name["zhipu"]["ok"] is False
    assert by_name["zhipu"]["detail"] == "key 无效"
