# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""渲染深度单元测试（方案 2026-09-13 批次 5：R1 links/tables + R2 wait_for + R3 懒加载）。"""

import json
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from backend.domain.network_policy import NetworkMode, NetworkPolicy
from backend.tools import web_render
from backend.tools.web_render import _scroll_for_lazy_load, render_page, wait_page_ready

pytestmark = [pytest.mark.unit]


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def fake_time(monkeypatch):
    clock = _FakeClock()
    monkeypatch.setattr(web_render, "time", clock)
    return clock


# ---------- R1：渲染页 outerHTML → links/tables ----------


def _install_render(monkeypatch, evaluate_results: List[Any]) -> List[Dict[str, Any]]:
    """装配渲染链假体：实例池 + cdp_command + _evaluate_json 按序回放。"""
    calls: List[Dict[str, Any]] = []
    queue = list(evaluate_results)

    class _StubPool:
        def acquire(self):
            return SimpleNamespace()

    def _fake_cdp(session, method, params=None, target_id=None):
        calls.append({"method": method, "params": params or {}, "target": target_id})
        if method == "Target.createTarget":
            return {"targetId": "t-render"}
        if method in (
            "Page.navigate",
            "Target.closeTarget",
            # AB4（Round 5 B2）：渲染前注入 stealth 脚本，假体放行即可
            "Page.addScriptToEvaluateOnNewDocument",
        ):
            return {}
        raise AssertionError(f"unexpected method {method}")

    def _fake_eval(session, expression, target_id):
        calls.append({"method": "Runtime.evaluate", "expression": expression})
        if "readyState" in expression:
            return "complete"
        if not queue:
            raise AssertionError("evaluate 序列耗尽")
        return queue.pop(0)

    monkeypatch.setattr(web_render, "_pool", _StubPool())
    monkeypatch.setattr(web_render, "cdp_command", _fake_cdp)
    monkeypatch.setattr(web_render, "_evaluate_json", _fake_eval)
    return calls


def test_render_page_extracts_links_and_tables_from_html(fake_time, monkeypatch):
    """R1：渲染后的 outerHTML 经 html_extract 产出 links/tables（关闭 W6）。"""
    html = (
        "<html><head><title>文献列表</title></head><body>"
        '<a href="https://spa.example/p1">论文一</a>'
        "<table><tr><th>年份</th><th>引用</th></tr>"
        "<tr><td>2025</td><td>120</td></tr></table>"
        "</body></html>"
    )
    # 序列：settle 内文长度 ×3（稳定）→ 滚动 scrollHeight ×3（稳定）→ outerHTML
    evaluate_results: List[Any] = [
        40,
        40,
        40,
        1000,
        1000,
        1000,
        json.dumps({"url": "https://spa.example/", "title": "文档", "html": html}),
    ]
    _install_render(monkeypatch, evaluate_results)

    result = render_page("https://spa.example/", NetworkPolicy(mode=NetworkMode.ONLINE))

    assert result["rendered"] is True
    assert result["title"] == "文献列表"
    assert "论文一" in result["content"]
    assert result["links"][-1] == {"text": "论文一", "url": "https://spa.example/p1"}
    assert result["tables"][0][0] == ["年份", "引用"]
    assert result["truncated"] is False


def test_render_page_truncates_oversized_html(fake_time, monkeypatch):
    """outerHTML 达 RENDER_HTML_CAP 上限 → truncated 标记。"""
    html = "<html><body>" + "字" * web_render.RENDER_HTML_CAP + "</body></html>"
    evaluate_results: List[Any] = [
        0,
        0,
        0,
        0,
        0,
        0,
        json.dumps({"url": "https://spa.example/", "html": html}),
    ]
    _install_render(monkeypatch, evaluate_results)

    result = render_page("https://spa.example/", NetworkPolicy(mode=NetworkMode.ONLINE))
    assert result["truncated"] is True


def test_render_page_falls_back_to_text_without_html(fake_time, monkeypatch):
    """页面无 html 返回（旧读取形态）→ innerText 回退路径。"""
    evaluate_results: List[Any] = [0, 0, 0, 0, 0, 0, json.dumps({"text": "纯文本正文"})]
    _install_render(monkeypatch, evaluate_results)

    result = render_page("https://spa.example/", NetworkPolicy(mode=NetworkMode.ONLINE))
    assert result["content"] == "纯文本正文"
    assert result["links"] == []
    assert result["tables"] == []


# ---------- R2：wait_for 选择器等待 ----------


def test_wait_page_ready_polls_wait_for_until_found(fake_time, monkeypatch):
    expressions: List[str] = []

    def _fake_eval(session, expression, target_id):
        expressions.append(expression)
        if "readyState" in expression:
            return "complete"
        if "querySelector" in expression:
            return len([e for e in expressions if "querySelector" in e]) >= 2
        return 100  # settle 内文长度恒定 → 立即稳定

    monkeypatch.setattr(web_render, "_evaluate_json", _fake_eval)
    wait_page_ready(SimpleNamespace(), "t1", wait_for="#result-list")

    assert any("querySelector" in e and "#result-list" in e for e in expressions)


def test_wait_page_ready_wait_for_timeout_does_not_fail(fake_time, monkeypatch):
    """wait_for 永不出现 → 不抛错，settle 后正常返回（半截内容好过没有）。"""
    def _fake_eval(session, expression, target_id):
        if "readyState" in expression:
            return "complete"
        if "querySelector" in expression:
            return False
        return 10

    monkeypatch.setattr(web_render, "_evaluate_json", _fake_eval)
    wait_page_ready(SimpleNamespace(), None, wait_for=".never-appears")
    # 等待窗口有界（readyState 0 轮 + wait_for 满窗 ≈ 10s + settle ≤3s）
    assert fake_time.now < 20.0


def test_render_page_passes_wait_for(fake_time, monkeypatch):
    """render_page 透传 wait_for → evaluate 链里出现 querySelector。"""
    html = "<html><body>已加载</body></html>"
    calls = _install_render(
        monkeypatch, [True, 10, 10, 10, 100, 100, 100, json.dumps({"html": html})]
    )
    render_page(
        "https://spa.example/", NetworkPolicy(mode=NetworkMode.ONLINE), wait_for=".item"
    )
    evaluated = [call.get("expression", "") for call in calls]
    assert any("querySelector" in e and ".item" in e for e in evaluated)


# ---------- R3：懒加载触底滚动 ----------


def test_scroll_stops_when_height_stabilises(fake_time, monkeypatch):
    calls: List[str] = []
    heights = [1000, 2000, 2000, 2000]

    def _fake_eval(session, expression, target_id):
        calls.append(expression)
        return heights.pop(0) if len(heights) > 1 else heights[0]

    monkeypatch.setattr(web_render, "_evaluate_json", _fake_eval)
    monkeypatch.setattr(web_render, "_LAZY_SCROLL_MAX_ROUNDS", 6)
    _scroll_for_lazy_load(SimpleNamespace(), None)
    # 1000 → 2000（增长）→ 稳定 ×2 轮 → 第 4 次提前结束（上限 6 未触顶）
    assert len(calls) == 4


def test_scroll_caps_at_max_rounds(fake_time, monkeypatch):
    calls: List[str] = []

    def _fake_eval(session, expression, target_id):
        calls.append(expression)
        return len(calls) * 100  # 高度一直涨

    monkeypatch.setattr(web_render, "_evaluate_json", _fake_eval)
    _scroll_for_lazy_load(SimpleNamespace(), None)
    assert len(calls) == web_render._LAZY_SCROLL_MAX_ROUNDS


def test_scroll_swallows_cdp_error(fake_time, monkeypatch):
    def _fake_eval(session, expression, target_id):
        raise web_render.BrowserCDPError("gone")

    monkeypatch.setattr(web_render, "_evaluate_json", _fake_eval)
    _scroll_for_lazy_load(SimpleNamespace(), None)  # 不抛即通过
