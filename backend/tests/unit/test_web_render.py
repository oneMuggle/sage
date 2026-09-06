"""web_render 单元测试（W1/W2，docs/plans/2026-09-06_web-dynamic-render-access.md）。

覆盖：JS 壳判定纯函数、页面就绪等待（readyState + 正文稳定）、渲染入口
（导航/读取/标签页清理/门禁/错误映射）、渲染实例池生命周期。CDP 交互
全部 stub，时间用假时钟 —— 测试零真实等待。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from backend.domain.network_policy import NetworkMode, NetworkPolicy
from backend.tools import browser_cdp, web_render
from backend.tools.web_render import (
    RENDER_IDLE_TIMEOUT_SECONDS,
    RENDER_POOL_ID,
    RenderError,
    looks_like_js_shell,
    render_page,
    wait_page_ready,
)

pytestmark = [pytest.mark.unit]


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def fake_time(monkeypatch):
    clock = _FakeClock()
    monkeypatch.setattr(web_render, "time", clock)
    return clock


# ---------------------------------------------------------------------------
# JS 壳判定（auto 模式）
# ---------------------------------------------------------------------------


def test_shell_detection_matches_spa_mount():
    html = '<html><head><title>App</title></head><body><div id="root"></div></body></html>'
    assert looks_like_js_shell(html, "") is True


def test_shell_detection_matches_script_heavy_page():
    html = "<html><head>" + ("<script>var x=1;</script>" * 10) + "</head><body>hi</body></html>"
    assert looks_like_js_shell(html, "hi") is True


def test_shell_detection_passes_static_pages():
    assert looks_like_js_shell("<html><body>hello</body></html>", "hello") is False
    long_text = "甲" * 600
    assert looks_like_js_shell("<p>" + long_text + "</p>", long_text) is False
    assert looks_like_js_shell("", "") is False


def test_shell_detection_short_body_without_markers_is_static():
    """无脚本、无挂载点的小页面不是壳 —— 静态站零开销不回退。"""
    html = "<html><body><p>目录</p></body></html>"
    assert looks_like_js_shell(html, "目录") is False


# ---------------------------------------------------------------------------
# 页面就绪等待（W2）
# ---------------------------------------------------------------------------


def test_wait_page_ready_returns_after_text_stabilises(fake_time, monkeypatch):
    reads = iter(["loading", "complete", 0, 1200, 1200, 1200])

    def _fake_eval(session, expression, target_id):
        return next(reads)

    monkeypatch.setattr(web_render, "_evaluate_json", _fake_eval)
    wait_page_ready(SimpleNamespace(), "t1")
    # 稳定即返回（0.3 就绪轮询 + 3 轮 0.4 稳定轮询），不等满任一窗口
    assert fake_time.now < 5.0


def test_wait_page_ready_settle_caps_at_max_window(fake_time, monkeypatch):
    ticks = iter(range(1000))

    def _fake_eval(session, expression, target_id):
        if "readyState" in expression:
            return "complete"
        return next(ticks)  # 内文长度一直变

    monkeypatch.setattr(web_render, "_evaluate_json", _fake_eval)
    wait_page_ready(SimpleNamespace(), None)
    assert web_render._SETTLE_MAX_SECONDS <= fake_time.now < 10.0


def test_wait_page_ready_swallows_context_destroyed(fake_time, monkeypatch):
    def _fake_eval(session, expression, target_id):
        raise browser_cdp.BrowserCDPError("target crashed")

    monkeypatch.setattr(web_render, "_evaluate_json", _fake_eval)
    wait_page_ready(SimpleNamespace(), None)  # 不抛即通过
    assert fake_time.now == 0.0


# ---------------------------------------------------------------------------
# 渲染入口
# ---------------------------------------------------------------------------


def _install_render(
    monkeypatch, page_json: str, lengths: List[int] = None
) -> List[Dict[str, Any]]:
    """装配渲染链假体：实例池 + cdp_command + _evaluate_json，返回调用记录。"""
    lengths = lengths if lengths is not None else [0, 0, 0]
    calls: List[Dict[str, Any]] = []

    class _StubPool:
        def acquire(self):
            return SimpleNamespace()  # 绝不真启动浏览器

    def _fake_cdp(session, method, params=None, target_id=None):
        calls.append({"method": method, "params": params or {}, "target": target_id})
        if method == "Target.createTarget":
            return {"targetId": "t-render"}
        if method in ("Page.navigate", "Target.closeTarget"):
            return {}
        raise AssertionError(f"unexpected method {method}")

    def _fake_eval(session, expression, target_id):
        calls.append({"method": "Runtime.evaluate"})
        if "readyState" in expression:
            return "complete"
        if "JSON.stringify" in expression:
            return page_json  # 最终内容读取（表达式同样含 innerText，先按形态区分）
        return lengths.pop(0) if len(lengths) > 1 else lengths[0]

    monkeypatch.setattr(web_render, "_pool", _StubPool())
    monkeypatch.setattr(web_render, "cdp_command", _fake_cdp)
    monkeypatch.setattr(web_render, "_evaluate_json", _fake_eval)
    return calls


def test_render_page_returns_rendered_content(fake_time, monkeypatch):
    page_json = json.dumps({"url": "https://spa.example/", "title": "SPA 页", "text": "渲染正文"})
    calls = _install_render(monkeypatch, page_json, lengths=[5, 5, 5])

    result = render_page("https://spa.example/", NetworkPolicy(mode=NetworkMode.ONLINE))

    assert result["rendered"] is True
    assert result["title"] == "SPA 页"
    assert result["content"] == "渲染正文"
    assert result["truncated"] is False
    methods = [call["method"] for call in calls]
    assert methods[0] == "Target.createTarget"  # 浏览器级调用，无 target
    navigate_call = next(call for call in calls if call["method"] == "Page.navigate")
    assert navigate_call["target"] == "t-render"
    close_calls = [call for call in calls if call["method"] == "Target.closeTarget"]
    assert len(close_calls) == 1  # 渲染标签页必清理
    assert close_calls[0]["params"]["targetId"] == "t-render"


def test_render_page_policy_rejected():
    with pytest.raises(RenderError, match="host_not_allowed"):
        render_page("https://evil.example/", NetworkPolicy(mode=NetworkMode.INTRANET))


def test_render_page_navigation_error_text(fake_time, monkeypatch):
    class _StubPool:
        def acquire(self):
            return SimpleNamespace()

    def _fake_cdp(session, method, params=None, target_id=None):
        if method == "Target.createTarget":
            return {"targetId": "t"}
        if method in ("Page.navigate", "Target.closeTarget"):
            return {"errorText": "ERR_CONNECTION_REFUSED"} if method == "Page.navigate" else {}
        raise AssertionError(method)

    monkeypatch.setattr(web_render, "_pool", _StubPool())
    monkeypatch.setattr(web_render, "cdp_command", _fake_cdp)
    with pytest.raises(RenderError, match="ERR_CONNECTION_REFUSED"):
        render_page("https://spa.example/", NetworkPolicy(mode=NetworkMode.ONLINE))


def test_render_page_maps_cdp_error_to_guidance(fake_time, monkeypatch):
    _install_render(monkeypatch, json.dumps({"text": "x"}))

    def _boom(session, method, params=None, target_id=None):
        raise browser_cdp.BrowserCDPError("socket gone")

    monkeypatch.setattr(web_render, "cdp_command", _boom)
    with pytest.raises(RenderError) as exc_info:
        render_page("https://spa.example/", NetworkPolicy(mode=NetworkMode.ONLINE))
    # 失败语义：给出手动渲染 / 关闭渲染的指引（W1）
    assert "browser_launch" in str(exc_info.value)
    assert "render=never" in str(exc_info.value)


def test_render_page_truncation_flag(fake_time, monkeypatch):
    page_json = json.dumps({"text": "x" * web_render.RENDER_TEXT_CAP})
    _install_render(monkeypatch, page_json, lengths=[0, 0, 0])
    result = render_page("https://spa.example/", NetworkPolicy(mode=NetworkMode.ONLINE))
    assert result["truncated"] is True


# ---------------------------------------------------------------------------
# 渲染实例池
# ---------------------------------------------------------------------------


class _FakePoolSession:
    def __init__(self, alive: bool = True):
        self.browser_id = RENDER_POOL_ID
        self.alive = alive
        self.user_data_dir = "/tmp/unused"
        self.process = SimpleNamespace(
            terminate=lambda: None, wait=lambda timeout=None: 0, kill=lambda: None
        )

    def is_alive(self) -> bool:
        return self.alive


def test_renderer_pool_reuses_live_session(monkeypatch):
    pool = web_render._RendererPool()
    created = []

    def _fake_launch(headless, browser_id=None):
        assert headless is True
        assert browser_id == RENDER_POOL_ID  # 保留 id，用户实例解析不受干扰
        session = _FakePoolSession()
        created.append(session)
        return session

    monkeypatch.setattr(web_render, "launch_browser", _fake_launch)
    first = pool.acquire()
    second = pool.acquire()
    assert first is second
    assert len(created) == 1

    first.alive = False  # 进程死亡 → 下次 acquire 重建
    third = pool.acquire()
    assert third is not first
    assert len(created) == 2


def test_renderer_pool_rebuilds_after_idle_timeout(monkeypatch):
    pool = web_render._RendererPool()
    clock = _FakeClock()
    monkeypatch.setattr(web_render, "time", clock)
    created = []

    def _fake_launch(headless, browser_id=None):
        session = _FakePoolSession()
        created.append(session)
        return session

    monkeypatch.setattr(web_render, "launch_browser", _fake_launch)
    first = pool.acquire()
    clock.now += RENDER_IDLE_TIMEOUT_SECONDS + 1
    second = pool.acquire()
    assert second is not first
    assert len(created) == 2


def test_reserved_id_excluded_from_user_instance_resolution():
    """保留 id 不算用户实例：渲染池常驻时 browser_snapshot 仍能免 id 解析。"""
    manager = browser_cdp.BrowserSessionManager()
    manager.register(_FakePoolSession())  # 仅渲染池在场
    assert manager.get(None) is None

    user = SimpleNamespace(browser_id="b1")
    manager.register(user)
    assert manager.get(None) is user  # 唯一用户实例照常免 id

    assert manager.get(RENDER_POOL_ID) is not None  # 显式指名仍可达
