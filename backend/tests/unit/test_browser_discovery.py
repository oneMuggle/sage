"""浏览器发现优先级与版本探测（main 分支版）。

Win7 老浏览器修复的 main 侧回归：设置页选择必须优先于内置兜底内核，
Windows 版本探测不得执行 exe，旧内核无头开关降级。另含 Firefox 兜底
（Chromium 全部缺失时的多浏览器支持）的发现与启动命令用例。
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
    monkeypatch.delenv("SAGE_FIREFOX_PATH", raising=False)
    monkeypatch.setattr(cdp, "_get_user_browser_path", lambda: str(fake))

    assert cdp.discover_browser_executable() == str(fake)


def test_embedded_sentinel_selects_builtin_when_available(monkeypatch):
    _set_embedded_env(monkeypatch)
    monkeypatch.delenv("SAGE_BROWSER_PATH", raising=False)
    monkeypatch.delenv("SAGE_FIREFOX_PATH", raising=False)
    monkeypatch.setattr(cdp, "_get_user_browser_path", lambda: cdp.EMBEDDED_EXECUTABLE)

    assert cdp.discover_browser_executable() == cdp.EMBEDDED_EXECUTABLE


def test_env_path_beats_user_path(monkeypatch, tmp_path):
    env_exe = tmp_path / "env-chrome"
    env_exe.write_text("bin")
    user_exe = tmp_path / "user-chrome"
    user_exe.write_text("bin")
    monkeypatch.setenv("SAGE_BROWSER_PATH", str(env_exe))
    monkeypatch.delenv("SAGE_FIREFOX_PATH", raising=False)
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


# ---------------------------------------------------------------------------
# Firefox 兜底（Chromium 全部缺失时的多浏览器支持，对齐 release/win7）
# ---------------------------------------------------------------------------


def test_firefox_env_path_beats_platform_and_embedded(monkeypatch, tmp_path):
    """SAGE_FIREFOX_PATH 是显式选择：胜过内置兜底与平台扫描。"""
    firefox = tmp_path / "firefox"
    firefox.write_text("bin")
    _set_embedded_env(monkeypatch)
    monkeypatch.delenv("SAGE_BROWSER_PATH", raising=False)
    monkeypatch.setenv("SAGE_FIREFOX_PATH", str(firefox))
    monkeypatch.setattr(cdp, "_get_user_browser_path", lambda: None)

    assert cdp.discover_browser_executable() == str(firefox)


def test_browser_path_beats_firefox_path(monkeypatch, tmp_path):
    chrome = tmp_path / "chrome"
    chrome.write_text("bin")
    firefox = tmp_path / "firefox"
    firefox.write_text("bin")
    monkeypatch.setenv("SAGE_BROWSER_PATH", str(chrome))
    monkeypatch.setenv("SAGE_FIREFOX_PATH", str(firefox))
    monkeypatch.delenv("SAGE_EMBEDDED_BROWSER", raising=False)
    monkeypatch.setattr(cdp, "_get_user_browser_path", lambda: None)

    assert cdp.discover_browser_executable() == str(chrome)


def test_missing_firefox_env_path_falls_through_to_user_path(monkeypatch, tmp_path):
    """指向不存在文件的 SAGE_FIREFOX_PATH 视为未设置，不阻断后续优先级。"""
    user_exe = tmp_path / "user-chrome"
    user_exe.write_text("bin")
    monkeypatch.delenv("SAGE_BROWSER_PATH", raising=False)
    monkeypatch.setenv("SAGE_FIREFOX_PATH", str(tmp_path / "missing-firefox"))
    monkeypatch.delenv("SAGE_EMBEDDED_BROWSER", raising=False)
    monkeypatch.setattr(cdp, "_get_user_browser_path", lambda: str(user_exe))

    assert cdp.discover_browser_executable() == str(user_exe)


def test_windows_firefox_candidates_cover_standard_install_dirs(monkeypatch):
    monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
    # 空值才会被候选构造跳过（delenv 会回落到内置默认路径）
    monkeypatch.setenv("ProgramFiles(x86)", "")

    candidates = [str(path) for path in cdp._windows_firefox_candidates()]

    assert len(candidates) == 1
    assert candidates[0].startswith(r"C:\Program Files")
    assert candidates[0].endswith(r"Mozilla Firefox\firefox.exe")


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (r"C:\Program Files\Mozilla Firefox\firefox.exe", cdp.BrowserType.FIREFOX),
        ("/usr/bin/firefox", cdp.BrowserType.FIREFOX),
        ("/usr/bin/google-chrome", cdp.BrowserType.CHROME),
        (r"C:\Program Files\Microsoft\Edge\Application\msedge.exe", cdp.BrowserType.CHROME),
    ],
)
def test_infer_browser_type(path, expected):
    assert cdp._infer_browser_type(path) == expected


def test_firefox_launch_command_uses_debugger_server_and_profile():
    command = cdp._build_launch_command("/usr/bin/firefox", False, "/tmp/profile")

    assert command == [
        "/usr/bin/firefox",
        "-start-debugger-server",
        str(cdp.FIREFOX_CDP_PORT),
        "-profile",
        "/tmp/profile",
        "-no-remote",
        "about:blank",
    ]
    assert cdp.FIREFOX_CDP_PORT == 9229


def test_firefox_launch_command_headless_inserts_flag_and_ignores_proxy():
    command = cdp._build_launch_command(
        "/usr/bin/firefox", True, "/tmp/profile", "http://127.0.0.1:7890"
    )

    assert command[1] == "-headless"
    assert not any(arg.startswith("--proxy-server") for arg in command)
    assert not any(arg.startswith("--remote-debugging-port") for arg in command)


def test_chromium_launch_command_keeps_random_port():
    command = cdp._build_launch_command("/usr/bin/google-chrome", True, "/tmp/profile")

    assert "--remote-debugging-port=0" in command
    assert "-start-debugger-server" not in command
