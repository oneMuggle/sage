import pytest

from backend.services.arena_adapter import ArenaAdapter, ThinkingFilter


class FakeBrowserSession:
    """Records every cdp_command call for assertion."""

    def __init__(self):
        self.calls: list = []
        self.responses: dict = {}

    def cdp_command(self, method, params=None, **_):
        self.calls.append({"method": method, "params": params})
        return self.responses.get(method, {})


def test_thinking_filter_strip_removes_thinking_blocks():
    text = "Hello <thinking>internal reasoning here</thinking> world"
    assert ThinkingFilter.STRIP.value == "strip"
    result = ArenaAdapter.apply_thinking_filter(text, ThinkingFilter.STRIP)
    assert "<thinking>" not in result
    assert "internal reasoning here" not in result
    assert "Hello" in result and "world" in result


def test_thinking_filter_keep_passes_verbatim():
    text = "Hello <thinking>x</thinking> world"
    assert ArenaAdapter.apply_thinking_filter(text, ThinkingFilter.KEEP) == text


def test_thinking_filter_summarize_replaces_with_token_estimate():
    text = "Hello <thinking>some internal reasoning that is fairly long</thinking> world"
    result = ArenaAdapter.apply_thinking_filter(text, ThinkingFilter.SUMMARIZE)
    assert "<thinking>" not in result
    assert "[thinking:" in result
    assert "Hello" in result and "world" in result


def test_adapter_check_login_state_returns_true_when_avatar_present():
    bs = FakeBrowserSession()
    bs.responses["Runtime.evaluate"] = {"result": {"value": True}}
    adapter = ArenaAdapter(bs)
    assert adapter.check_login_state() is True


def test_adapter_detect_captcha_returns_true_when_iframe_present():
    bs = FakeBrowserSession()
    bs.responses["Runtime.evaluate"] = {"result": {"value": True}}
    adapter = ArenaAdapter(bs)
    assert adapter.detect_captcha() is True


def test_adapter_fill_login_sends_key_dispatch_events():
    bs = FakeBrowserSession()
    bs.responses["Runtime.evaluate"] = {"result": {"value": True}}
    adapter = ArenaAdapter(bs)
    adapter.fill_login("user@example.com", "secret123")
    # Should have called Input.dispatchKeyEvent for each character
    key_events = [c for c in bs.calls if c["method"] == "Input.dispatchKeyEvent"]
    # "user@example.com" = 16 chars; "secret123" = 9 chars
    assert len(key_events) >= 16
    # Verify text was split into per-character dispatches
    typed_chars = [k["params"].get("text", "") for k in key_events if k["params"].get("type") == "char"]
    assert "u" in typed_chars and "s" in typed_chars


def test_eval_js_raises_on_cdp_command_error():
    from backend.services.arena_adapter import ArenaAdapter, CDPCommandError

    class FailingSession(FakeBrowserSession):
        def cdp_command(self, method, params=None, **_):
            self.calls.append({"method": method, "params": params})
            raise RuntimeError("CDP socket closed")

    bs = FailingSession()
    adapter = ArenaAdapter(bs)
    with pytest.raises(CDPCommandError) as excinfo:
        adapter._eval_js("document.title")
    assert "CDP socket closed" in str(excinfo.value)


def test_eval_js_raises_on_empty_result():
    from backend.services.arena_adapter import ArenaAdapter, CDPCommandError

    bs = FakeBrowserSession()
    bs.responses["Runtime.evaluate"] = {"result": {}}  # missing 'value'
    adapter = ArenaAdapter(bs)
    with pytest.raises(CDPCommandError):
        adapter._eval_js("document.title")


def test_focus_selector_raises_when_element_missing():
    from backend.services.arena_adapter import (
        ArenaAdapter, SelectorNotFoundError,
    )

    bs = FakeBrowserSession()
    bs.responses["Runtime.evaluate"] = {"result": {"value": None}}
    adapter = ArenaAdapter(bs)
    with pytest.raises(SelectorNotFoundError):
        adapter._focus_selector("input#email")


def test_click_selector_raises_when_element_missing():
    from backend.services.arena_adapter import (
        ArenaAdapter, SelectorNotFoundError,
    )

    bs = FakeBrowserSession()
    bs.responses["Runtime.evaluate"] = {"result": {"value": None}}
    adapter = ArenaAdapter(bs)
    with pytest.raises(SelectorNotFoundError):
        adapter._click_selector("button.submit")


def test_check_login_state_raises_when_cdp_fails():
    from backend.services.arena_adapter import ArenaAdapter, CDPCommandError

    class FailingSession(FakeBrowserSession):
        def cdp_command(self, method, params=None, **_):
            raise RuntimeError("connection lost")

    bs = FailingSession()
    adapter = ArenaAdapter(bs)
    with pytest.raises(CDPCommandError):
        adapter.check_login_state()
