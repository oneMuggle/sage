"""浏览器发现优先级与版本探测（main 分支版）。

Win7 老浏览器修复的 main 侧回归：设置页选择必须优先于内置兜底内核，
Windows 版本探测不得执行 exe，旧内核无头开关降级。
"""

from __future__ import annotations

import pytest

import backend.tools.browser_cdp as cdp

pytestmark = pytest.mark.unit


def _set_embedded_env(monkeypatch) -> None:
    monkeypatch.setenv("SAGE_EMBEDDED_BROWSER", "1")
    monkeypatch.setenv("SAGE_EMBEDDED_BROWSER_PORT", "9411")
    monkeypatch.setenv("SAGE_EMBEDDED_BROWSER_TOKEN", "tok")


def test_user_path_beats_embedded_fallback(monkeypatch, tmp_path):
    fake = tmp_path / "chrome.exe"
    fake.write_text("bin")
    _set_embedded_env(monkeypatch)
    monkeypatch.delenv("SAGE_BROWSER_PATH", raising=False)
    monkeypatch.setattr(cdp, "_get_user_browser_path", lambda: str(fake))

    assert cdp.discover_browser_executable() == str(fake)


def test_embedded_sentinel_selects_builtin_when_available(monkeypatch):
    _set_embedded_env(monkeypatch)
    monkeypatch.delenv("SAGE_BROWSER_PATH", raising=False)
    monkeypatch.setattr(cdp, "_get_user_browser_path", lambda: cdp.EMBEDDED_EXECUTABLE)

    assert cdp.discover_browser_executable() == cdp.EMBEDDED_EXECUTABLE


def test_env_path_beats_user_path(monkeypatch, tmp_path):
    env_exe = tmp_path / "env-chrome"
    env_exe.write_text("bin")
    user_exe = tmp_path / "user-chrome"
    user_exe.write_text("bin")
    monkeypatch.setenv("SAGE_BROWSER_PATH", str(env_exe))
    monkeypatch.delenv("SAGE_EMBEDDED_BROWSER", raising=False)
    monkeypatch.setattr(cdp, "_get_user_browser_path", lambda: str(user_exe))

    assert cdp.discover_browser_executable() == str(env_exe)


def test_chromium_major_version_reads_version_dirs(tmp_path):
    """Windows 无法用 --version 探测：读 exe 同级的版本目录名（Win7 场景同构）。"""
    exe_dir = tmp_path / "Application"
    exe_dir.mkdir()
    (exe_dir / "100.0.4896.60").mkdir()
    (exe_dir / "107.0.5304.87").mkdir()
    exe = exe_dir / "msedge"
    exe.write_text("")

    assert cdp.chromium_major_version(str(exe)) == 107


def test_headless_flag_falls_back_for_legacy_major(tmp_path):
    """Chrome 109 前无 new headless：Edge 100 / Chrome 107 必须降级 --headless。"""
    exe_dir = tmp_path / "Application"
    exe_dir.mkdir()
    (exe_dir / "100.0.4896.60").mkdir()
    exe = exe_dir / "msedge"
    exe.write_text("")

    assert cdp.headless_flag(str(exe)) == "--headless"


def test_headless_flag_uses_new_for_recent_or_unknown(tmp_path):
    exe_dir = tmp_path / "Application"
    exe_dir.mkdir()
    (exe_dir / "138.0.7204.50").mkdir()
    exe = exe_dir / "chrome"
    exe.write_text("")
    assert cdp.headless_flag(str(exe)) == "--headless=new"

    # 版本未知时保持现行默认（不因探测失败改变既有行为）
    assert cdp.headless_flag(str(tmp_path / "missing")) == "--headless=new"
