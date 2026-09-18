"""浏览器抽象层与启动器（支持 Chrome/Edge/Firefox 多浏览器自动调度）。

定义 BrowserType、BrowserCapability 和 BrowserLauncher 抽象基类，
实现 ChromeLauncher 与 FirefoxLauncher，并提供 discover_and_select() 入口。
"""

from __future__ import annotations

import abc
import json
import logging
import os
import platform
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: Firefox 启动监听的默认调试端口
FIREFOX_DEFAULT_CDP_PORT = 9229

#: 启动握手超时（秒）
LAUNCH_TIMEOUT_SECONDS = 30.0

#: Chrome DevToolsActivePort 轮询间隔
CHROME_POLL_INTERVAL = 0.2

#: Firefox HTTP 接口轮询间隔
FIREFOX_POLL_INTERVAL = 0.5


class BrowserType(str, Enum):
    """支持的浏览器类型枚举。"""

    CHROME = "chrome"
    EDGE = "edge"
    CHROMIUM = "chromium"
    FIREFOX = "firefox"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class BrowserCapability:
    """浏览器能力描述。"""

    browser_type: BrowserType
    executable: str
    version: Optional[str]
    cdp_port: int  # 0 为 Chrome 动态随机端口，非 0 为固定端口（如 Firefox 9229）
    cdp_endpoint_strategy: str  # "devtools_active_port" | "http_json_version"
    launcher: BrowserLauncher
    fix_hint: Optional[str] = None


class BrowserLauncher(abc.ABC):
    """浏览器启动器抽象基类。"""

    @abc.abstractmethod
    def build_command(
        self,
        executable: str,
        headless: bool,
        user_data_dir: str,
        proxy_flag: str = "",
    ) -> List[str]:
        """构造浏览器启动命令行参数列表。"""

    @abc.abstractmethod
    def wait_for_cdp(
        self,
        process: subprocess.Popen,
        user_data_dir: str,
        timeout: float = LAUNCH_TIMEOUT_SECONDS,
    ) -> Tuple[int, str]:
        """等待浏览器就绪并返回 (port, ws_path)。"""


class ChromeLauncher(BrowserLauncher):
    """Chromium 系（Chrome/Edge/Chromium）浏览器启动器。"""

    def build_command(
        self,
        executable: str,
        headless: bool,
        user_data_dir: str,
        proxy_flag: str = "",
    ) -> List[str]:
        command = [
            executable,
            "--remote-debugging-port=0",
            f"--user-data-dir={user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-background-networking",
            "--window-size=1440,900",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
        ]
        if proxy_flag:
            command.append(f"--proxy-server={proxy_flag}")
        command.append("about:blank")
        if headless:
            command.insert(1, "--headless=new")
        return command

    def wait_for_cdp(
        self,
        process: subprocess.Popen,
        user_data_dir: str,
        timeout: float = LAUNCH_TIMEOUT_SECONDS,
    ) -> Tuple[int, str]:
        deadline = time.monotonic() + timeout
        port_file = Path(user_data_dir) / "DevToolsActivePort"
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(
                    f"浏览器进程提前退出（退出码 {process.returncode}）——可尝试 headless=false 排查"
                )
            if port_file.is_file():
                try:
                    lines = port_file.read_text(encoding="ascii").splitlines()
                    port, ws_path = int(lines[0]), lines[1].strip()
                except (OSError, ValueError, IndexError):
                    time.sleep(CHROME_POLL_INTERVAL)
                    continue
                if port > 0 and ws_path.startswith("/devtools/"):
                    return port, ws_path
            time.sleep(CHROME_POLL_INTERVAL)

        raise RuntimeError(
            f"等待 DevToolsActivePort 超时（{timeout:.0f} 秒）——浏览器可能未完成启动"
        )


class FirefoxLauncher(BrowserLauncher):
    """Firefox (Gecko) 浏览器启动器，基于 -start-debugger-server 协议。"""

    def __init__(self, port: int = FIREFOX_DEFAULT_CDP_PORT) -> None:
        self.port = port

    def build_command(
        self,
        executable: str,
        headless: bool,
        user_data_dir: str,
        proxy_flag: str = "",
    ) -> List[str]:
        command = [
            executable,
            "-start-debugger-server",
            str(self.port),
            "-profile",
            user_data_dir,
            "-no-remote",
        ]
        if headless:
            command.insert(1, "-headless")
        command.append("about:blank")
        return command

    def wait_for_cdp(
        self,
        process: subprocess.Popen,
        user_data_dir: str,
        timeout: float = LAUNCH_TIMEOUT_SECONDS,
    ) -> Tuple[int, str]:
        deadline = time.monotonic() + timeout
        url = f"http://127.0.0.1:{self.port}/json/version"
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(
                    f"Firefox 进程提前退出（退出码 {process.returncode}）——可尝试 headless=false 排查"
                )
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Sage-Diagnostic"})
                with urllib.request.urlopen(req, timeout=1.0) as resp:
                    if resp.status == 200:
                        payload = json.loads(resp.read().decode("utf-8"))
                        ws_url = payload.get("webSocketDebuggerUrl", "")
                        if ws_url:
                            from urllib.parse import urlparse

                            parsed = urlparse(ws_url)
                            ws_path = parsed.path
                            if parsed.query:
                                ws_path = f"{ws_path}?{parsed.query}"
                            return self.port, ws_path
            except (urllib.error.URLError, OSError, ValueError, KeyError):
                pass
            time.sleep(FIREFOX_POLL_INTERVAL)

        raise RuntimeError(
            f"等待 Firefox CDP 接口超时（{timeout:.0f} 秒，端口 {self.port}）——浏览器可能未完成启动"
        )


def _windows_candidates() -> List[Tuple[BrowserType, Path]]:
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local_appdata = os.environ.get("LocalAppData", "")
    bases = [program_files, program_files_x86, local_appdata]

    targets = [
        (BrowserType.CHROME, r"Google\Chrome\Application\chrome.exe"),
        (BrowserType.EDGE, r"Microsoft\Edge\Application\msedge.exe"),
        (BrowserType.FIREFOX, r"Mozilla Firefox\firefox.exe"),
    ]

    candidates: List[Tuple[BrowserType, Path]] = []
    for base in bases:
        if not base:
            continue
        for b_type, rel in targets:
            candidates.append((b_type, Path(base) / rel))
    return candidates


def _darwin_candidates() -> List[Tuple[BrowserType, Path]]:
    if platform.system() != "Darwin":
        return []
    targets = [
        (BrowserType.CHROME, "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        (BrowserType.EDGE, "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        (BrowserType.CHROMIUM, "/Applications/Chromium.app/Contents/MacOS/Chromium"),
        (BrowserType.FIREFOX, "/Applications/Firefox.app/Contents/MacOS/firefox"),
    ]
    return [(b_type, Path(path)) for b_type, path in targets]


_LINUX_CHROME_NAMES = (
    (BrowserType.CHROME, "google-chrome"),
    (BrowserType.CHROME, "google-chrome-stable"),
    (BrowserType.CHROMIUM, "chromium"),
    (BrowserType.CHROMIUM, "chromium-browser"),
    (BrowserType.EDGE, "microsoft-edge"),
    (BrowserType.EDGE, "microsoft-edge-stable"),
)


def _infer_browser_type(path_or_name: str) -> BrowserType:
    lower = path_or_name.lower()
    if "firefox" in lower:
        return BrowserType.FIREFOX
    if "edge" in lower or "msedge" in lower:
        return BrowserType.EDGE
    if "chrome" in lower:
        return BrowserType.CHROME
    if "chromium" in lower:
        return BrowserType.CHROMIUM
    return BrowserType.UNKNOWN


def _create_capability(b_type: BrowserType, executable: str) -> BrowserCapability:
    if b_type == BrowserType.FIREFOX:
        return BrowserCapability(
            browser_type=b_type,
            executable=executable,
            version=None,
            cdp_port=FIREFOX_DEFAULT_CDP_PORT,
            cdp_endpoint_strategy="http_json_version",
            launcher=FirefoxLauncher(port=FIREFOX_DEFAULT_CDP_PORT),
        )
    return BrowserCapability(
        browser_type=b_type,
        executable=executable,
        version=None,
        cdp_port=0,
        cdp_endpoint_strategy="devtools_active_port",
        launcher=ChromeLauncher(),
    )


def discover_and_select() -> Optional[BrowserCapability]:
    """按优先级顺序发现并选择首选浏览器。

    优先级链：
    1. 环境变量 SAGE_BROWSER_PATH（最高优先级，向后兼容）
    2. 环境变量 SAGE_FIREFOX_PATH（Firefox 显式指定）
    3. Windows / macOS 平台路径或 Linux PATH 中的 Chrome/Edge/Chromium
    4. 平台路径或 PATH 中的 Firefox
    """
    # 1. 显式环境变量 SAGE_BROWSER_PATH
    env_browser = os.environ.get("SAGE_BROWSER_PATH")
    if env_browser and Path(env_browser).is_file():
        b_type = _infer_browser_type(env_browser)
        return _create_capability(b_type, env_browser)

    # 2. 显式环境变量 SAGE_FIREFOX_PATH
    env_firefox = os.environ.get("SAGE_FIREFOX_PATH")
    if env_firefox and Path(env_firefox).is_file():
        return _create_capability(BrowserType.FIREFOX, env_firefox)

    # 3. Windows 平台候选
    if os.name == "nt":
        candidates = _windows_candidates()
        # 先找 Chrome / Edge
        for b_type, path in candidates:
            if b_type in (BrowserType.CHROME, BrowserType.EDGE) and path.is_file():
                return _create_capability(b_type, str(path))
        # 再找 Firefox
        for b_type, path in candidates:
            if b_type == BrowserType.FIREFOX and path.is_file():
                return _create_capability(b_type, str(path))
        # 兜底查 PATH 中的 firefox / chrome
        for name in ("chrome", "msedge", "firefox"):
            found = shutil.which(name)
            if found:
                return _create_capability(_infer_browser_type(name), found)
        return None

    # 4. macOS 平台候选
    if platform.system() == "Darwin":
        darwin_candidates = _darwin_candidates()
        # 先找 Chromium 系
        for b_type, path in darwin_candidates:
            if b_type != BrowserType.FIREFOX and path.is_file():
                return _create_capability(b_type, str(path))
        # 再找 Firefox
        for b_type, path in darwin_candidates:
            if b_type == BrowserType.FIREFOX and path.is_file():
                return _create_capability(b_type, str(path))

    # 5. Linux / POSIX：先 Chromium 系 PATH，后 Firefox PATH
    for b_type, name in _LINUX_CHROME_NAMES:
        found = shutil.which(name)
        if found:
            return _create_capability(b_type, found)

    firefox_found = shutil.which("firefox")
    if firefox_found:
        return _create_capability(BrowserType.FIREFOX, firefox_found)

    return None
