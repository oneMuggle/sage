"""浏览器诊断单元测试（Phase D5）。"""

from __future__ import annotations

import platform
from unittest.mock import MagicMock, patch

from backend.tools.browser_diagnostics import (
    CheckResult,
    _check_browser_data_dir_writable,
    _check_executable_chrome,
    _check_executable_firefox,
    _check_win7_sp1,
    run_all_checks,
)


def test_check_result_to_dict():
    """CheckResult 正确序列化为 dict。"""
    result = CheckResult(
        id="test_check",
        status="pass",
        detail="all good",
        fix_hint="https://example.com",
    )
    d = result.to_dict()
    assert d == {
        "id": "test_check",
        "status": "pass",
        "detail": "all good",
        "fix_hint": "https://example.com",
    }


def test_check_result_to_dict_no_fix_hint():
    """fix_hint 为 None 时正确序列化。"""
    result = CheckResult(id="test", status="na", detail="skipped")
    d = result.to_dict()
    assert d["fix_hint"] is None


def test_check_executable_chrome_found():
    """发现 Chrome 时返回 pass。"""
    from backend.tools.browser_launcher import BrowserCapability, BrowserType

    mock_cap = BrowserCapability(
        browser_type=BrowserType.CHROME,
        executable="/usr/bin/google-chrome",
        version="120.0",
        cdp_port=0,
        cdp_endpoint_strategy="devtools_active_port",
        launcher=MagicMock(),
    )
    result = _check_executable_chrome(mock_cap)
    assert result.status == "pass"
    assert "google-chrome" in result.detail


def test_check_executable_chrome_not_found():
    """未发现 Chrome 时返回 warn。"""
    result = _check_executable_chrome(None)
    assert result.status == "warn"
    assert result.fix_hint is not None


def test_check_executable_firefox_found():
    """发现 Firefox 时返回 pass。"""
    from backend.tools.browser_launcher import BrowserCapability, BrowserType

    mock_cap = BrowserCapability(
        browser_type=BrowserType.FIREFOX,
        executable="/usr/bin/firefox",
        version="121.0",
        cdp_port=9229,
        cdp_endpoint_strategy="http_json_version",
        launcher=MagicMock(),
    )
    result = _check_executable_firefox(mock_cap)
    assert result.status == "pass"
    assert "firefox" in result.detail


def test_check_win7_sp1_non_windows():
    """非 Windows 平台返回 na。"""
    with patch("backend.tools.browser_diagnostics.platform") as mock_platform:
        mock_platform.system.return_value = "Linux"
        result = _check_win7_sp1()
    assert result.status == "na"
    assert "非 Windows" in result.detail


def test_check_win7_sp1_not_win7():
    """非 Win7（如 Win10）返回 na。"""
    with patch("backend.tools.browser_diagnostics.platform") as mock_platform:
        mock_platform.system.return_value = "Windows"
        mock_platform.version.return_value = "10.0.19041"
        result = _check_win7_sp1()
    assert result.status == "na"
    assert "非 Win7" in result.detail


def test_check_win7_sp1_present():
    """Win7 SP1 已安装时返回 pass。"""
    with patch("backend.tools.browser_diagnostics.platform") as mock_platform:
        mock_platform.system.return_value = "Windows"
        mock_platform.version.return_value = "6.1.7601 Service Pack 1"
        result = _check_win7_sp1()
    assert result.status == "pass"
    assert "SP1 已安装" in result.detail


def test_check_win7_sp1_missing():
    """Win7 无 SP1 时返回 fail。"""
    with patch("backend.tools.browser_diagnostics.platform") as mock_platform:
        mock_platform.system.return_value = "Windows"
        mock_platform.version.return_value = "6.1.7600"
        result = _check_win7_sp1()
    assert result.status == "fail"
    assert result.fix_hint is not None


def test_check_browser_data_dir_writable():
    """临时目录可写时返回 pass。"""
    result = _check_browser_data_dir_writable()
    assert result.status == "pass"


def test_check_browser_data_dir_not_writable():
    """临时目录不可写时返回 fail。"""
    with patch("backend.tools.browser_diagnostics.tempfile.mkdtemp", side_effect=OSError("full")):
        result = _check_browser_data_dir_writable()
    assert result.status == "fail"
    assert "不可写" in result.detail


def test_run_all_checks_structure():
    """run_all_checks 返回正确的顶层结构。"""
    with patch(
        "backend.tools.browser_diagnostics._check_cdp_handshake",
        return_value=CheckResult("cdp_handshake", "pass", "mocked"),
    ):
        result = run_all_checks()
    assert "platform" in result
    assert "checks" in result
    assert "recommended_browser" in result
    assert "errors" in result
    assert isinstance(result["checks"], list)
    assert result["platform"] == platform.system().lower()


def test_run_all_checks_recommended_browser_logic():
    """推荐浏览器逻辑：Chrome 优先于 Firefox。"""
    from backend.tools.browser_launcher import BrowserCapability, BrowserType

    chrome_cap = BrowserCapability(
        browser_type=BrowserType.CHROME,
        executable="/usr/bin/chrome",
        version="120.0",
        cdp_port=0,
        cdp_endpoint_strategy="devtools_active_port",
        launcher=MagicMock(),
    )
    firefox_cap = BrowserCapability(
        browser_type=BrowserType.FIREFOX,
        executable="/usr/bin/firefox",
        version="121.0",
        cdp_port=9229,
        cdp_endpoint_strategy="http_json_version",
        launcher=MagicMock(),
    )

    with patch(
        "backend.tools.browser_diagnostics._check_cdp_handshake",
        return_value=CheckResult("cdp_handshake", "pass", "mocked"),
    ):
        # 发现 Chrome → 推荐 chrome
        with patch(
            "backend.tools.browser_diagnostics.discover_and_select",
            return_value=chrome_cap,
        ):
            result = run_all_checks()
        assert result["recommended_browser"] == "chrome"

        # 发现 Firefox → 推荐 firefox
        with patch(
            "backend.tools.browser_diagnostics.discover_and_select",
            return_value=firefox_cap,
        ):
            result = run_all_checks()
        assert result["recommended_browser"] == "firefox"

        # 未发现 → 推荐 none
        with patch(
            "backend.tools.browser_diagnostics.discover_and_select",
            return_value=None,
        ):
            result = run_all_checks()
        assert result["recommended_browser"] == "none"
