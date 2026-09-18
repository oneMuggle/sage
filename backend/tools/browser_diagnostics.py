"""浏览器环境诊断 API（Phase D）。

提供浏览器环境健康检查，包括：
- 可执行文件发现
- Win7 SP1 + KB4474419 补丁检测
- VC++ 2019 Redistributable 检测
- 浏览器数据目录可写性验证
- CDP 握手测试

API 契约见 docs/plans/2026-09-17_multi-browser-support.md §4。
"""

from __future__ import annotations

import logging
import platform
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .browser_cdp import discover_browser_executable, launch_browser
from .browser_launcher import BrowserType, discover_and_select

logger = logging.getLogger(__name__)


@dataclass
class CheckResult:
    """单项检查结果。"""

    id: str
    status: str  # "pass" | "warn" | "fail" | "na"
    detail: str
    fix_hint: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "detail": self.detail,
            "fix_hint": self.fix_hint,
        }


def _pass(id: str, detail: str) -> CheckResult:
    return CheckResult(id=id, status="pass", detail=detail)


def _warn(id: str, detail: str, fix_hint: Optional[str] = None) -> CheckResult:
    return CheckResult(id=id, status="warn", detail=detail, fix_hint=fix_hint)


def _fail(id: str, detail: str, fix_hint: Optional[str] = None) -> CheckResult:
    return CheckResult(id=id, status="fail", detail=detail, fix_hint=fix_hint)


def _na(id: str, detail: str) -> CheckResult:
    return CheckResult(id=id, status="na", detail=detail)


# ---------------------------------------------------------------------------
# 检查项
# ---------------------------------------------------------------------------


def _check_executable_chrome(cap: Optional[Any] = None) -> CheckResult:
    """检查 Chrome/Edge 可执行文件是否可发现。"""
    if cap is None:
        cap = discover_and_select()
    if cap and cap.browser_type in (BrowserType.CHROME, BrowserType.EDGE):
        return _pass(
            "executable_chrome",
            f"发现 {cap.browser_type.value}: {cap.executable}",
        )
    return _warn(
        "executable_chrome",
        "未发现 Chrome/Edge 浏览器",
        "https://www.google.com/chreme/ 或 https://www.microsoft.com/edge",
    )


def _check_executable_firefox(cap: Optional[Any] = None) -> CheckResult:
    """检查 Firefox 可执行文件是否可发现。"""
    if cap is None:
        cap = discover_and_select()
    if cap and cap.browser_type == BrowserType.FIREFOX:
        return _pass(
            "executable_firefox",
            f"发现 Firefox: {cap.executable}",
        )
    return _warn(
        "executable_firefox",
        "未发现 Firefox 浏览器",
        "https://www.mozilla.org/firefox/enterprise/",
    )


def _check_win7_sp1() -> CheckResult:
    """检查 Windows 7 SP1（仅 Win7 环境）。"""
    if platform.system() != "Windows":
        return _na("win7_sp1", "非 Windows 平台")

    ver = platform.version()
    # Win7 = NT 6.1；SP1 在 version string 中体现为 "Service Pack 1"
    if "6.1" not in ver:
        return _na("win7_sp1", f"非 Win7（version={ver}）")

    if "service pack 1" in ver.lower():
        return _pass("win7_sp1", "SP1 已安装")
    return _fail(
        "win7_sp1",
        "未检测到 SP1",
        "https://www.microsoft.com/download/details.aspx?id=5842",
    )


def _check_win7_kb4474419() -> CheckResult:
    """检查 KB4474419 SHA-2 签名补丁（仅 Win7）。"""
    if platform.system() != "Windows":
        return _na("win7_kb4474419_sha2", "非 Windows 平台")

    ver = platform.version()
    if "6.1" not in ver:
        return _na("win7_kb4474419_sha2", f"非 Win7（version={ver}）")

    # 1. 注册表检测
    try:
        import winreg  # type: ignore[import-not-found]

        key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                try:
                    sub_name = winreg.EnumKey(key, i)
                    with winreg.OpenKey(key, sub_name) as sub:
                        try:
                            display_name, _ = winreg.QueryValueEx(sub, "DisplayName")
                            if "KB4474419" in str(display_name):
                                return _pass("win7_kb4474419_sha2", "KB4474419 已安装（注册表）")
                        except OSError:
                            continue
                except OSError:
                    continue
    except Exception as exc:  # noqa: BLE001
        logger.debug("注册表检测 KB4474419 失败: %s", exc)

    # 2. wmic 回退
    try:
        result = subprocess.run(  # noqa: S603
            ["wmic", "qfe", "list", "brief"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if "KB4474419" in result.stdout:
            return _pass("win7_kb4474419_sha2", "KB4474419 已安装（wmic）")
    except Exception as exc:  # noqa: BLE001
        logger.debug("wmic 检测 KB4474419 失败: %s", exc)

    return _fail(
        "win7_kb4474419_sha2",
        "未检测到 SHA-2 补丁 KB4474419",
        "https://www.catalog.update.microsoft.com/Search.aspx?q=KB4474419",
    )


def _check_vcredist_2019() -> CheckResult:
    """检查 VC++ 2019 Redistributable（仅 Windows）。"""
    if platform.system() != "Windows":
        return _na("vcredist_2019", "非 Windows 平台")

    # 注册表检测
    try:
        import winreg  # type: ignore[import-not-found]

        key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                try:
                    sub_name = winreg.EnumKey(key, i)
                    with winreg.OpenKey(key, sub_name) as sub:
                        try:
                            display_name, _ = winreg.QueryValueEx(sub, "DisplayName")
                            if "Visual C++ 2019" in str(display_name) or "2015-2022" in str(
                                display_name
                            ):
                                return _pass("vcredist_2019", f"已安装: {display_name}")
                        except OSError:
                            continue
                except OSError:
                    continue
    except Exception as exc:  # noqa: BLE001
        logger.debug("注册表检测 VC++ 2019 失败: %s", exc)

    return _fail(
        "vcredist_2019",
        "未检测到 VC++ 2019 Redistributable",
        "https://aka.ms/vs/16/release/vc_redist.x64.exe",
    )


def _check_browser_data_dir_writable() -> CheckResult:
    """检查浏览器数据目录是否可写。"""
    try:
        # 尝试在临时目录创建测试文件
        test_dir = Path(tempfile.mkdtemp(prefix="sage_browser_test_"))
        test_file = test_dir / "write_test.txt"
        test_file.write_text("test", encoding="utf-8")
        test_file.unlink()
        test_dir.rmdir()
        return _pass("browser_data_dir_writable", "临时目录可写")
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "browser_data_dir_writable",
            f"临时目录不可写: {exc}",
            "检查磁盘空间或 TEMP 环境变量权限",
        )


def _check_cdp_handshake() -> CheckResult:
    """测试 CDP 握手（启动浏览器 + DevToolsActivePort 握手）。"""
    executable = discover_browser_executable()
    if not executable:
        return _warn("cdp_handshake", "无可执行文件，跳过握手测试")

    try:
        # 启动浏览器（headless + 临时目录）
        session = launch_browser(headless=True, persistent=False)
        # 关闭
        from .browser_cdp import get_browser_manager

        get_browser_manager().remove(session.browser_id)
        session.process.terminate()
        session.process.wait(timeout=5)
        return _pass("cdp_handshake", f"Chrome DevToolsActivePort 握手成功（{session.port}）")
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "cdp_handshake",
            f"CDP 握手失败: {exc}",
            "检查浏览器版本是否支持 DevTools Protocol",
        )


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def run_all_checks() -> Dict[str, Any]:
    """执行全部检查并返回聚合结果。

    返回格式符合 docs/plans §4 API 契约。
    """
    checks: List[CheckResult] = []
    errors: List[str] = []

    # 共享浏览器发现结果（避免重复扫描）
    try:
        discovered_cap = discover_and_select()
    except Exception as exc:  # noqa: BLE001
        logger.debug("discover_and_select 异常: %s", exc)
        discovered_cap = None

    # 执行各项检查
    check_fns = [
        lambda: _check_executable_chrome(discovered_cap),
        lambda: _check_executable_firefox(discovered_cap),
        _check_win7_sp1,
        _check_win7_kb4474419,
        _check_vcredist_2019,
        _check_browser_data_dir_writable,
        _check_cdp_handshake,
    ]
    for check_fn in check_fns:
        try:
            result = check_fn()
            checks.append(result)
        except Exception as exc:  # noqa: BLE001
            logger.exception("检查项 %s 异常", check_fn.__name__)
            errors.append(f"{check_fn.__name__}: {exc}")

    # 推荐浏览器逻辑
    chrome_ok = any(c.id == "executable_chrome" and c.status == "pass" for c in checks)
    firefox_ok = any(c.id == "executable_firefox" and c.status == "pass" for c in checks)

    if chrome_ok:
        recommended = "chrome"
    elif firefox_ok:
        recommended = "firefox"
    else:
        recommended = "none"

    return {
        "platform": platform.system().lower(),
        "checks": [c.to_dict() for c in checks],
        "recommended_browser": recommended,
        "errors": errors,
    }


__all__ = [
    "CheckResult",
    "run_all_checks",
]
