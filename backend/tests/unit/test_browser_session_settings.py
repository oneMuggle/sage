# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""浏览器会话配置 / LRU 回收 / 命名单元测试（2026-11-20 浏览器多账号优化）。

覆盖：
- ``get_max_sessions`` 读取 / 钳制 / 回退
- ``get_lru_evict_enabled`` 默认关闭 + 读取
- ``BrowserSessionManager.register`` 在 LRU 启用时回收最久未用实例
- ``BrowserSessionManager`` 命名 / ``get_status`` 形状 / 渲染池槽位过滤
"""

from types import SimpleNamespace

import pytest

from backend.tools import browser_cdp
from backend.tools.browser_cdp import (
    BrowserCDPError,
    BrowserSession,
    BrowserSessionManager,
    BrowserType,
)

pytestmark = [pytest.mark.unit]


def _fake_process():
    return SimpleNamespace(
        poll=lambda: None,
        terminate=lambda: None,
        kill=lambda: None,
        wait=lambda timeout=None: None,
    )


def _patch_settings(monkeypatch, config):
    class _FakeRepo:
        def get(self, key):
            if key == "browser_config":
                return config
            return None

    monkeypatch.setattr("backend.data.settings_repo.SettingsRepository", _FakeRepo)


def _session(
    browser_id,
    tmp_path,
    *,
    name="",
    last_used_at="",
    browser_type=BrowserType.CHROME,
):
    (tmp_path / browser_id).mkdir(exist_ok=True)
    return BrowserSession(
        browser_id=browser_id,
        executable="fake-browser",
        headless=True,
        user_data_dir=str(tmp_path / browser_id),
        process=_fake_process(),
        port=1,
        ws_path="/devtools/browser/x",
        name=name,
        last_used_at=last_used_at,
        browser_type=browser_type,
    )


# ---------- get_max_sessions ----------


class TestGetMaxSessions:
    def test_default_when_unset(self, monkeypatch):
        _patch_settings(monkeypatch, None)
        assert browser_cdp.get_max_sessions() == 4

    def test_reads_configured(self, monkeypatch):
        _patch_settings(monkeypatch, '{"maxSessions": 6}')
        assert browser_cdp.get_max_sessions() == 6

    def test_clamps_high(self, monkeypatch):
        _patch_settings(monkeypatch, '{"maxSessions": 20}')
        assert browser_cdp.get_max_sessions() == 8

    def test_clamps_low(self, monkeypatch):
        _patch_settings(monkeypatch, '{"maxSessions": 1}')
        assert browser_cdp.get_max_sessions() == 2

    def test_dict_value(self, monkeypatch):
        _patch_settings(monkeypatch, {"maxSessions": 5})
        assert browser_cdp.get_max_sessions() == 5

    def test_fallback_on_malformed_json(self, monkeypatch):
        _patch_settings(monkeypatch, "not-json")
        assert browser_cdp.get_max_sessions() == 4


# ---------- get_lru_evict_enabled ----------


class TestLruFlag:
    def test_default_false(self, monkeypatch):
        _patch_settings(monkeypatch, None)
        assert browser_cdp.get_lru_evict_enabled() is False

    def test_enabled(self, monkeypatch):
        _patch_settings(monkeypatch, '{"lruEvict": true}')
        assert browser_cdp.get_lru_evict_enabled() is True

    def test_malformed_returns_false(self, monkeypatch):
        _patch_settings(monkeypatch, "junk")
        assert browser_cdp.get_lru_evict_enabled() is False


# ---------- register 上限与 LRU ----------


class TestRegisterLimit:
    def test_limit_enforced_with_configured_max(self, tmp_path, monkeypatch):
        monkeypatch.setattr(browser_cdp, "get_max_sessions", lambda: 2)
        monkeypatch.setattr(browser_cdp, "get_lru_evict_enabled", lambda: False)
        manager = BrowserSessionManager()
        manager.register(_session("b1", tmp_path))
        manager.register(_session("b2", tmp_path))
        with pytest.raises(BrowserCDPError):
            manager.register(_session("b3", tmp_path))

    def test_lru_evicts_oldest(self, tmp_path, monkeypatch):
        monkeypatch.setattr(browser_cdp, "get_max_sessions", lambda: 2)
        monkeypatch.setattr(browser_cdp, "get_lru_evict_enabled", lambda: True)
        manager = BrowserSessionManager()
        old = _session("old", tmp_path, last_used_at="2020-01-01T00:00:00+00:00")
        newer = _session("newer", tmp_path, last_used_at="2021-01-01T00:00:00+00:00")
        manager.register(old)
        manager.register(newer)
        manager.register(_session("latest", tmp_path))
        ids = {s.browser_id for s in manager.all_sessions()}
        assert "old" not in ids
        assert ids == {"newer", "latest"}

    def test_lru_skips_embedded(self, tmp_path, monkeypatch):
        monkeypatch.setattr(browser_cdp, "get_max_sessions", lambda: 2)
        monkeypatch.setattr(browser_cdp, "get_lru_evict_enabled", lambda: True)
        manager = BrowserSessionManager()
        manager.register(
            _session("c1", tmp_path, last_used_at="2020-01-01T00:00:00+00:00")
        )
        manager.register(
            _session("c2", tmp_path, last_used_at="2021-01-01T00:00:00+00:00")
        )
        manager.register(
            _session("emb", tmp_path, browser_type=BrowserType.EMBEDDED)
        )
        manager.register(_session("c3", tmp_path))
        ids = {s.browser_id for s in manager.all_sessions()}
        assert "emb" in ids
        assert "c1" not in ids
        assert ids == {"c2", "c3", "emb"}


# ---------- 命名 / 状态 ----------


class TestNamingAndStatus:
    def test_update_name_and_status(self, tmp_path, monkeypatch):
        monkeypatch.setattr(browser_cdp, "get_max_sessions", lambda: 4)
        monkeypatch.setattr(browser_cdp, "get_lru_evict_enabled", lambda: False)
        manager = BrowserSessionManager()
        manager.register(_session("b1", tmp_path))
        assert manager.update_session_name("b1", "账号A") is True
        assert manager.update_session_name("missing", "x") is False
        status = manager.get_status()
        assert status["active"] == 1
        assert status["max"] == 4
        assert status["lruEvict"] is False
        assert status["sessions"][0]["name"] == "账号A"
        assert status["sessions"][0]["id"] == "b1"
        assert "last_used_at" in status["sessions"][0]

    def test_status_excludes_reserved_pool(self, tmp_path, monkeypatch):
        monkeypatch.setattr(browser_cdp, "get_max_sessions", lambda: 6)
        monkeypatch.setattr(browser_cdp, "get_lru_evict_enabled", lambda: False)
        manager = BrowserSessionManager()
        manager.register(_session(browser_cdp.RESERVED_BROWSER_ID, tmp_path))
        manager.register(
            _session(browser_cdp.RESERVED_BROWSER_ID + "-1", tmp_path)
        )
        manager.register(_session("user", tmp_path))
        status = manager.get_status()
        ids = {s["id"] for s in status["sessions"]}
        assert ids == {"user"}
        assert status["active"] == 1

    def test_touch_updates_last_used(self, tmp_path, monkeypatch):
        monkeypatch.setattr(browser_cdp, "get_max_sessions", lambda: 4)
        monkeypatch.setattr(browser_cdp, "get_lru_evict_enabled", lambda: False)
        manager = BrowserSessionManager()
        session = _session("b1", tmp_path, last_used_at="2020-01-01T00:00:00+00:00")
        manager.register(session)
        manager.touch_session("b1")
        assert session.last_used_at != "2020-01-01T00:00:00+00:00"
        assert session.last_used_at.startswith("20")  # ISO timestamp prefix
