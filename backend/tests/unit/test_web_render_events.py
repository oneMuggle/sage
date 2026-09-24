# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""web_render 事件状态/通道接线测试（R22 批次 2 / R23 / R24）。

从 test_web_render.py 拆出（架构 800 行门禁）：只保留渲染事件化相关
用例；壳判定/就绪等待/AU5 凭据等用例仍在原文件。CDP 交互全部 stub。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from backend.domain.network_policy import NetworkMode, NetworkPolicy
from backend.tools import web_render
from backend.tools.web_render import render_page

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


def _install_render(monkeypatch, page_json: str, lengths: List[int] = None) -> List[Dict[str, Any]]:
    """装配渲染链假体：实例池 + cdp_command + _evaluate_json，返回调用记录。"""
    lengths = lengths if lengths is not None else [0, 0, 0]
    calls: List[Dict[str, Any]] = []

    class _StubPool:
        def acquire(self):
            return SimpleNamespace(browser_id="b-render")  # 绝不真启动浏览器

    def _fake_cdp(session, method, params=None, target_id=None):
        calls.append({"method": method, "params": params or {}, "target": target_id})
        if method == "Target.createTarget":
            return {"targetId": "t-render"}
        if method in (
            "Page.navigate",
            "Target.closeTarget",
            "Page.addScriptToEvaluateOnNewDocument",
        ):
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


# ---------- R22 批次 2：Network 事件状态优先 ----------


def test_render_page_prefers_event_tracked_status(fake_time, monkeypatch):
    """事件通道有 Document 记录时优先事件状态（可含 302 中间 hop 的拦截码）。"""
    page_json = json.dumps({"url": "https://spa.example/", "title": "t", "text": "x"})
    _install_render(monkeypatch, page_json, lengths=[0, 0, 0])
    detached: Any = []
    monkeypatch.setattr(web_render, "ensure_network_tracking", lambda bid, tid: "sess-e")
    monkeypatch.setattr(
        web_render,
        "get_tracked_response",
        lambda bid, sid: {"url": "https://a.example/", "status": 403}
        if sid == "sess-e"
        else None,
    )
    monkeypatch.setattr(
        web_render, "detach_network_session", lambda bid, sid: detached.append((bid, sid))
    )

    result = render_page("https://spa.example/", NetworkPolicy(mode=NetworkMode.ONLINE))

    assert result["rendered_status"] == 403
    assert detached == [("b-render", "sess-e")]


def test_render_page_event_status_absent_falls_back_to_navigation_timing(
    fake_time, monkeypatch
):
    """事件无记录（通道未建立 / 未捕获）→ Navigation Timing 兜底不被覆盖。"""
    page_json = json.dumps(
        {"url": "https://spa.example/", "title": "t", "text": "x", "status": 503}
    )
    _install_render(monkeypatch, page_json, lengths=[0, 0, 0])
    monkeypatch.setattr(web_render, "ensure_network_tracking", lambda bid, tid: "sess-e")
    monkeypatch.setattr(web_render, "get_tracked_response", lambda bid, sid: None)

    result = render_page("https://spa.example/", NetworkPolicy(mode=NetworkMode.ONLINE))

    assert result["rendered_status"] == 503


# ---------- R23：渲染池事件通道接线 ----------


def test_render_page_wires_pool_event_channel(fake_time, monkeypatch):
    """渲染前为池浏览器接事件通道（R23）：以会话的 browser_id/port/ws_path 调用。"""
    page_json = json.dumps({"url": "https://spa.example/", "title": "t", "text": "x"})
    _install_render(monkeypatch, page_json, lengths=[0, 0, 0])

    class _Pool:
        def acquire(self):
            return SimpleNamespace(
                browser_id="b-render", port=9222, ws_path="/devtools/browser/x"
            )

    monkeypatch.setattr(web_render, "_pool", _Pool())
    wired = []
    monkeypatch.setattr(
        web_render,
        "_ensure_pool_channel",
        lambda session: wired.append(
            (session.browser_id, session.port, session.ws_path)
        )
        or True,
    )

    render_page("https://spa.example/", NetworkPolicy(mode=NetworkMode.ONLINE))

    assert wired == [("b-render", 9222, "/devtools/browser/x")]


def test_render_page_survives_channel_wire_failure(fake_time, monkeypatch):
    """事件通道建立抛错（_ensure_pool_channel 内部吞掉）不阻断渲染主流程。"""
    page_json = json.dumps({"url": "https://spa.example/", "title": "t", "text": "x"})
    _install_render(monkeypatch, page_json, lengths=[0, 0, 0])
    monkeypatch.setattr(
        web_render,
        "start_event_channel",
        lambda *args: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    # 真实 _ensure_pool_channel 走 except → False；stub 会话缺 port 也走同路径
    monkeypatch.setattr(
        web_render,
        "ensure_network_tracking",
        lambda bid, tid: None,
    )

    result = render_page("https://spa.example/", NetworkPolicy(mode=NetworkMode.ONLINE))

    assert result["rendered"] is True


def test_render_page_records_event_metrics(fake_time, monkeypatch):
    """R24：渲染埋点事件命中率——通道就绪与事件状态被采用各计一次。"""
    page_json = json.dumps({"url": "https://spa.example/", "title": "t", "text": "x"})
    _install_render(monkeypatch, page_json, lengths=[0, 0, 0])
    monkeypatch.setattr(web_render, "_ensure_pool_channel", lambda session: True)
    monkeypatch.setattr(web_render, "ensure_network_tracking", lambda bid, tid: "sess-e")
    monkeypatch.setattr(
        web_render,
        "get_tracked_response",
        lambda bid, sid: {"url": "https://a.example/", "status": 200}
        if sid == "sess-e"
        else None,
    )
    recorded: Any = []
    monkeypatch.setattr(
        web_render, "record_render_event", lambda c, t: recorded.append((c, t))
    )

    result = render_page("https://spa.example/", NetworkPolicy(mode=NetworkMode.ONLINE))

    assert result["rendered_status"] == 200
    assert recorded == [(True, True)]


# ---------- R30：wait_for 完整度可观测 ----------


def test_wait_page_ready_reports_wait_for_hit(fake_time, monkeypatch):
    """wait_for 选择器在窗口内出现 → True。"""
    evals = iter(["complete", True, 5, 5, 5])
    monkeypatch.setattr(web_render, "_evaluate_json", lambda s, e, t: next(evals))
    assert web_render.wait_page_ready(SimpleNamespace(), "t1", wait_for=".item") is True


def test_wait_page_ready_reports_wait_for_miss(fake_time, monkeypatch):
    """readyState 达标后选择器窗口耗尽 → False。"""
    calls = {"n": 0}

    def _eval(session, expression, target_id):
        calls["n"] += 1
        return "complete" if calls["n"] == 1 else 0  # 选择器永不出现

    monkeypatch.setattr(web_render, "_evaluate_json", _eval)
    assert web_render.wait_page_ready(SimpleNamespace(), "t1", wait_for=".never") is False


def test_wait_page_ready_without_wait_for_is_true(fake_time, monkeypatch):
    evals = iter(["complete", 5, 5, 5])
    monkeypatch.setattr(web_render, "_evaluate_json", lambda s, e, t: next(evals))
    assert web_render.wait_page_ready(SimpleNamespace(), "t1") is True


def test_render_page_reports_wait_for_satisfied(fake_time, monkeypatch):
    page_json = json.dumps({"url": "https://spa.example/", "title": "t", "text": "x"})
    _install_render(monkeypatch, page_json, lengths=[0, 0, 0])
    inner = web_render._evaluate_json

    def _eval(session, expression, target_id):
        if "querySelector" in expression:
            return True
        return inner(session, expression, target_id)

    monkeypatch.setattr(web_render, "_evaluate_json", _eval)

    result = render_page(
        "https://spa.example/", NetworkPolicy(mode=NetworkMode.ONLINE), wait_for=".item"
    )

    assert result["wait_for_satisfied"] is True


def test_render_page_reports_wait_for_miss(fake_time, monkeypatch):
    page_json = json.dumps({"url": "https://spa.example/", "title": "t", "text": "x"})
    _install_render(monkeypatch, page_json, lengths=[0, 0, 0])  # querySelector 得 0 → 未命中

    result = render_page(
        "https://spa.example/", NetworkPolicy(mode=NetworkMode.ONLINE), wait_for=".item"
    )

    assert result["wait_for_satisfied"] is False
