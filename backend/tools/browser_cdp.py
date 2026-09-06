"""浏览器自动化基础设施（对标增强 G7，docs/plans §2.1）。

经 CDP（Chrome DevTools Protocol）驱动本机 Chrome/Edge：

- **发现**：环境变量 ``SAGE_BROWSER_PATH`` 优先，回退平台常见安装路径
  与 PATH（chrome / chromium / edge）；
- **启动**：``--remote-debugging-port=0``（随机端口）+ 独立临时
  user-data-dir（不污染用户浏览器配置），通过 ``DevToolsActivePort``
  文件握手拿到真实端口与 browser 端 WS 路径；
- **命令**：每次调用开一条短连接（localhost，毫秒级），attach 目标页
  后发送命令、按 id 收响应、丢弃事件帧 —— 无长连接状态机，崩溃/超时
  影响面为单次调用；
- **生命周期**：进程级管理器（上限 ``MAX_BROWSER_SESSIONS``），后端
  退出时 ``close_all``（main.py lifespan shutdown 钩子）。

安全边界：仅回环连接（browser_ws 强制）；导航仅允许 http/https/about/
data（拒绝 file:// / chrome:// / javascript:，见 browser_tool 校验）。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .browser_ws import ws_close, ws_connect, ws_recv_text, ws_send_text

logger = logging.getLogger(__name__)

#: 并发浏览器实例上限（每个实例是独立 Chromium 进程 + 临时目录）
MAX_BROWSER_SESSIONS = 4

#: web_fetch 渲染池的保留 browser_id（web_render 专用）。"唯一实例"解析
#: 跳过它 —— 渲染池后台常驻时 browser_snapshot 仍应能免 id 解析用户实例。
RESERVED_BROWSER_ID = "render-pool"

#: 启动握手超时（等待 DevToolsActivePort 文件出现）
LAUNCH_TIMEOUT_SECONDS = 30.0

#: 单条 CDP 命令超时
CDP_TIMEOUT_SECONDS = 20.0

#: DevToolsActivePort 轮询间隔
_LAUNCH_POLL_INTERVAL = 0.2


class BrowserCDPError(RuntimeError):
    """CDP 命令失败（协议错误 / 目标丢失 / 命令报 errorText）。"""


# ---------------------------------------------------------------------------
# 浏览器可执行文件发现
# ---------------------------------------------------------------------------

_LINUX_CANDIDATES = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "microsoft-edge",
    "microsoft-edge-stable",
)


def _windows_candidates() -> List[Path]:
    # Windows 环境变量的规范拼写就是这种大小写（os.environ 大小写不敏感，但名字本身如此）
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")  # noqa: SIM112
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")  # noqa: SIM112
    local_appdata = os.environ.get("LocalAppData", "")  # noqa: SIM112
    chrome_rel = r"Google\Chrome\Application\chrome.exe"
    edge_rel = r"Microsoft\Edge\Application\msedge.exe"
    bases = [program_files, program_files_x86, local_appdata]
    return [
        Path(base) / rel
        for base in bases
        if base
        for rel in (chrome_rel, edge_rel)
    ]


def discover_browser_executable() -> Optional[str]:
    """按 环境变量 → 平台路径 → PATH 顺序找 Chromium 系浏览器。"""
    env_override = os.environ.get("SAGE_BROWSER_PATH")
    if env_override and Path(env_override).is_file():
        return env_override
    if os.name == "nt":
        for candidate in _windows_candidates():
            if candidate.is_file():
                return str(candidate)
        return None
    # POSIX：Linux/WSL 走 PATH，macOS 走应用包路径
    for name in _LINUX_CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    return _darwin_candidates()


def _darwin_candidates() -> Optional[str]:
    import platform

    if platform.system() != "Darwin":
        return None
    for app in ("Google Chrome", "Microsoft Edge", "Chromium"):
        candidate = Path("/Applications") / f"{app}.app" / "Contents" / "MacOS" / app
        if candidate.is_file():
            return str(candidate)
    return None


# ---------------------------------------------------------------------------
# 会话与生命周期
# ---------------------------------------------------------------------------


@dataclass
class BrowserSession:
    """一个由 Sage 启动的浏览器实例。"""

    browser_id: str
    executable: str
    headless: bool
    user_data_dir: str
    process: subprocess.Popen
    port: int
    ws_path: str

    def is_alive(self) -> bool:
        return self.process.poll() is None


class BrowserSessionManager:
    """进程级浏览器会话表（线程安全，上限 MAX_BROWSER_SESSIONS）。"""

    def __init__(self) -> None:
        self._sessions: Dict[str, BrowserSession] = {}

    def register(self, session: BrowserSession) -> None:
        if len(self._sessions) >= MAX_BROWSER_SESSIONS:
            raise BrowserCDPError(
                f"浏览器实例数已达上限 {MAX_BROWSER_SESSIONS}，请先用 browser_close 关闭"
            )
        self._sessions[session.browser_id] = session

    def get(self, browser_id: Optional[str]) -> Optional[BrowserSession]:
        """按 id 取会话；None → 唯一"用户"实例（单实例场景免传 id）。

        保留 id（RESERVED_BROWSER_ID，web_fetch 渲染池）不算用户实例。
        """
        if browser_id:
            return self._sessions.get(browser_id)
        user_sessions = [
            session
            for session_id, session in self._sessions.items()
            if session_id != RESERVED_BROWSER_ID
        ]
        if len(user_sessions) == 1:
            return user_sessions[0]
        return None

    def require(self, browser_id: Optional[str]) -> BrowserSession:
        session = self.get(browser_id)
        if session is None:
            if browser_id:
                raise BrowserCDPError(f"未知 browser_id: {browser_id}")
            raise BrowserCDPError(
                "没有运行中的浏览器实例（可多实例时必须传 browser_id）——先调用 browser_launch"
            )
        if not session.is_alive():
            self._sessions.pop(session.browser_id, None)
            raise BrowserCDPError("浏览器进程已退出（可能被用户关闭）——请重新 browser_launch")
        return session

    def remove(self, browser_id: str) -> Optional[BrowserSession]:
        return self._sessions.pop(browser_id, None)

    def count(self) -> int:
        return len(self._sessions)

    def close_all(self) -> int:
        """关闭全部实例（后端退出钩子）；返回关闭数。"""
        count = 0
        for browser_id in list(self._sessions):
            session = self._sessions.pop(browser_id)
            _terminate_session(session)
            count += 1
        return count


def _terminate_session(session: BrowserSession) -> None:
    """终止浏览器进程 + 尽力清理临时目录（任何失败静默记日志）。"""
    try:
        session.process.terminate()
        try:
            session.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            session.process.kill()
    except OSError as exc:
        logger.warning("browser terminate 失败: %s", exc)
    shutil.rmtree(session.user_data_dir, ignore_errors=True)


_manager: Optional[BrowserSessionManager] = None


def get_browser_manager() -> BrowserSessionManager:
    global _manager
    if _manager is None:
        _manager = BrowserSessionManager()
    return _manager


def launch_browser(
    headless: bool = True, browser_id: Optional[str] = None
) -> BrowserSession:
    """启动浏览器实例并完成 DevToolsActivePort 握手。

    Args:
        headless:   无头模式（web_fetch 渲染池恒为 True）。
        browser_id: 显式指定会话 id（web_fetch 渲染池传保留 id
                    RESERVED_BROWSER_ID）；缺省生成随机 id。

    Raises:
        BrowserCDPError: 找不到浏览器 / 启动超时 / 实例数超限。
    """
    executable = discover_browser_executable()
    if not executable:
        raise BrowserCDPError(
            "未找到 Chrome/Edge 浏览器：请安装或用环境变量 SAGE_BROWSER_PATH 指定可执行文件路径"
        )

    user_data_dir = tempfile.mkdtemp(prefix="sage_browser_")
    command = [
        executable,
        "--remote-debugging-port=0",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-background-networking",
        "--window-size=1440,900",
        "about:blank",
    ]
    if headless:
        # Chrome 109+（Win7 末代版本）起支持 new headless
        command.insert(1, "--headless=new")

    try:
        process = subprocess.Popen(  # noqa: S603 — 可执行文件来自受控发现逻辑
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
    except OSError as exc:
        shutil.rmtree(user_data_dir, ignore_errors=True)
        raise BrowserCDPError(f"浏览器启动失败: {exc}")

    deadline = time.monotonic() + LAUNCH_TIMEOUT_SECONDS
    port_file = Path(user_data_dir) / "DevToolsActivePort"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            shutil.rmtree(user_data_dir, ignore_errors=True)
            raise BrowserCDPError(
                f"浏览器进程提前退出（退出码 {process.returncode}）——可尝试 headless=false 排查"
            )
        if port_file.is_file():
            try:
                lines = port_file.read_text(encoding="ascii").splitlines()
                port, ws_path = int(lines[0]), lines[1].strip()
            except (OSError, ValueError, IndexError):
                time.sleep(_LAUNCH_POLL_INTERVAL)
                continue
            if port > 0 and ws_path.startswith("/devtools/"):
                session = BrowserSession(
                    browser_id=browser_id or uuid.uuid4().hex[:12],
                    executable=executable,
                    headless=headless,
                    user_data_dir=user_data_dir,
                    process=process,
                    port=port,
                    ws_path=ws_path,
                )
                get_browser_manager().register(session)
                return session
        time.sleep(_LAUNCH_POLL_INTERVAL)

    _terminate_session(
        BrowserSession("", executable, headless, user_data_dir, process, 0, "")
    )
    raise BrowserCDPError(
        f"等待 DevToolsActivePort 超时（{LAUNCH_TIMEOUT_SECONDS:.0f} 秒）——浏览器可能未完成启动"
    )


# ---------------------------------------------------------------------------
# CDP 命令
# ---------------------------------------------------------------------------


class _CDPConnection:
    """单次调用的短连接：握手、attach、命令、按 id 收响应。"""

    def __init__(self, session: BrowserSession) -> None:
        self.sock = ws_connect("127.0.0.1", session.port, session.ws_path, timeout=CDP_TIMEOUT_SECONDS)
        self._next_id = 0

    def command(
        self, method: str, params: Optional[Dict[str, Any]] = None, session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        self._next_id += 1
        message: Dict[str, Any] = {"id": self._next_id, "method": method, "params": params or {}}
        if session_id:
            message["sessionId"] = session_id
        ws_send_text(self.sock, json.dumps(message))
        deadline = time.monotonic() + CDP_TIMEOUT_SECONDS
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BrowserCDPError(f"CDP 命令超时: {method}")
            self.sock.settimeout(remaining)
            raw = ws_recv_text(self.sock)
            data = json.loads(raw)
            if data.get("id") != self._next_id:
                continue  # 事件帧 —— 丢弃
            if "error" in data:
                error = data["error"]
                raise BrowserCDPError(
                    f"CDP 错误 ({method}): {error.get('message', 'unknown')}"
                )
            return data.get("result") or {}

    def close(self) -> None:
        ws_close(self.sock)


def _list_page_targets(session: BrowserSession) -> List[Dict[str, Any]]:
    connection = _CDPConnection(session)
    try:
        result = connection.command("Target.getTargets")
    finally:
        connection.close()
    return [
        info
        for info in result.get("targetInfos", [])
        if info.get("type") == "page"
    ]


def ensure_page_target(session: BrowserSession, target_id: Optional[str] = None) -> str:
    """解析可用页面目标；无页面 / 指定目标不存在时新建 about:blank 页。"""
    pages = _list_page_targets(session)
    if target_id:
        if any(info.get("targetId") == target_id for info in pages):
            return target_id
        raise BrowserCDPError(f"未知 target_id: {target_id}")
    if pages:
        return pages[0]["targetId"]
    connection = _CDPConnection(session)
    try:
        result = connection.command("Target.createTarget", {"url": "about:blank"})
    finally:
        connection.close()
    created = result.get("targetId")
    if not created:
        raise BrowserCDPError("创建页面目标失败")
    return created


def cdp_command(
    session: BrowserSession,
    method: str,
    params: Optional[Dict[str, Any]] = None,
    target_id: Optional[str] = None,
) -> Dict[str, Any]:
    """向指定页面目标发送一条 CDP 命令并返回 result。

    一次调用 = 一条短连接（attach → command → close）。页面级方法
    自动带 sessionId；浏览器级方法（Target.*）不带。
    """
    connection = _CDPConnection(session)
    try:
        if method.startswith("Target.") and method not in ("Target.attachToTarget",):
            return connection.command(method, params)
        resolved_target = ensure_page_target(session, target_id)
        attached = connection.command(
            "Target.attachToTarget", {"targetId": resolved_target, "flatten": True}
        )
        page_session_id = attached.get("sessionId")
        if not page_session_id:
            raise BrowserCDPError("attach 页面目标失败（无 sessionId）")
        return connection.command(method, params, session_id=page_session_id)
    finally:
        connection.close()


__all__ = [
    "BrowserCDPError",
    "BrowserSession",
    "BrowserSessionManager",
    "CDP_TIMEOUT_SECONDS",
    "LAUNCH_TIMEOUT_SECONDS",
    "MAX_BROWSER_SESSIONS",
    "RESERVED_BROWSER_ID",
    "cdp_command",
    "discover_browser_executable",
    "ensure_page_target",
    "get_browser_manager",
    "launch_browser",
]
