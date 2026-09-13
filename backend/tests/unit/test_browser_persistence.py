# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""浏览器持久 profile + 下载黑洞修复单元测试（方案 2026-09-13 批次 3）。

覆盖：持久 profile 终止保留 / 临时目录照删、profile 目录解析、
browser_launch 的 setDownloadBehavior 接线、cdp_command 浏览器级方法
免 attach 路由、渲染池持久 profile 配置。
"""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from backend.domain.tool_policy import ToolPolicy
from backend.tools import browser_cdp, browser_tool, web_render
from backend.tools.browser_cdp import BrowserSession, BrowserSessionManager
from backend.tools.browser_tool import BrowserLaunchTool
from backend.tools.web_render import RENDER_POOL_ID, RENDER_PROFILE_NAME

pytestmark = [pytest.mark.unit]


def _fake_process():
    return SimpleNamespace(
        poll=lambda: None, terminate=lambda: None, kill=lambda: None, wait=lambda timeout=None: None
    )


def _session(tmp_path: Path, persistent: bool) -> BrowserSession:
    return BrowserSession(
        browser_id="b1",
        executable="fake-browser",
        headless=True,
        user_data_dir=str(tmp_path / ("persist" if persistent else "temp")),
        process=_fake_process(),
        port=1,
        ws_path="/devtools/browser/x",
        persistent=persistent,
    )


# ---------- _terminate_session：持久保留 / 临时照删 ----------


class TestTerminateSession:
    def test_persistent_profile_dir_kept(self, tmp_path):
        profile_dir = tmp_path / "persist"
        profile_dir.mkdir()
        (profile_dir / "Cookies").write_bytes(b"login-state")
        browser_cdp._terminate_session(_session(tmp_path, persistent=True))
        assert (profile_dir / "Cookies").read_bytes() == b"login-state"

    def test_temp_profile_dir_removed(self, tmp_path):
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        (temp_dir / "Preferences").write_bytes(b"junk")
        browser_cdp._terminate_session(_session(tmp_path, persistent=False))
        assert not temp_dir.exists()


# ---------- 目录解析 ----------


class TestProfileRoots:
    def test_profiles_root_follows_sage_db_path(self, tmp_path, monkeypatch):
        db_path = tmp_path / "appdata" / "sage.db"
        monkeypatch.setenv("SAGE_DB_PATH", str(db_path))
        root = browser_cdp._profiles_root()
        assert root == tmp_path / "appdata" / "browser-profiles"
        assert root.is_dir()

    def test_downloads_root_follows_sage_db_path(self, tmp_path, monkeypatch):
        db_path = tmp_path / "appdata" / "sage.db"
        monkeypatch.setenv("SAGE_DB_PATH", str(db_path))
        root = browser_cdp.browser_downloads_root()
        assert root == tmp_path / "appdata" / "browser-downloads"
        assert root.is_dir()


# ---------- browser_launch 接线 ----------


class TestLaunchToolPersistence:
    def test_launch_persistent_wires_download_behavior(self, tmp_path, monkeypatch):
        captured: Dict[str, Any] = {}

        def _fake_launch(headless, browser_id=None, persistent=False, profile_name="default"):
            captured["persistent"] = persistent
            captured["profile_name"] = profile_name
            session = _session(tmp_path, persistent)
            session.browser_id = "b9"
            return session

        calls: List[Dict[str, Any]] = []

        def _fake_cdp(session_, method, params=None, target_id=None):
            calls.append({"method": method, "params": params or {}})
            return {}

        monkeypatch.setattr(browser_tool, "launch_browser", _fake_launch)
        monkeypatch.setattr(browser_tool, "cdp_command", _fake_cdp)
        tool = BrowserLaunchTool(policy=ToolPolicy(workspace_root=str(tmp_path)))
        result = tool.execute(headless=False, persistent=True, profile_name="工作")

        assert result.success is True
        assert captured == {"persistent": True, "profile_name": "工作"}
        assert result.content["persistent"] is True
        assert result.content["profile_dir"] == str(tmp_path / "persist")
        # 下载重定向到工作区 downloads/
        download_call = next(
            c for c in calls if c["method"] == "Browser.setDownloadBehavior"
        )
        assert download_call["params"]["behavior"] == "allow"
        assert download_call["params"]["downloadPath"] == str(tmp_path / "downloads")

    def test_launch_unbound_workspace_uses_data_downloads(self, tmp_path, monkeypatch):
        db_path = tmp_path / "appdata" / "sage.db"
        monkeypatch.setenv("SAGE_DB_PATH", str(db_path))

        def _fake_launch(headless, browser_id=None, persistent=False, profile_name="default"):
            return _session(tmp_path, persistent)

        calls: List[Dict[str, Any]] = []

        def _fake_cdp(session_, method, params=None, target_id=None):
            calls.append({"method": method, "params": params or {}})
            return {}

        monkeypatch.setattr(browser_tool, "launch_browser", _fake_launch)
        monkeypatch.setattr(browser_tool, "cdp_command", _fake_cdp)
        tool = BrowserLaunchTool(policy=ToolPolicy(workspace_root=None))
        result = tool.execute()

        assert result.success is True
        expected = str(tmp_path / "appdata" / "browser-downloads")
        download_call = next(
            c for c in calls if c["method"] == "Browser.setDownloadBehavior"
        )
        assert download_call["params"]["downloadPath"] == expected
        assert result.content["download_dir"] == expected

    def test_launch_survives_download_behavior_failure(self, tmp_path, monkeypatch):
        def _fake_launch(headless, browser_id=None, persistent=False, profile_name="default"):
            return _session(tmp_path, persistent)

        def _fake_cdp(session_, method, params=None, target_id=None):
            raise browser_cdp.BrowserCDPError("cdp down")

        monkeypatch.setattr(browser_tool, "launch_browser", _fake_launch)
        monkeypatch.setattr(browser_tool, "cdp_command", _fake_cdp)
        tool = BrowserLaunchTool(policy=ToolPolicy(workspace_root=str(tmp_path)))
        result = tool.execute()

        assert result.success is True  # 下载配置失败不影响启动


# ---------- cdp_command 浏览器级路由 ----------


class TestCdpCommandRouting:
    def _install_fake_connection(self, monkeypatch):
        sent: List[Dict[str, Any]] = []

        class _FakeConnection:
            def __init__(self, session):
                pass

            def command(self, method, params=None, session_id=None):
                sent.append({"method": method, "params": params or {}, "sid": session_id})
                if method == "Target.attachToTarget":
                    return {"sessionId": "page-s1"}
                if method == "Target.getTargets":
                    return {"targetInfos": [{"targetId": "t1", "type": "page"}]}
                return {}

            def close(self):
                pass

        monkeypatch.setattr(browser_cdp, "_CDPConnection", _FakeConnection)
        return sent

    def test_browser_level_method_skips_attach(self, monkeypatch):
        sent = self._install_fake_connection(monkeypatch)
        session = _session(Path(), persistent=False)
        session.browser_id = "b1"
        manager = BrowserSessionManager()
        manager.register(session)
        monkeypatch.setattr(browser_cdp, "_manager", manager)

        browser_cdp.cdp_command(session, "Browser.setDownloadBehavior", {"behavior": "allow"})
        browser_cdp.cdp_command(session, "Target.getTargets", {})
        browser_cdp.cdp_command(session, "Runtime.evaluate", {"expression": "1"})

        methods = [item["method"] for item in sent]
        assert methods[0] == "Browser.setDownloadBehavior"  # 浏览器级直接发
        assert all(item["sid"] is None for item in sent[:2])
        assert "Target.attachToTarget" in methods[2:]  # 页面级仍走 attach
        evaluate = next(item for item in sent if item["method"] == "Runtime.evaluate")
        assert evaluate["sid"] == "page-s1"


# ---------- 渲染池持久 profile ----------


class TestRenderPoolPersistence:
    def setup_method(self):
        web_render.get_renderer_pool().reset()

    def teardown_method(self):
        web_render.get_renderer_pool().reset()

    def test_acquire_persistent_when_configured(self, monkeypatch):
        launched: Dict[str, Any] = {}

        def _fake_launch(headless, browser_id=None, persistent=False, profile_name="default"):
            launched.update(
                {"headless": headless, "browser_id": browser_id, "persistent": persistent, "profile_name": profile_name}
            )
            return SimpleNamespace(browser_id=RENDER_POOL_ID, is_alive=lambda: True)

        monkeypatch.setattr(web_render, "launch_browser", _fake_launch)
        monkeypatch.setattr(web_render, "_render_persistent_enabled", lambda: True)

        session = web_render.get_renderer_pool().acquire()
        assert session.browser_id == RENDER_POOL_ID
        assert launched["persistent"] is True
        assert launched["profile_name"] == RENDER_PROFILE_NAME
        assert launched["browser_id"] == RENDER_POOL_ID
        assert launched["headless"] is True

    def test_acquire_temp_when_not_configured(self, monkeypatch):
        launched: Dict[str, Any] = {}

        def _fake_launch(headless, browser_id=None, persistent=False, profile_name="default"):
            launched["persistent"] = persistent
            return SimpleNamespace(browser_id=RENDER_POOL_ID, is_alive=lambda: True)

        monkeypatch.setattr(web_render, "launch_browser", _fake_launch)
        monkeypatch.setattr(web_render, "_render_persistent_enabled", lambda: False)

        web_render.get_renderer_pool().acquire()
        assert launched["persistent"] is False


# ---------- _render_persistent_enabled 配置读取 ----------


class TestRenderPersistentConfig:
    def _patch_repo(self, monkeypatch, raw):
        class _Repo:
            def get(self, key):
                assert key == web_render.SETTINGS_KEY_WEB_ACCESS_CONFIG
                return raw

        monkeypatch.setattr(
            "backend.data.settings_repo.SettingsRepository", lambda: _Repo()
        )

    def test_enabled(self, monkeypatch):
        self._patch_repo(monkeypatch, json.dumps({"render_persistent": True}))
        assert web_render._render_persistent_enabled() is True

    def test_missing_key_disabled(self, monkeypatch):
        self._patch_repo(monkeypatch, None)
        assert web_render._render_persistent_enabled() is False

    def test_invalid_json_disabled(self, monkeypatch):
        self._patch_repo(monkeypatch, "{broken")
        assert web_render._render_persistent_enabled() is False

    def test_read_error_disabled(self, monkeypatch):
        class _Broken:
            def get(self, key):
                raise RuntimeError("db gone")

        monkeypatch.setattr(
            "backend.data.settings_repo.SettingsRepository", lambda: _Broken()
        )
        assert web_render._render_persistent_enabled() is False
