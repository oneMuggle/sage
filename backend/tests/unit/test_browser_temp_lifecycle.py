# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""浏览器一次性目录生命周期单元测试（2026-09-18 %TEMP% 泄漏修复）。

覆盖：一次性目录落数据根而非 %TEMP%、启动清扫按 mtime 判龄、
_remove_dir_with_retry 重试与留痕、require 死会话回收目录、
register 同 id 冲突不静默丢旧实例。
"""

import os
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from backend.tools import browser_cdp
from backend.tools.browser_cdp import (
    EPHEMERAL_PREFIX,
    BrowserCDPError,
    BrowserSession,
    BrowserSessionManager,
    sweep_stale_browser_dirs,
)

pytestmark = [pytest.mark.unit]


def _fake_process(alive: bool = True, pid: int = 4242):
    return SimpleNamespace(
        pid=pid,
        poll=lambda: None if alive else 1,
        terminate=lambda: None,
        kill=lambda: None,
        wait=lambda timeout=None: None,
    )


def _session(tmp_path: Path, browser_id: str = "b1", alive: bool = True) -> BrowserSession:
    return BrowserSession(
        browser_id=browser_id,
        executable="fake-browser",
        headless=True,
        user_data_dir=str(tmp_path),
        process=_fake_process(alive=alive),
        port=1,
        ws_path="/devtools/browser/x",
        persistent=False,
    )


def _make_dir(root: Path, name: str, *, age_seconds: float) -> Path:
    d = root / name
    d.mkdir(parents=True)
    f = d / "lockfile"
    f.write_bytes(b"x")
    stamp = time.time() - age_seconds
    os.utime(f, (stamp, stamp))
    os.utime(d, (stamp, stamp))
    return d


@pytest.fixture()
def data_env(tmp_path, monkeypatch):
    """把 SAGE_DB_PATH 与 gettempdir 都指到 tmp，隔离真实环境。"""
    db_path = tmp_path / "appdata" / "sage.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db_path))
    fake_temp = tmp_path / "win_temp"
    fake_temp.mkdir()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(fake_temp))
    monkeypatch.delenv("SAGE_TEMP_PROFILE_SWEEP", raising=False)
    ephemeral = db_path.parent / "browser-ephemeral"
    ephemeral.mkdir(parents=True)
    return SimpleNamespace(
        ephemeral=ephemeral,
        fake_temp=fake_temp,
    )


# ---------- 启动清扫 ----------


class TestSweep:
    def test_sweeps_old_dirs_in_both_roots_keeps_fresh(self, data_env):
        old_new_root = _make_dir(data_env.ephemeral, EPHEMERAL_PREFIX + "aaa", age_seconds=86400 * 3)
        old_temp = _make_dir(data_env.fake_temp, EPHEMERAL_PREFIX + "bbb", age_seconds=86400 * 2)
        fresh = _make_dir(data_env.ephemeral, EPHEMERAL_PREFIX + "ccc", age_seconds=60)
        unrelated = _make_dir(data_env.fake_temp, "other_app_dir", age_seconds=86400 * 9)

        removed = sweep_stale_browser_dirs()

        assert removed == 2
        assert not old_new_root.exists()
        assert not old_temp.exists()
        assert fresh.is_dir()  # mtime 判龄：活跃实例（持续被写）不误删
        assert unrelated.is_dir()  # 前缀不匹配不动

    def test_long_lived_session_with_old_top_dir_kept(self, data_env):
        """Windows 顶层目录 mtime 不随深层"改写已有文件"刷新——不能按顶层判龄。"""
        d = _make_dir(data_env.ephemeral, EPHEMERAL_PREFIX + "live", age_seconds=86400 * 3)
        deep = d / "Default" / "Site Characteristics Database"
        deep.mkdir(parents=True)
        current = deep / "CURRENT"
        current.write_bytes(b"x")  # 会话刚改写：文件 mtime 为 now
        stamp = time.time() - 86400 * 3
        os.utime(deep, (stamp, stamp))
        os.utime(d, (stamp, stamp))  # 各级目录都显式打旧，模拟长期无新增条目
        assert sweep_stale_browser_dirs() == 0
        assert d.is_dir()

    def test_sweep_disabled_by_env(self, data_env):
        old = _make_dir(data_env.ephemeral, EPHEMERAL_PREFIX + "aaa", age_seconds=86400 * 3)
        os.environ["SAGE_TEMP_PROFILE_SWEEP"] = "0"
        try:
            assert sweep_stale_browser_dirs() == 0
        finally:
            del os.environ["SAGE_TEMP_PROFILE_SWEEP"]
        assert old.is_dir()

    def test_sweep_is_idempotent_and_tolerant(self, data_env, monkeypatch):
        old = _make_dir(data_env.ephemeral, EPHEMERAL_PREFIX + "aaa", age_seconds=86400 * 3)
        real_rmtree = browser_cdp.shutil.rmtree

        def locked_rmtree(path):  # 模拟被占用：抛 OSError 不崩
            raise OSError("winerror 32 locked")

        monkeypatch.setattr(browser_cdp.shutil, "rmtree", locked_rmtree)
        assert sweep_stale_browser_dirs() == 0
        assert old.is_dir()

        monkeypatch.setattr(browser_cdp.shutil, "rmtree", real_rmtree)
        assert sweep_stale_browser_dirs() == 1
        assert not old.exists()


# ---------- _remove_dir_with_retry ----------


class TestRemoveWithRetry:
    def test_retries_then_succeeds(self, tmp_path, monkeypatch):
        target = tmp_path / "victim"
        target.mkdir()
        real_rmtree = browser_cdp.shutil.rmtree  # 先捕获原函数，patch 后模块属性已指向假体
        calls: List[str] = []

        def flaky_rmtree(path):
            calls.append(path)
            if len(calls) < 3:
                raise OSError("locked")
            real_rmtree(path)

        monkeypatch.setattr(browser_cdp.shutil, "rmtree", flaky_rmtree)
        monkeypatch.setattr(browser_cdp.time, "sleep", lambda s: None)
        browser_cdp._remove_dir_with_retry(str(target))
        assert len(calls) == 3

    def test_final_failure_logs_warning_not_raise(self, tmp_path, monkeypatch, caplog):
        calls: List[str] = []

        def always_locked(path):
            calls.append(path)
            raise OSError("locked")

        monkeypatch.setattr(browser_cdp.shutil, "rmtree", always_locked)
        monkeypatch.setattr(browser_cdp.time, "sleep", lambda s: None)
        with caplog.at_level("WARNING", logger="backend.tools.browser_cdp"):
            browser_cdp._remove_dir_with_retry(str(tmp_path / "victim"))
        assert len(calls) == 5  # 默认 5 次尝试
        assert "启动清扫兜底" in caplog.text

    def test_missing_dir_is_noop(self, tmp_path, monkeypatch):
        monkeypatch.setattr(browser_cdp.time, "sleep", lambda s: None)
        browser_cdp._remove_dir_with_retry(str(tmp_path / "never-existed"))  # 不抛不留 warn


# ---------- require / register 生命周期 ----------


class TestManagerLifecycle:
    def test_require_dead_session_removes_dir(self, tmp_path):
        (tmp_path / "DevToolsActivePort").write_text("1\n/devtools/browser/x")
        manager = BrowserSessionManager()
        manager.register(_session(tmp_path, browser_id="u1", alive=True))
        # 进程自行退出（崩溃/用户关窗）后再次访问：不只 pop，还要回收目录
        manager._sessions["u1"].process = _fake_process(alive=False)
        with pytest.raises(BrowserCDPError):
            manager.require("u1")
        assert manager.get("u1") is None
        assert not tmp_path.exists()

    def test_register_same_id_terminates_old(self, tmp_path):
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        new_dir = tmp_path / "new"
        new_dir.mkdir()
        manager = BrowserSessionManager()
        manager.register(_session(old_dir, browser_id="render-pool"))
        # 固定 id 池重建：同 key 注册不得静默丢弃旧对象（连带目录）
        manager.register(_session(new_dir, browser_id="render-pool"))
        assert manager.count() == 1
        assert manager.get("render-pool").user_data_dir == str(new_dir)
        assert not old_dir.exists()
        assert new_dir.exists()

    def test_register_quota_checked_after_conflict_reclaim(self, tmp_path):
        manager = BrowserSessionManager()
        for i in range(browser_cdp.MAX_BROWSER_SESSIONS):
            manager.register(_session(tmp_path / f"d{i}", browser_id=f"b{i}"))
        # 满表下重建同 id 会话：冲突回收释放了额度，应能成功而非报超限
        (tmp_path / "d0").mkdir(exist_ok=True)
        replacement = _session(tmp_path / "d0", browser_id="b0")
        manager.register(replacement)
        assert manager.get("b0") is replacement
        assert manager.count() == browser_cdp.MAX_BROWSER_SESSIONS


# ---------- launch_browser 一次性目录落数据根 ----------


class TestEphemeralDirLocation:
    def test_non_persistent_dir_under_data_root_not_temp(self, data_env, monkeypatch):
        captured: Dict[str, Any] = {}

        def fake_mkdtemp(prefix="", dir=None, **kw):
            captured["prefix"] = prefix
            captured["dir"] = dir
            p = Path(dir) / (prefix + "xyz123")
            p.mkdir(parents=True, exist_ok=True)
            (p / "DevToolsActivePort").write_text("9222\n/devtools/browser/fake\n")
            return str(p)

        class FakePopen:
            pid = 4321

            def __init__(self, command, **kw):
                captured["command"] = command

            def poll(self):
                return None

        monkeypatch.setattr(browser_cdp.tempfile, "mkdtemp", fake_mkdtemp)
        monkeypatch.setattr(browser_cdp.subprocess, "Popen", FakePopen)
        monkeypatch.setattr(browser_cdp, "discover_browser_executable", lambda: "fake-browser.exe")
        if hasattr(browser_cdp, "discover_and_select"):  # win7 线：launcher 抽象
            fake_launcher = SimpleNamespace(
                build_command=lambda exe, headless, udd, proxy: [exe, udd],
                wait_for_cdp=lambda proc, udd, timeout=None: (9222, "/devtools/browser/fake"),
            )
            fake_cap = SimpleNamespace(
                browser_type=browser_cdp.BrowserType.CHROME, launcher=fake_launcher
            )
            monkeypatch.setattr(browser_cdp, "discover_and_select", lambda: fake_cap)
        from backend.tools import http_factory

        monkeypatch.setattr(http_factory, "browser_proxy_flag", lambda: "")
        monkeypatch.setattr(browser_cdp, "_manager", BrowserSessionManager())

        session = browser_cdp.launch_browser(headless=True)

        assert Path(captured["dir"]) == data_env.ephemeral
        assert captured["prefix"] == EPHEMERAL_PREFIX
        # 一次性目录不再落在 %TEMP%（Path.is_relative_to 为 3.9+，用前缀判断保 3.8 兼容）
        assert not str(session.user_data_dir).startswith(str(data_env.fake_temp))
