"""browser_frames 单测：帧树展平 / CDP 调用形状 / 隔离世界执行 / 全帧就绪等待。"""

from __future__ import annotations

import json

import pytest

from backend.tools import browser_frames


def _tree(url: str = "https://kns.test/result.aspx") -> dict:
    return {
        "frameTree": {
            "frame": {"id": "main", "url": url, "name": "", "parentId": None},
            "childFrames": [
                {
                    "frame": {
                        "id": "f-result",
                        "url": "https://kns.test/brief.aspx?pagename=ASP.brief_result_aspx",
                        "name": "iframeResult",
                        "parentId": "main",
                    }
                },
                {
                    "frame": {
                        "id": "f-nested",
                        "url": "about:blank",
                        "name": "",
                        "parentId": "f-result",
                    },
                },
            ],
        }
    }


def test_flatten_frame_tree_marks_main_and_children():
    frames = browser_frames.flatten_frame_tree(_tree())

    assert [frame.frame_id for frame in frames] == ["main", "f-result", "f-nested"]
    assert frames[0].is_main is True
    assert frames[1].is_main is False
    assert frames[1].name == "iframeResult"
    assert frames[2].parent_id == "f-result"


def test_list_frames_issues_page_enable_and_get_frame_tree(monkeypatch):
    calls = []

    def fake_cdp(session, method, params=None, target_id=None):
        calls.append(method)
        if method == "Page.getFrameTree":
            return _tree()
        return {}

    monkeypatch.setattr(browser_frames, "cdp_command", fake_cdp)

    frames = browser_frames.list_frames(object())

    assert [call for call in calls if call.startswith("Page.")] == [
        "Page.enable",
        "Page.getFrameTree",
    ]
    assert len(frames) == 3


def test_list_frames_raises_on_cdp_failure(monkeypatch):
    from backend.tools.browser_cdp import BrowserCDPError

    def boom(*args, **kwargs):
        raise BrowserCDPError("no frame tree")

    monkeypatch.setattr(browser_frames, "cdp_command", boom)

    with pytest.raises(BrowserCDPError):
        browser_frames.list_frames(object())


def test_create_world_rejects_missing_context(monkeypatch):
    monkeypatch.setattr(
        browser_frames, "cdp_command", lambda *a, **k: {"executionContextId": 0}
    )

    with pytest.raises(browser_frames.BrowserCDPError):
        browser_frames.create_world(object(), "f-result")


def test_create_world_passes_frame_id_and_world_name(monkeypatch):
    captured = {}

    def fake_cdp(session, method, params=None, target_id=None):
        captured.update(params or {})
        return {"executionContextId": 42}

    monkeypatch.setattr(browser_frames, "cdp_command", fake_cdp)

    context_id = browser_frames.create_world(object(), "f-result")

    assert context_id == 42
    assert captured == {
        "frameId": "f-result",
        "worldName": browser_frames.ISOLATED_WORLD_NAME,
    }


def test_evaluate_in_context_passes_context_id(monkeypatch):
    captured = {}

    def fake_cdp(session, method, params=None, target_id=None):
        captured.update(params or {})
        return {"result": {"value": "ok"}}

    monkeypatch.setattr(browser_frames, "cdp_command", fake_cdp)

    assert browser_frames.evaluate_in_context(object(), "1+1", 7) == "ok"
    assert captured["contextId"] == 7
    assert captured["returnByValue"] is True


def test_evaluate_in_context_surfaces_page_errors(monkeypatch):
    monkeypatch.setattr(
        browser_frames,
        "cdp_command",
        lambda *a, **k: {"exceptionDetails": {"text": "boom"}},
    )

    with pytest.raises(browser_frames.BrowserCDPError):
        browser_frames.evaluate_in_context(object(), "throw 1", 7)


def test_wait_frames_settled_true_when_ready_and_stable(monkeypatch):
    monkeypatch.setattr(browser_frames, "SETTLE_POLL_SECONDS", 0)
    monkeypatch.setattr(
        browser_frames,
        "probe_frame",
        lambda session, frame, target_id=None, context_id=None: {
            "ready": "complete",
            "text_len": 10,
        },
    )

    frames = [browser_frames.FrameInfo("main", "", "u", "", True)]
    assert browser_frames.wait_frames_settled(object(), frames=frames, timeout=1.0) is True


def test_wait_frames_settled_false_on_timeout(monkeypatch):
    clock = {"now": 0.0}

    class _FakeTime:
        @staticmethod
        def monotonic():
            return clock["now"]

        @staticmethod
        def sleep(seconds):
            clock["now"] += seconds

    monkeypatch.setattr(browser_frames, "time", _FakeTime)
    monkeypatch.setattr(browser_frames, "SETTLE_POLL_SECONDS", 0.5)
    monkeypatch.setattr(
        browser_frames,
        "probe_frame",
        lambda session, frame, target_id=None, context_id=None: {
            "ready": "loading",
            "text_len": 0,
        },
    )

    frames = [browser_frames.FrameInfo("main", "", "u", "", True)]
    assert browser_frames.wait_frames_settled(object(), frames=frames, timeout=1.0) is False


def test_all_frames_settled_requires_all_ready():
    probes = [
        {"frame_id": "main", "ready": "complete", "text_len": 5},
        {"frame_id": "child", "ready": "loading", "text_len": 3},
    ]

    assert browser_frames.all_frames_settled(probes) is False
    probes[1]["ready"] = "complete"
    assert browser_frames.all_frames_settled(probes) is True


def test_build_probe_expression_returns_ready_state_and_text_length():
    expression = browser_frames.build_probe_expression()
    assert "readyState" in expression
    assert "innerText" in expression
    assert isinstance(expression, str)
