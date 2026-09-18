"""Unit tests for browser_launcher module."""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.tools.browser_launcher import (
    BrowserCapability,
    BrowserLauncher,
    BrowserType,
    ChromeLauncher,
    FirefoxLauncher,
    _infer_browser_type,
    discover_and_select,
)


def test_infer_browser_type():
    assert _infer_browser_type("/usr/bin/google-chrome") == BrowserType.CHROME
    assert _infer_browser_type(r"C:\Program Files\Google\Chrome\Application\chrome.exe") == BrowserType.CHROME
    assert _infer_browser_type("/usr/bin/chromium-browser") == BrowserType.CHROMIUM
    assert _infer_browser_type("msedge.exe") == BrowserType.EDGE
    assert _infer_browser_type("/usr/bin/firefox") == BrowserType.FIREFOX
    assert _infer_browser_type("/usr/local/bin/unknown-browser") == BrowserType.UNKNOWN


def test_chrome_launcher_build_command():
    launcher = ChromeLauncher()
    cmd = launcher.build_command(
        executable="/usr/bin/chrome",
        headless=True,
        user_data_dir="/tmp/test_dir",
        proxy_flag="http://127.0.0.1:7890",
    )
    assert cmd[0] == "/usr/bin/chrome"
    assert "--headless=new" in cmd
    assert "--remote-debugging-port=0" in cmd
    assert "--user-data-dir=/tmp/test_dir" in cmd
    assert "--proxy-server=http://127.0.0.1:7890" in cmd
    assert cmd[-1] == "about:blank"

    # Headless = False
    cmd_headful = launcher.build_command(
        executable="/usr/bin/chrome",
        headless=False,
        user_data_dir="/tmp/test_dir",
    )
    assert "--headless=new" not in cmd_headful


def test_firefox_launcher_build_command():
    launcher = FirefoxLauncher(port=9229)
    cmd = launcher.build_command(
        executable="/usr/bin/firefox",
        headless=True,
        user_data_dir="/tmp/ff_profile",
    )
    assert cmd[0] == "/usr/bin/firefox"
    assert "-headless" in cmd
    assert "-start-debugger-server" in cmd
    assert "9229" in cmd
    assert "-profile" in cmd
    assert "/tmp/ff_profile" in cmd
    assert cmd[-1] == "about:blank"


def test_chrome_launcher_wait_for_cdp_success(tmp_path):
    launcher = ChromeLauncher()
    port_file = tmp_path / "DevToolsActivePort"
    port_file.write_text("12345\n/devtools/browser/abc-123\n", encoding="ascii")

    proc = MagicMock(spec=subprocess.Popen)
    proc.poll.return_value = None

    port, ws_path = launcher.wait_for_cdp(proc, str(tmp_path), timeout=2.0)
    assert port == 12345
    assert ws_path == "/devtools/browser/abc-123"


def test_chrome_launcher_wait_for_cdp_proc_exited(tmp_path):
    launcher = ChromeLauncher()
    proc = MagicMock(spec=subprocess.Popen)
    proc.poll.return_value = 1
    proc.returncode = 1

    with pytest.raises(RuntimeError, match="提前退出"):
        launcher.wait_for_cdp(proc, str(tmp_path), timeout=1.0)


def test_firefox_launcher_wait_for_cdp_success(tmp_path):
    launcher = FirefoxLauncher(port=9229)
    proc = MagicMock(spec=subprocess.Popen)
    proc.poll.return_value = None

    fake_json = json.dumps({"webSocketDebuggerUrl": "ws://127.0.0.1:9229/devtools/browser/ff-uuid"}).encode("utf-8")
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = fake_json
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.urlopen", return_value=mock_response):
        port, ws_path = launcher.wait_for_cdp(proc, str(tmp_path), timeout=2.0)
        assert port == 9229
        assert ws_path == "/devtools/browser/ff-uuid"


def test_firefox_launcher_wait_for_cdp_proc_exited(tmp_path):
    launcher = FirefoxLauncher(port=9229)
    proc = MagicMock(spec=subprocess.Popen)
    proc.poll.return_value = 2
    proc.returncode = 2

    with pytest.raises(RuntimeError, match="提前退出"):
        launcher.wait_for_cdp(proc, str(tmp_path), timeout=1.0)


def test_discover_and_select_sage_browser_path_env(monkeypatch, tmp_path):
    fake_exe = tmp_path / "custom_browser"
    fake_exe.write_text("binary")
    monkeypatch.setenv("SAGE_BROWSER_PATH", str(fake_exe))

    cap = discover_and_select()
    assert cap is not None
    assert cap.executable == str(fake_exe)
    assert cap.browser_type == BrowserType.UNKNOWN


def test_discover_and_select_sage_firefox_path_env(monkeypatch, tmp_path):
    fake_ff = tmp_path / "firefox.exe"
    fake_ff.write_text("binary")
    monkeypatch.setenv("SAGE_FIREFOX_PATH", str(fake_ff))
    monkeypatch.delenv("SAGE_BROWSER_PATH", raising=False)

    cap = discover_and_select()
    assert cap is not None
    assert cap.executable == str(fake_ff)
    assert cap.browser_type == BrowserType.FIREFOX
    assert cap.cdp_port == 9229


def test_discover_and_select_fallback_to_firefox_when_no_chrome(monkeypatch):
    monkeypatch.delenv("SAGE_BROWSER_PATH", raising=False)
    monkeypatch.delenv("SAGE_FIREFOX_PATH", raising=False)

    def fake_which(name: str):
        if name == "firefox":
            return "/usr/bin/firefox"
        return None

    monkeypatch.setattr("shutil.which", fake_which)
    monkeypatch.setattr("os.name", "posix")
    monkeypatch.setattr("platform.system", lambda: "Linux")

    cap = discover_and_select()
    assert cap is not None
    assert cap.browser_type == BrowserType.FIREFOX
    assert cap.executable == "/usr/bin/firefox"
    assert isinstance(cap.launcher, FirefoxLauncher)


def test_discover_and_select_prefers_chrome_over_firefox(monkeypatch):
    monkeypatch.delenv("SAGE_BROWSER_PATH", raising=False)
    monkeypatch.delenv("SAGE_FIREFOX_PATH", raising=False)

    def fake_which(name: str):
        if name in ("google-chrome", "firefox"):
            return f"/usr/bin/{name}"
        return None

    monkeypatch.setattr("shutil.which", fake_which)
    monkeypatch.setattr("os.name", "posix")
    monkeypatch.setattr("platform.system", lambda: "Linux")

    cap = discover_and_select()
    assert cap is not None
    assert cap.browser_type == BrowserType.CHROME
    assert cap.executable == "/usr/bin/google-chrome"
    assert isinstance(cap.launcher, ChromeLauncher)
