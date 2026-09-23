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

import asyncio
import contextlib
import json
import logging
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

from .browser_ws import ws_close, ws_connect, ws_recv_text, ws_send_text

logger = logging.getLogger(__name__)

#: 并发浏览器实例上限（每个实例是独立 Chromium 进程 + 临时目录）
MAX_BROWSER_SESSIONS = 4

#: web_fetch 渲染池的保留 browser_id（web_render 专用）。"唯一实例"解析
#: 跳过它 —— 渲染池后台常驻时 browser_snapshot 仍应能免 id 解析用户实例。
RESERVED_BROWSER_ID = "render-pool"

#: 一次性（非持久）浏览器 user-data-dir 的目录名前缀，启动清扫按此匹配
EPHEMERAL_PREFIX = "sage_browser_"

#: 启动清扫的默认判龄阈值：24 小时未被写过的临时目录视为孤儿
SWEEP_MAX_AGE_SECONDS = 24 * 3600.0

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
    return [Path(base) / rel for base in bases if base for rel in (chrome_rel, edge_rel)]


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
    #: 持久 profile（登录态跨会话保留）；False = 临时目录，终止时删除
    persistent: bool = False
    #: 持久 profile 目录名（persistent=True 时记录；AU3 自动刷新按名复用）
    profile_name: str = ""

    def is_alive(self) -> bool:
        return self.process.poll() is None


class BrowserSessionManager:
    """进程级浏览器会话表（线程安全，上限 MAX_BROWSER_SESSIONS）。"""

    def __init__(self) -> None:
        self._sessions: Dict[str, BrowserSession] = {}

    def register(self, session: BrowserSession) -> None:
        old = self._sessions.pop(session.browser_id, None)
        if old is not None and old is not session:
            # 固定 id 的池并发重建时曾会静默覆盖旧会话对象（连带其临时目录
            # 永久遗留）——改为显式回收旧实例并留痕。
            logger.warning(
                "browser_id 冲突（%s）：回收旧实例 pid=%s",
                session.browser_id,
                getattr(old.process, "pid", None),
            )
            _terminate_session(old)
        if len(self._sessions) >= MAX_BROWSER_SESSIONS:
            raise BrowserCDPError(
                f"浏览器实例数已达上限 {MAX_BROWSER_SESSIONS}，请先用 browser_close 关闭"
            )
        self._sessions[session.browser_id] = session

    def get(self, browser_id: Optional[str]) -> Optional[BrowserSession]:
        """按 id 取会话；None → 唯一"用户"实例（单实例场景免传 id）。

        保留 id（RESERVED_BROWSER_ID 及其 ``render-pool-`` 前缀槽位，web_fetch
        渲染池）不算用户实例——否则多槽渲染池会挤掉单用户浏览器免传 id 的
        便利解析（R24）。
        """
        if browser_id:
            return self._sessions.get(browser_id)
        user_sessions = [
            session
            for session_id, session in self._sessions.items()
            if session_id != RESERVED_BROWSER_ID
            and not session_id.startswith(RESERVED_BROWSER_ID + "-")
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
            # 进程已自行退出（崩溃/用户关窗）：terminate 部分幂等跳过，
            # 重点是回收其一次性目录，否则永久遗留。
            _terminate_session(session)
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
    """终止浏览器进程 + 尽力清理临时目录（任何失败静默记日志）。

    持久 profile（session.persistent）只关进程不删目录 —— 登录态跨会话
    保留的前提；启动失败路径同样经由本函数，持久目录即使启动失败也不删
    （里面可能有用户既有登录态）。
    """
    # SN3：先停事件通道（常驻 WS 线程），再杀进程
    try:
        from .browser_events import stop_download_tracking

        if session.browser_id:
            stop_download_tracking(session.browser_id)
    except Exception:  # noqa: BLE001 — 事件通道清理失败不阻断终止
        logger.debug("停止下载事件通道失败", exc_info=True)
    try:
        session.process.terminate()
        try:
            session.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            session.process.kill()
    except OSError as exc:
        logger.warning("browser terminate 失败: %s", exc)
    # Windows 上 terminate/kill 只作用于父进程；renderer/gpu/network 子进程
    # 仍持有 user_data_dir 文件句柄，直接 rmtree 会失败 —— 强杀整棵进程树。
    _kill_process_tree(session.process)
    if getattr(session, "persistent", False):
        return
    _remove_dir_with_retry(session.user_data_dir)


def _kill_process_tree(process: subprocess.Popen) -> None:
    """Windows：taskkill /T /F 强杀整棵进程树（进程已退出时静默无操作）。

    POSIX 上 Chromium 子进程随父进程退出自行收尾，暂不引入进程组/psutil。
    """
    if os.name != "nt":
        return
    pid = getattr(process, "pid", None)  # 测试假体可能无 pid
    if pid is None:
        return
    try:
        subprocess.run(  # noqa: S603 — taskkill 是系统命令，参数均为整数 pid
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        logger.debug("taskkill 进程树失败（忽略）: pid=%s", pid, exc_info=True)


def _remove_dir_with_retry(path: str, attempts: int = 5) -> None:
    """带退避重试删除目录；最终失败留 warning（由启动清扫兜底）。

    不再用 ``ignore_errors=True`` 静默吞错——历史上 38/41 个泄漏目录
    证明"失败无声"让问题积累数周不可见。
    """
    for attempt in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt < attempts - 1:
                time.sleep(0.2 * (attempt + 1))
    logger.warning("浏览器临时目录清理失败（将由启动清扫兜底）: %s", path)


def _data_root() -> Path:
    """应用数据根：packaged 模式 = %APPDATA%/Sage，开发态 = 项目 ``data/``。"""
    env_path = os.environ.get("SAGE_DB_PATH")
    if env_path:
        return Path(env_path).parent
    return Path(__file__).parent.parent.parent / "data"


def _profiles_root() -> Path:
    """持久 profile 根目录（见 ``_data_root``）。"""
    root = _data_root() / "browser-profiles"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _ephemeral_root() -> Path:
    """一次性浏览器 user-data-dir 根目录。

    与持久 profile 同数据根（E: 盘 / APPDATA），不再挤占 C 盘 %TEMP%；
    清扫、配额、大小统计都只在这一个目录下进行。
    """
    root = _data_root() / "browser-ephemeral"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _dir_is_stale(path: Path, cutoff: float) -> bool:
    """子树内最大 mtime 早于 cutoff 才算过期；一发现不早于 cutoff 的项即短路。

    不能只看顶层目录 mtime：Windows 上它只在顶层增删条目时更新，而运行中的
    Chromium 持续写的是深层 cache/leveldb 文件——长活会话会被顶层判龄误删。
    """
    try:
        if path.stat().st_mtime >= cutoff:
            return False
        for root, dirs, files in os.walk(path):
            for name in dirs + files:
                try:
                    if (Path(root) / name).stat().st_mtime >= cutoff:
                        return False  # 仍在被写：非孤儿
                except OSError:
                    continue
    except OSError:
        return False
    return True


def sweep_stale_browser_dirs(max_age_seconds: float = SWEEP_MAX_AGE_SECONDS) -> int:
    """启动兜底清扫：删除超龄的浏览器一次性目录，返回回收数。

    进程被硬杀（Electron 退出 kill 后端、开发期重启、崩溃、断电）时进程内
    清理无法执行，只能靠下一次启动回收。两处都扫：新数据根
    ``browser-ephemeral/`` 与旧版遗留在 ``%TEMP%`` 的 ``sage_browser_*``。

    只按 **mtime** 判龄（运行中的 profile 持续被写，mtime 恒新），不会误删
    其他后端实例正在使用的目录。``SAGE_TEMP_PROFILE_SWEEP=0`` 可关闭。
    幂等，可反复执行；被占用的目录本次删不掉，下次启动再试。
    """
    if os.environ.get("SAGE_TEMP_PROFILE_SWEEP", "1") == "0":
        return 0
    now = time.time()
    removed = 0
    roots = [_ephemeral_root(), Path(tempfile.gettempdir())]
    for root in roots:
        if not root.is_dir():
            continue
        for candidate in root.glob(f"{EPHEMERAL_PREFIX}*"):
            if not candidate.is_dir():
                continue
            if not _dir_is_stale(candidate, now - max_age_seconds):
                continue
            try:
                shutil.rmtree(candidate)
                removed += 1
            except OSError:
                logger.debug("启动清扫暂无法删除（下次启动重试）: %s", candidate)
    if removed:
        logger.info("启动清扫回收 %d 个过期浏览器临时目录", removed)
    return removed


def browser_downloads_root() -> Path:
    """浏览器内触发下载的兜底落盘目录（未绑定工作区时）。"""
    env_path = os.environ.get("SAGE_DB_PATH")
    if env_path:
        root = Path(env_path).parent / "browser-downloads"
    else:
        base_dir = Path(__file__).parent.parent.parent
        root = base_dir / "data" / "browser-downloads"
    root.mkdir(parents=True, exist_ok=True)
    return root


_manager: Optional[BrowserSessionManager] = None


def get_browser_manager() -> BrowserSessionManager:
    global _manager
    if _manager is None:
        _manager = BrowserSessionManager()
    return _manager


def _build_launch_command(
    executable: str, headless: bool, user_data_dir: str, proxy_flag: str = ""
) -> List[str]:
    """构造浏览器启动命令（纯函数便于单测）。

    ``proxy_flag`` 非空时追加 ``--proxy-server=``（用户级代理配置，见
    http_factory.browser_proxy_flag）——否则浏览器通道绕过代理，代理用户
    经 headless 渲染访问被墙站点依旧不通。
    """
    command = [
        executable,
        "--remote-debugging-port=0",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-background-networking",
        "--window-size=1440,900",
        # AB4（Round 5）：不向页面暴露自动化痕迹 —— 默认 Chrome 会把
        # navigator.webdriver 置 true 并挂 "Chrome is being controlled" 提示，
        # 是最廉价的 bot 信号。只做"不主动暴露"，不做验证码破解。
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
    ]
    if proxy_flag:
        command.append(f"--proxy-server={proxy_flag}")
    command.append("about:blank")
    if headless:
        # Chrome 109+（Win7 末代版本）起支持 new headless
        command.insert(1, "--headless=new")
    return command


def launch_browser(
    headless: bool = True,
    browser_id: Optional[str] = None,
    persistent: bool = False,
    profile_name: str = "default",
) -> BrowserSession:
    """启动浏览器实例并完成 DevToolsActivePort 握手。

    Args:
        headless:     无头模式（web_fetch 渲染池恒为 True）。
        browser_id:   显式指定会话 id（web_fetch 渲染池传保留 id
                      RESERVED_BROWSER_ID）；缺省生成随机 id。
        persistent:   使用持久 profile（``_profiles_root()/<profile_name>``，
                      登录态跨会话保留）；False = 一次性临时目录。
        profile_name: 持久 profile 目录名（净化为安全 basename）。

    Raises:
        BrowserCDPError: 找不到浏览器 / 启动超时 / 实例数超限。
    """
    executable = discover_browser_executable()
    if not executable:
        raise BrowserCDPError(
            "未找到 Chrome/Edge 浏览器：请安装或用环境变量 SAGE_BROWSER_PATH 指定可执行文件路径"
        )

    if persistent:
        from .download_tool import sanitize_filename

        profile_dir = _profiles_root() / sanitize_filename(profile_name or "default")
        profile_dir.mkdir(parents=True, exist_ok=True)
        user_data_dir = str(profile_dir)
    else:
        user_data_dir = tempfile.mkdtemp(prefix=EPHEMERAL_PREFIX, dir=str(_ephemeral_root()))
    from .http_factory import browser_proxy_flag

    command = _build_launch_command(executable, headless, user_data_dir, browser_proxy_flag())

    try:
        process = subprocess.Popen(  # noqa: S603 — 可执行文件来自受控发现逻辑
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
    except OSError as exc:
        if not persistent:
            _remove_dir_with_retry(user_data_dir)
        raise BrowserCDPError(f"浏览器启动失败: {exc}")

    deadline = time.monotonic() + LAUNCH_TIMEOUT_SECONDS
    port_file = Path(user_data_dir) / "DevToolsActivePort"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            if not persistent:
                _kill_process_tree(process)
                _remove_dir_with_retry(user_data_dir)
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
                    persistent=persistent,
                    profile_name=str(profile_name or "") if persistent else "",
                )
                get_browser_manager().register(session)
                return session
        time.sleep(_LAUNCH_POLL_INTERVAL)

    _terminate_session(
        BrowserSession(
            "", executable, headless, user_data_dir, process, 0, "", persistent=persistent
        )
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
        self.sock = ws_connect(
            "127.0.0.1", session.port, session.ws_path, timeout=CDP_TIMEOUT_SECONDS
        )
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
                raise BrowserCDPError(f"CDP 错误 ({method}): {error.get('message', 'unknown')}")
            return data.get("result") or {}

    def close(self) -> None:
        ws_close(self.sock)


def _list_page_targets(session: BrowserSession) -> List[Dict[str, Any]]:
    connection = _CDPConnection(session)
    try:
        result = connection.command("Target.getTargets")
    finally:
        connection.close()
    return [info for info in result.get("targetInfos", []) if info.get("type") == "page"]


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
        # 浏览器级方法不带 sessionId（Target.* 自身即浏览器级；Browser.* 如
        # setDownloadBehavior、Storage.* 如 setCookies/getCookies（AU5 渲染
        # 通道 cookie 注入 / 回写）都走浏览器作用域，attach 页面反而可能报错）。
        if method.startswith(("Target.", "Browser.", "Storage.")) and method not in (
            "Target.attachToTarget",
        ):
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


#: AB4 最小 stealth：只堵三项最廉价的自动化信号，不追求完整 stealth 库。
#: 新 headless（--headless=new）下 navigator.webdriver 仍为 true，需在文档创建前覆写。
STEALTH_SCRIPT = """
(() => {
  try {
    Object.defineProperty(Navigator.prototype, 'webdriver', {get: () => undefined, configurable: true});
  } catch (e) {}
  try {
    if (!window.chrome) { window.chrome = { runtime: {}, loadTimes() {}, csi() {}, app: {} }; }
  } catch (e) {}
  try {
    if (!navigator.languages || navigator.languages.length === 0) {
      Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en'], configurable: true});
    }
  } catch (e) {}
})();
"""


def apply_stealth(
    session: BrowserSession, target_id: Optional[str] = None, command: Any = None
) -> bool:
    """在目标页注入 ``STEALTH_SCRIPT``（新文档创建前执行）。失败返回 False，不抛。

    ``command`` 可注入 ``cdp_command`` 同签名函数（调用方模块级补丁 / 测试假体）。
    """
    send = command or cdp_command
    try:
        send(
            session,
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": STEALTH_SCRIPT},
            target_id=target_id,
        )
        return True
    except BrowserCDPError as exc:
        logger.debug("stealth 注入失败（忽略）: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Persistent CDP session (Phase 2 of arena automation)
# ---------------------------------------------------------------------------
#
# Unlike cdp_command() (short-lived, one command per connection), a persistent
# session holds a single WebSocket open for the lifetime of the observation
# and routes incoming CDP event frames to an in-memory queue.

_message_id_lock = threading.Lock()
_message_id_counter = 0


def _next_message_id() -> int:
    global _message_id_counter
    with _message_id_lock:
        _message_id_counter += 1
        return _message_id_counter


def _reset_message_id() -> None:
    """Reset the counter; intended for tests only."""
    global _message_id_counter
    with _message_id_lock:
        _message_id_counter = 0


class PersistentCDPSession:
    """Context manager wrapping a long-lived CDP WebSocket.

    Usage:
        with cdp_persistent_session(session) as cdp:
            await cdp.send_async("Network.enable")
            while True:
                event = await cdp.next_event()
                ...

    For sync (test) usage, the constructor accepts an injected ``ws_factory``
    that returns an object with ``send`` / ``recv`` / ``close`` async methods.
    """

    #: Incoming CDP event frames (asyncio.Queue when async, deque when sync).
    events: Any = None

    def __init__(
        self,
        browser_session: Any,
        ws_factory: Optional[Any] = None,
    ):
        self._browser_session = browser_session
        self._ws_factory = ws_factory  # for tests
        self._ws: Any = None
        self._reader_task: Optional[asyncio.Task] = None
        self._sync_queue: deque = deque()  # for sync test mode
        self.events: Any = None  # asyncio.Queue when async, deque when sync

    def __enter__(self) -> PersistentCDPSession:
        if self._ws_factory is not None:
            # Sync test path: caller provides a fake WS; we just queue frames manually
            self._ws = self._ws_factory()
            self.events = self._sync_queue
            return self
        # Real path: caller should use cdp_persistent_session() async helper below
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._ws is not None:
            with contextlib.suppress(Exception):
                if hasattr(self._ws, "close"):
                    # close may be async; for sync we accept either
                    result = self._ws.close()
                    if asyncio.iscoroutine(result):
                        # In sync context, schedule and wait
                        try:
                            loop = asyncio.get_event_loop()
                            if loop.is_running():
                                loop.create_task(result)
                            else:
                                loop.run_until_complete(result)
                        except RuntimeError:
                            asyncio.run(result)

    async def send_async(self, method: str, params: Optional[Dict] = None) -> Dict:
        """Send a command and return the response dict."""
        if self._ws is None:
            raise BrowserCDPError("session not connected")
        msg_id = _next_message_id()
        payload = {"id": msg_id, "method": method, "params": params or {}}
        if hasattr(self._ws, "send"):
            await self._ws.send(json.dumps(payload))
        # Caller is responsible for matching responses via the event queue
        return {"id": msg_id, "method": method}

    # Public alias matching the interface spec (send).
    send = send_async

    def push_event(self, frame: Dict) -> None:
        """Inject an event frame (used by tests and by the async reader task)."""
        if isinstance(self.events, deque):
            self.events.append(frame)
        elif self.events is not None:
            self.events.put_nowait(frame)

    def close(self) -> None:
        """Close the underlying WebSocket."""
        self.__exit__(None, None, None)


@contextlib.contextmanager
def cdp_persistent_session(browser_session: Any) -> Iterator[PersistentCDPSession]:
    """Sync entry point. For full async lifecycle, use PersistentCDPSession directly."""
    sess = PersistentCDPSession(browser_session)
    try:
        yield sess
    finally:
        sess.close()


class CdpEventPump:
    """长连 CDP WebSocket：attach 页面目标 → Network.enable → 线程回吐事件帧。

    与 ``cdp_command``（一命令一短连接、事件帧被丢弃）互补：模型观测需要的
    恰恰是事件流本身。``stop()`` 置停止位并关 socket，读线程在 socket 超时
    （1s）内感知并退出；连接断开时线程自终，由 ``alive`` 反映真实状态。

    用法::

        pump = CdpEventPump(session, on_event=handler.handle)
        pump.start()
        ...
        pump.stop()
    """

    #: 读线程 socket 超时（决定 stop 的最长感知延迟）
    POLL_TIMEOUT_SEC = 1.0

    def __init__(
        self,
        session: Any,
        on_event: Callable[[Dict[str, Any]], None],
        target_id: Optional[str] = None,
        connect_fn: Optional[Callable[[Any], Any]] = None,
    ):
        self._session = session
        self._on_event = on_event
        self._target_id = target_id
        self._connect_fn = connect_fn  # 测试注入：返回带 send/recv 语义的假 socket
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._sock: Any = None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="sage-cdp-event-pump", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        sock = self._sock
        if sock is not None:
            with contextlib.suppress(Exception):
                ws_close(sock)
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=self.POLL_TIMEOUT_SEC * 3)
        self._thread = None

    @property
    def alive(self) -> bool:
        return bool(self._thread is not None and self._thread.is_alive())

    # -- internals ---------------------------------------------------------

    def _connect(self) -> Any:
        if self._connect_fn is not None:
            return self._connect_fn(self._session)
        return ws_connect(
            "127.0.0.1", self._session.port, self._session.ws_path, timeout=10
        )

    def _dispatch(self, frame: Dict[str, Any]) -> None:
        try:
            self._on_event(frame)
        except Exception:  # noqa: BLE001 — 回调异常不能带垮泵线程
            logger.debug("CdpEventPump on_event 回调异常（忽略）", exc_info=True)

    def _rpc(
        self,
        sock: Any,
        msg_id: int,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        timeout: float = 10.0,
    ) -> Dict[str, Any]:
        """发送命令并等到同 id 响应；途中收到的事件帧照常转发给回调。"""
        payload: Dict[str, Any] = {"id": msg_id, "method": method, "params": params or {}}
        if session_id:
            payload["sessionId"] = session_id
        ws_send_text(sock, json.dumps(payload))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                sock.settimeout(0.5)
                raw = ws_recv_text(sock)
            except socket.timeout:  # noqa: UP041 — py38 上 socket.timeout ≠ TimeoutError
                continue
            try:
                frame = json.loads(raw)
            except ValueError:
                continue
            if frame.get("id") == msg_id:
                if "error" in frame:
                    message = (frame.get("error") or {}).get("message", "unknown")
                    raise BrowserCDPError(f"CDP 错误 ({method}): {message}")
                return frame.get("result") or {}
            if "method" in frame:
                self._dispatch(frame)
        raise BrowserCDPError(f"CDP 命令超时: {method}")

    def _run(self) -> None:
        try:
            sock = self._connect()
            self._sock = sock
            resolved = ensure_page_target(self._session, self._target_id)
            attached = self._rpc(
                sock, 1, "Target.attachToTarget",
                {"targetId": resolved, "flatten": True},
            )
            page_session_id = str(attached.get("sessionId") or "")
            if not page_session_id:
                raise BrowserCDPError("attach 页面目标失败（无 sessionId）")
            self._rpc(
                sock, 2, "Network.enable", {}, session_id=page_session_id
            )
            while not self._stop.is_set():
                try:
                    sock.settimeout(self.POLL_TIMEOUT_SEC)
                    raw = ws_recv_text(sock)
                except socket.timeout:  # noqa: UP041 — py38 上 socket.timeout ≠ TimeoutError
                    continue
                except Exception:  # noqa: BLE001 — 连接关闭/对端断开
                    break
                try:
                    frame = json.loads(raw)
                except ValueError:
                    continue
                if "method" not in frame:
                    continue  # 无对应命令的响应（理论不应出现）
                self._dispatch(frame)
        except Exception as exc:  # noqa: BLE001 — 建连/握手失败：泵退出
            logger.info("CdpEventPump 退出: %s", exc)
        finally:
            sock = self._sock
            self._sock = None
            if sock is not None:
                with contextlib.suppress(Exception):
                    ws_close(sock)
            self._stop.set()


__all__ = [
    "BrowserCDPError",
    "BrowserSession",
    "BrowserSessionManager",
    "CdpEventPump",
    "CDP_TIMEOUT_SECONDS",
    "EPHEMERAL_PREFIX",
    "LAUNCH_TIMEOUT_SECONDS",
    "MAX_BROWSER_SESSIONS",
    "RESERVED_BROWSER_ID",
    "STEALTH_SCRIPT",
    "SWEEP_MAX_AGE_SECONDS",
    "apply_stealth",
    "browser_downloads_root",
    "cdp_command",
    "cdp_persistent_session",
    "discover_browser_executable",
    "ensure_page_target",
    "get_browser_manager",
    "launch_browser",
    "PersistentCDPSession",
    "sweep_stale_browser_dirs",
]
