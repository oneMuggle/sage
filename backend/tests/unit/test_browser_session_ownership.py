# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""浏览器多会话隔离（P0）单元测试。

覆盖：
- ``BrowserSessionManager`` 按聊天会话归属解析（自有实例优先、跨会话拒绝、
  external 共享标签页例外、无归属调用方保持旧语义）
- 工具执行租约：LRU/上限淘汰跳过租用中的实例
- 持久 profile 占用互斥与隐式默认名自动后缀
- Firefox 固定 9229 端口的单实例守卫
- 审计 ``conversation_id`` 归因与下载目录按实例隔离
- 工具层：``browser_close`` 拒绝跨会话实例、自动拉起携带 owner
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from backend.domain.tool_policy import ToolPolicy
from backend.tools import browser_cdp, browser_tool
from backend.tools.browser_cdp import (
    BrowserCDPError,
    BrowserSession,
    BrowserSessionManager,
    BrowserType,
)
from backend.tools.browser_tool import BrowserCloseTool, BrowserNavigateTool
from backend.tools.context import (
    ToolExecutionContext,
    reset_tool_context,
    set_tool_context,
)

pytestmark = [pytest.mark.unit]


def _fake_process() -> SimpleNamespace:
    return SimpleNamespace(
        poll=lambda: None,
        terminate=lambda: None,
        kill=lambda: None,
        wait=lambda timeout=None: None,
    )


def _session(
    browser_id: str,
    tmp_path,
    *,
    owner: str = "",
    browser_type: BrowserType = BrowserType.CHROME,
    last_used_at: str = "",
) -> BrowserSession:
    (tmp_path / browser_id).mkdir(exist_ok=True)
    return BrowserSession(
        browser_id=browser_id,
        executable="fake-browser",
        headless=True,
        user_data_dir=str(tmp_path / browser_id),
        process=_fake_process(),
        port=1,
        ws_path="/devtools/browser/x",
        browser_type=browser_type,
        owner=owner,
        last_used_at=last_used_at,
    )


@pytest.fixture()
def manager(monkeypatch) -> BrowserSessionManager:
    """独立管理器并安装为进程单例；同时清空 profile 占用登记。"""
    fresh = BrowserSessionManager()
    monkeypatch.setattr(browser_cdp, "_manager", fresh)
    monkeypatch.setattr(browser_cdp, "_profile_owners", {})
    monkeypatch.setattr(browser_cdp, "get_max_sessions", lambda: 4)
    monkeypatch.setattr(browser_cdp, "get_lru_evict_enabled", lambda: False)
    return fresh


def _bind(session_id: str):
    ctx = ToolExecutionContext(
        session_id=session_id,
        stream_id="stream-1",
        binding_generation=0,
        office_doc_scope=frozenset(),
    )
    return set_tool_context(ctx)


# ---------------------------------------------------------------------------
# 归属解析
# ---------------------------------------------------------------------------


class TestOwnerResolution:
    def test_owner_resolves_own_instance(self, manager, tmp_path):
        manager.register(_session("a1", tmp_path, owner="conv-a"))
        manager.register(_session("b1", tmp_path, owner="conv-b"))

        assert manager.require(None, owner="conv-a").browser_id == "a1"
        assert manager.require(None, owner="conv-b").browser_id == "b1"

    def test_explicit_id_of_other_owner_rejected(self, manager, tmp_path):
        manager.register(_session("b1", tmp_path, owner="conv-b"))

        with pytest.raises(BrowserCDPError, match="另一个会话"):
            manager.require("b1", owner="conv-a")
        # 原实例不受影响
        assert manager.get("b1") is not None

    def test_owner_without_instance_does_not_borrow_other_sessions(
        self, manager, tmp_path
    ):
        manager.register(_session("b1", tmp_path, owner="conv-b"))

        with pytest.raises(BrowserCDPError, match="没有运行中的浏览器实例"):
            manager.require(None, owner="conv-a")

    def test_owned_instance_preferred_over_external(self, manager, tmp_path):
        manager.register(
            _session("ext", tmp_path, browser_type=BrowserType.EXTERNAL)
        )
        manager.register(_session("a1", tmp_path, owner="conv-a"))

        assert manager.require(None, owner="conv-a").browser_id == "a1"

    def test_external_shared_tab_allowed_when_no_owned_instance(
        self, manager, tmp_path
    ):
        # external 是固定 id 的用户共享标签页（EXTENSION_BROWSER_ID）
        manager.register(
            _session(
                browser_cdp.EXTENSION_BROWSER_ID,
                tmp_path,
                browser_type=BrowserType.EXTERNAL,
            )
        )

        assert manager.require(None, owner="conv-a").browser_id == "external"
        # 显式指定 external 也不受归属限制（用户共享标签页）
        assert manager.require("external", owner="conv-a").browser_id == "external"

    def test_owner_with_multiple_instances_requires_explicit_id(
        self, manager, tmp_path
    ):
        manager.register(_session("a1", tmp_path, owner="conv-a"))
        manager.register(_session("a2", tmp_path, owner="conv-a"))

        with pytest.raises(BrowserCDPError, match="browser_id"):
            manager.require(None, owner="conv-a")

    def test_legacy_owner_empty_keeps_unique_instance_semantics(
        self, manager, tmp_path
    ):
        manager.register(_session("only", tmp_path))
        assert manager.require(None).browser_id == "only"

    def test_status_reports_owner_and_busy(self, manager, tmp_path):
        session = _session("a1", tmp_path, owner="conv-a")
        manager.register(session)
        manager.acquire_lease(session)

        item = manager.get_status()["sessions"][0]
        assert item["owner"] == "conv-a"
        assert item["busy"] is True


# ---------------------------------------------------------------------------
# 租约与淘汰
# ---------------------------------------------------------------------------


class TestLeaseEviction:
    def test_lease_count_balanced(self, manager, tmp_path):
        session = _session("a1", tmp_path, owner="conv-a")
        manager.register(session)
        manager.acquire_lease(session)
        manager.acquire_lease(session)
        assert session.lease_count == 2
        manager.release_lease(session)
        manager.release_lease(session)
        manager.release_lease(session)
        assert session.lease_count == 0

    def test_lru_skips_leased_instance(self, manager, tmp_path, monkeypatch):
        monkeypatch.setattr(browser_cdp, "get_max_sessions", lambda: 2)
        monkeypatch.setattr(browser_cdp, "get_lru_evict_enabled", lambda: True)
        old = _session("old", tmp_path, last_used_at="2020-01-01T00:00:00+00:00")
        newer = _session("newer", tmp_path, last_used_at="2021-01-01T00:00:00+00:00")
        manager.register(old)
        manager.register(newer)
        manager.acquire_lease(old)  # 长任务执行中

        manager.register(_session("latest", tmp_path))

        ids = {s.browser_id for s in manager.all_sessions()}
        assert "old" in ids  # 租用中不淘汰
        assert ids == {"old", "latest"}

    def test_cap_raises_when_all_instances_leased(
        self, manager, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(browser_cdp, "get_max_sessions", lambda: 2)
        monkeypatch.setattr(browser_cdp, "get_lru_evict_enabled", lambda: True)
        first = _session("a1", tmp_path)
        second = _session("a2", tmp_path)
        manager.register(first)
        manager.register(second)
        manager.acquire_lease(first)
        manager.acquire_lease(second)

        with pytest.raises(BrowserCDPError, match="正在执行操作"):
            manager.register(_session("a3", tmp_path))


# ---------------------------------------------------------------------------
# 持久 profile 占用互斥
# ---------------------------------------------------------------------------


class TestProfileClaim:
    def test_explicit_profile_rejects_other_browser(self, manager, tmp_path):
        profile = str(tmp_path / "default")
        assert browser_cdp._claim_profile(profile, "b1") == profile
        # 同 id 幂等
        assert browser_cdp._claim_profile(profile, "b1") == profile
        with pytest.raises(BrowserCDPError, match="正被另一个浏览器会话使用"):
            browser_cdp._claim_profile(profile, "b2")

    def test_implicit_profile_auto_suffix(self, manager, tmp_path):
        base = str(tmp_path / "default")
        assert browser_cdp._claim_profile(base, "b1", allow_suffix=True) == base
        assert (
            browser_cdp._claim_profile(base, "b2", allow_suffix=True) == base + "-2"
        )

    def test_release_allows_reclaim(self, manager, tmp_path):
        profile = str(tmp_path / "default")
        browser_cdp._claim_profile(profile, "b1")
        browser_cdp._release_profile(profile, "b1")
        assert browser_cdp._claim_profile(profile, "b2") == profile

    def test_release_by_non_owner_is_noop(self, manager, tmp_path):
        profile = str(tmp_path / "default")
        browser_cdp._claim_profile(profile, "b1")
        browser_cdp._release_profile(profile, "b2")
        with pytest.raises(BrowserCDPError):
            browser_cdp._claim_profile(profile, "b2")


# ---------------------------------------------------------------------------
# Firefox 单实例守卫
# ---------------------------------------------------------------------------


class TestFirefoxGuard:
    def test_second_firefox_instance_rejected(self, manager, tmp_path):
        manager.register(
            _session("ff1", tmp_path, browser_type=BrowserType.FIREFOX)
        )
        with pytest.raises(BrowserCDPError, match="Firefox"):
            browser_cdp._assert_firefox_single_instance("ff2")

    def test_same_id_allowed(self, manager, tmp_path):
        manager.register(
            _session("ff1", tmp_path, browser_type=BrowserType.FIREFOX)
        )
        browser_cdp._assert_firefox_single_instance("ff1")


# ---------------------------------------------------------------------------
# 审计归因 / 下载目录
# ---------------------------------------------------------------------------


class TestAttribution:
    def test_audit_records_conversation_id(self, monkeypatch, tmp_path):
        captured: List[Dict[str, Any]] = []
        monkeypatch.setattr(
            browser_tool.browser_action_repo,
            "record",
            lambda entry: captured.append(entry),
        )
        token = _bind("conv-a")
        try:
            browser_tool._record_browser_audit(
                _session("a1", tmp_path, owner="conv-a"),
                "browser_navigate",
                "navigate",
                "ok",
            )
        finally:
            reset_tool_context(token)

        assert captured[0]["conversation_id"] == "conv-a"

    def test_audit_without_context_keeps_null(self, monkeypatch, tmp_path):
        captured: List[Dict[str, Any]] = []
        monkeypatch.setattr(
            browser_tool.browser_action_repo,
            "record",
            lambda entry: captured.append(entry),
        )
        browser_tool._record_browser_audit(
            _session("a1", tmp_path), "browser_navigate", "navigate", "ok"
        )
        assert captured[0]["conversation_id"] is None

    def test_download_dir_for_workspace(self, tmp_path):
        session = _session("a1", tmp_path)
        assert browser_tool._download_dir_for(session, str(tmp_path)) == (
            tmp_path / "downloads"
        )

    def test_download_dir_for_unbound_workspace_isolated_per_instance(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("SAGE_DB_PATH", str(tmp_path / "appdata" / "sage.db"))
        session = _session("a1", tmp_path)
        target = browser_tool._download_dir_for(session, None)
        assert target == tmp_path / "appdata" / "browser-downloads" / "a1"


# ---------------------------------------------------------------------------
# 工具层归属拦截 / 自动拉起
# ---------------------------------------------------------------------------


class TestToolOwnership:
    def test_close_rejects_other_sessions_browser(self, manager, tmp_path):
        manager.register(_session("a1", tmp_path, owner="conv-a"))
        token = _bind("conv-b")
        try:
            result = BrowserCloseTool(policy=ToolPolicy()).execute(browser_id="a1")
        finally:
            reset_tool_context(token)

        assert result.success is False
        assert "另一个会话" in (result.error or "")
        assert manager.get("a1") is not None

    def test_auto_launch_carries_owner(self, manager, tmp_path, monkeypatch):
        # 只有 B 会话的实例：A 首次导航必须自动拉起自己的实例
        manager.register(_session("b1", tmp_path, owner="conv-b"))
        launches: List[Dict[str, Any]] = []

        def _fake_launch(**kwargs):
            launches.append(kwargs)
            raise BrowserCDPError("stop-after-capture")

        monkeypatch.setattr(browser_tool, "launch_browser", _fake_launch)
        token = _bind("conv-a")
        try:
            result = BrowserNavigateTool(policy=ToolPolicy()).execute(
                url="https://example.com/"
            )
        finally:
            reset_tool_context(token)

        assert result.success is False
        assert launches
        assert launches[0]["owner"] == "conv-a"

    def test_auto_launch_skipped_when_owner_has_instance(
        self, manager, tmp_path, monkeypatch
    ):
        manager.register(_session("a1", tmp_path, owner="conv-a"))
        calls: List[Dict[str, Any]] = []
        monkeypatch.setattr(
            browser_tool, "launch_browser", lambda **kw: calls.append(kw)
        )
        monkeypatch.setattr(
            browser_tool, "_apply_download_behavior", lambda session, root: tmp_path
        )
        monkeypatch.setattr(browser_tool, "_site_access_gate", lambda *a, **k: None)
        monkeypatch.setattr(browser_tool, "_wait_page_settled", lambda *a, **k: None)
        monkeypatch.setattr(
            browser_tool, "inject_network_monitor", lambda *a, **k: None
        )
        monkeypatch.setattr(browser_tool, "_record_browser_audit", lambda *a, **k: None)
        monkeypatch.setattr(
            browser_tool,
            "cdp_command",
            lambda *a, **k: {"result": {"value": "{}"}},
        )
        token = _bind("conv-a")
        try:
            BrowserNavigateTool(policy=ToolPolicy()).execute(
                url="https://example.com/"
            )
        finally:
            reset_tool_context(token)

        assert calls == []


# ---------------------------------------------------------------------------
# external 共享标签页全局串行（P1）
# ---------------------------------------------------------------------------


class TestExternalSharedTabLock:
    def _external(self, tmp_path, owner: str = "conv-a"):
        return _session(
            "external", tmp_path, owner=owner, browser_type=BrowserType.EXTERNAL
        )

    def test_external_action_lock_busy_raises(self, manager, tmp_path, monkeypatch):
        monkeypatch.setattr(browser_tool, "_EXTERNAL_LOCK_TIMEOUT_SECONDS", 0.05)
        session = self._external(tmp_path)
        assert browser_tool._EXTERNAL_ACTION_LOCK.acquire(blocking=False) is True
        try:
            # 嵌套 with：括号式多上下文语法仅 py3.9+，这里保持 py38 兼容
            with pytest.raises(BrowserCDPError, match="共享标签页"):  # noqa: SIM117
                with browser_tool._browser_lease_scope():
                    browser_tool._lease_session(session)
        finally:
            browser_tool._EXTERNAL_ACTION_LOCK.release()

    def test_external_lock_released_after_scope(self, manager, tmp_path, monkeypatch):
        monkeypatch.setattr(browser_tool, "_EXTERNAL_LOCK_TIMEOUT_SECONDS", 0.05)
        session = self._external(tmp_path)
        with browser_tool._browser_lease_scope():
            browser_tool._lease_session(session)
        # 作用域退出后全局锁已释放
        assert browser_tool._EXTERNAL_ACTION_LOCK.acquire(blocking=False) is True
        browser_tool._EXTERNAL_ACTION_LOCK.release()

    def test_chromium_session_does_not_take_external_lock(self, manager, tmp_path):
        session = _session("chrome-1", tmp_path, owner="conv-a")
        with browser_tool._browser_lease_scope():
            browser_tool._lease_session(session)
            # 普通实例不占用 external 锁
            assert browser_tool._EXTERNAL_ACTION_LOCK.acquire(blocking=False) is True
            browser_tool._EXTERNAL_ACTION_LOCK.release()
