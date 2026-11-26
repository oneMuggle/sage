"""浏览器自动化基础设施（对标增强 G7，docs/plans §2.1）。

经 CDP（Chrome DevTools Protocol）驱动本机 Chrome/Edge/Firefox：

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
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple
from urllib.parse import quote, urlparse

from .browser_launcher import (
    EMBEDDED_EXECUTABLE,
    BrowserCapability,
    BrowserLauncher,
    BrowserType,
    ChromeLauncher,
    FirefoxLauncher,
    discover_and_select,
)
from .browser_ws import ws_close, ws_connect, ws_recv_text, ws_send_text

logger = logging.getLogger(__name__)

#: 并发浏览器实例上限默认值（每个实例是独立 Chromium 进程 + 临时目录）。
#: 实际运行时通过 ``get_max_sessions()`` 从 settings 读取用户配置。
DEFAULT_MAX_BROWSER_SESSIONS = 4

#: 兼容旧代码：模块级常量保留为默认值
MAX_BROWSER_SESSIONS = DEFAULT_MAX_BROWSER_SESSIONS


def get_max_sessions() -> int:
    """从 settings 读取浏览器并发上限，回退到默认值 4。

    用户可在设置页调整 2-8 范围。安全边界在函数内强制钳制。
    """
    try:
        from backend.data.settings_repo import SettingsRepository

        repo = SettingsRepository()
        raw = repo.get("browser_config")
        if raw:
            config = json.loads(raw) if isinstance(raw, str) else raw
            value = config.get("maxSessions", DEFAULT_MAX_BROWSER_SESSIONS)
            # 安全边界：2-8
            return max(2, min(8, int(value)))
    except Exception as exc:
        logger.debug("get_max_sessions fallback: %s", exc)
    return DEFAULT_MAX_BROWSER_SESSIONS


def get_lru_evict_enabled() -> bool:
    """从 settings 读取 LRU 自动回收开关，默认关闭。"""
    try:
        from backend.data.settings_repo import SettingsRepository

        repo = SettingsRepository()
        raw = repo.get("browser_config")
        if raw:
            config = json.loads(raw) if isinstance(raw, str) else raw
            return bool(config.get("lruEvict", False))
    except Exception as exc:
        logger.debug("get_lru_evict_enabled fallback: %s", exc)
    return False

#: web_fetch 渲染池的保留 browser_id（web_render 专用）。"唯一实例"解析
#: 跳过它 —— 渲染池后台常驻时 browser_snapshot 仍应能免 id 解析用户实例。
RESERVED_BROWSER_ID = "render-pool"

#: 用户日常浏览器扩展共享标签页的固定会话 id（与
#: ``browser_extension_bridge.EXTENSION_BROWSER_ID`` 保持一致）。
EXTENSION_BROWSER_ID = "external"


def _is_reserved_browser_id(browser_id: str) -> bool:
    """内部渲染池保留槽位（web_fetch 懒重建），不参与用户会话解析。"""
    return browser_id == RESERVED_BROWSER_ID or browser_id.startswith(
        RESERVED_BROWSER_ID + "-"
    )

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

#: Firefox 的调试端口是固定的（``-start-debugger-server <port>``），不像
#: Chromium 支持 ``--remote-debugging-port=0`` 随机端口
FIREFOX_CDP_PORT = 9229

#: Firefox CDP 握手轮询间隔（Firefox 启动与调试服务就绪都比 Chromium 慢）
_FIREFOX_POLL_INTERVAL = 0.5

#: ``SAGE_BROWSER_PATH`` 的 Firefox 专用别名（优先级紧随其后）
FIREFOX_PATH_ENV = "SAGE_FIREFOX_PATH"


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


def _windows_firefox_candidates() -> List[Path]:
    """Firefox 常见安装位置（Chromium 全部缺失时的兜底，Win7 场景）。"""
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")  # noqa: SIM112
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")  # noqa: SIM112
    firefox_rel = r"Mozilla Firefox\firefox.exe"
    bases = [program_files, program_files_x86]
    return [Path(base) / firefox_rel for base in bases if base]


def _infer_browser_type(executable: str) -> BrowserType:
    """按可执行文件名推断浏览器类型（本模块只需区分 Chromium / Firefox）。"""
    if "firefox" in Path(executable).name.lower():
        return BrowserType.FIREFOX
    return BrowserType.CHROME


def _discover_embedded_env() -> Optional[Dict[str, Any]]:
    """读取 Electron 注入的内置浏览器环境（端口/token）；不完整返回 None。"""
    if os.environ.get("SAGE_EMBEDDED_BROWSER", "").strip() != "1":
        return None
    raw_port = os.environ.get("SAGE_EMBEDDED_BROWSER_PORT", "").strip()
    token = os.environ.get("SAGE_EMBEDDED_BROWSER_TOKEN", "").strip()
    if not raw_port or not token:
        return None
    try:
        port = int(raw_port)
    except ValueError:
        return None
    if not 0 < port < 65536:
        return None
    return {"port": port, "token": token}


def _get_user_browser_path() -> Optional[str]:
    """从设置中读取用户配置的浏览器路径。

    `(embedded)` 是设置页「Sage 内置浏览器」选项的哨兵值，不是文件路径，
    需要原样返回交由发现链解析。
    """
    try:
        from backend.data.settings_repo import SettingsRepository

        path = SettingsRepository().get("browser_path")
        if path == EMBEDDED_EXECUTABLE:
            return EMBEDDED_EXECUTABLE
        if path and Path(path).is_file():
            return path
    except Exception as exc:  # noqa: BLE001 — 设置读取失败时回退到平台发现
        logger.debug("读取用户浏览器路径设置失败: %s", exc)
    return None


def discover_browser_executable() -> Optional[str]:
    """按 环境变量 → 用户设置 → 内置兜底 → 平台能力发现 顺序找浏览器。"""
    cap = discover_and_select(_get_user_browser_path())
    return cap.executable if cap else None


def _darwin_candidates() -> Optional[str]:
    import platform

    if platform.system() != "Darwin":
        return None
    for app, exe in (
        ("Google Chrome", "Google Chrome"),
        ("Microsoft Edge", "Microsoft Edge"),
        ("Chromium", "Chromium"),
        ("Firefox", "firefox"),
    ):
        candidate = Path("/Applications") / f"{app}.app" / "Contents" / "MacOS" / exe
        if candidate.is_file():
            return str(candidate)
    return None


#: Chromium 在 exe 同级保留的版本目录名（如 107.0.5304.87）
_VERSION_DIR_RE = re.compile(r"(\d+)\.\d+\.\d+\.\d+")

#: --headless=new 自 Chrome 109 起提供；更老内核（Win7 的 Edge 100 /
#: Chrome 107）只能使用旧无头模式。
NEW_HEADLESS_MIN_MAJOR = 109


def _major_from_version_dirs(executable: str) -> Optional[int]:
    """exe 同级 ``X.Y.Z.W/`` 版本目录的最大大版本号；无则 None（不 spawn 进程）。"""
    try:
        exe_dir = os.path.dirname(executable)
        versions = [
            int(match.group(1))
            for name in os.listdir(exe_dir)
            for match in [_VERSION_DIR_RE.fullmatch(name)]
            if match and os.path.isdir(os.path.join(exe_dir, name))
        ]
        if versions:
            return max(versions)
    except OSError:
        pass
    return None


def chromium_major_version(executable: str) -> Optional[int]:
    """探测 Chromium 系浏览器大版本（版本目录优先；Windows 不执行 --version）。"""
    major = _major_from_version_dirs(executable)
    if major is not None:
        return major
    if os.name == "nt":
        return None
    try:
        completed = subprocess.run(  # noqa: S603 — 可执行路径来自受控发现逻辑
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = _VERSION_DIR_RE.search(completed.stdout or "")
    return int(match.group(1)) if match else None


def headless_flag(executable: str) -> str:
    """按内核版本选择无头开关：旧内核（< 109）回退旧无头模式。

    每次启动命令构造都会调用，因此只做目录扫描（不 spawn 子进程）；
    版本未知时保持现行默认新无头。
    """
    major = _major_from_version_dirs(executable)
    if major is not None and major < NEW_HEADLESS_MIN_MAJOR:
        return "--headless"
    return "--headless=new"


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

    #: 浏览器类型（Chrome/Edge/Chromium/Firefox/Embedded）
    browser_type: BrowserType = BrowserType.CHROME
    #: Embedded：Electron 内置浏览器桥的鉴权 token（仅内存持有）
    bridge_token: str = ""
    #: External：共享该标签页的浏览器扩展设备 id（仅内存持有）
    external_device_id: str = ""
    #: External：用户共享标签页的 Chrome tabId（仅内存持有）
    external_tab_id: str = ""

    #: 当前活动标签页（browser_tabs switch/create 设置；None = 解析为第一个页面）
    active_target_id: Optional[str] = None

    #: P2: 用户给的会话名称（多账号场景下区分用途，如"账号A-审核员"）
    name: str = ""
    #: P1/P3: 最后使用时间（ISO 格式字符串，便于 JSON 序列化；LRU 回收依据）
    last_used_at: str = ""
    #: 启动该实例的聊天会话 id（ToolExecutionContext.session_id）。
    #: "" = 无归属（REST 设置页 / 内部基础设施 / 旧调用方），保持旧解析语义。
    owner: str = ""
    #: 工具执行期间的活动租约数；>0 时上限/LRU 淘汰必须跳过该实例。
    lease_count: int = 0

    def __post_init__(self) -> None:
        # 初始化时设置 last_used_at 为当前时间（如果未提供）
        if not self.last_used_at:
            from datetime import datetime, timezone

            self.last_used_at = datetime.now(timezone.utc).isoformat()  # noqa: UP017

    def touch(self) -> None:
        """更新最后使用时间（每次访问会话时调用）。"""
        from datetime import datetime, timezone

        self.last_used_at = datetime.now(timezone.utc).isoformat()  # noqa: UP017

    def is_alive(self) -> bool:
        return self.process.poll() is None

    def is_leased(self) -> bool:
        """是否有工具调用正在使用该实例（租约未释放）。"""
        return self.lease_count > 0


class BrowserSessionManager:
    """进程级浏览器会话表（线程安全，上限动态读取 settings）。"""

    def __init__(self) -> None:
        self._sessions: Dict[str, BrowserSession] = {}
        # 上限判定是 check-then-act，登录任务线程与渲染池并发注册时需要串行化。
        self._lock = threading.Lock()

    def _counted_locked(self) -> int:
        """按真实浏览器进程计的会话数。

        EMBEDDED 与 Electron 共享同一个 Chromium 进程（见 ``_EmbeddedProcess``），
        每开一个逻辑会话并不会多一个进程；EXTERNAL 是用户自己的标签页。
        两者都不参与进程上限。
        """
        return sum(
            1
            for session in self._sessions.values()
            if getattr(session, "browser_type", None)
            not in (BrowserType.EMBEDDED, BrowserType.EXTERNAL)
        )

    def register(self, session: BrowserSession) -> None:
        evicted: List[BrowserSession] = []
        # 动态读取当前上限（每次注册时读取，用户改设置后立即生效）
        max_sessions = get_max_sessions()
        lru_evict = get_lru_evict_enabled()
        try:
            with self._lock:
                old = self._sessions.pop(session.browser_id, None)
                if old is not None and old is not session:
                    # 固定 id 的池并发重建时曾会静默覆盖旧会话对象（连带其临时目录
                    # 永久遗留）——改为显式回收旧实例并留痕。
                    logger.warning(
                        "browser_id 冲突（%s）：回收旧实例 pid=%s",
                        session.browser_id,
                        getattr(old.process, "pid", None),
                    )
                    evicted.append(old)
                # 已退出实例（用户关窗/崩溃）不占名额：注册前先回收，
                # 否则「关掉浏览器后仍报已达上限」。
                for stale_id, stale in list(self._sessions.items()):
                    if not stale.is_alive():
                        self._sessions.pop(stale_id, None)
                        evicted.append(stale)
                # 用户共享标签页与内置浏览器不需要新进程，不占进程名额。
                needs_slot = (
                    session.browser_id != EXTENSION_BROWSER_ID
                    and getattr(session, "browser_type", None) != BrowserType.EMBEDDED
                )
                if needs_slot and self._counted_locked() >= max_sessions:
                    # 渲染池是懒重建的后台实例：为前台会话让位，下次渲染按需重建。
                    # 内置池会话共享 Electron 单进程，不能个别回收（会误关其它标签页）。
                    # 被租用的池实例正被 in-flight 渲染使用，不能牺牲。
                    for pool_id in [
                        bid
                        for bid, pooled in list(self._sessions.items())
                        if _is_reserved_browser_id(bid)
                        and getattr(pooled, "browser_type", None) != BrowserType.EMBEDDED
                        and not pooled.is_leased()
                    ]:
                        if self._counted_locked() < max_sessions:
                            break
                        evicted.append(self._sessions.pop(pool_id))
                # P3: LRU 自动回收（用户开启时生效；跳过租用中的实例）
                if lru_evict and needs_slot and self._counted_locked() >= max_sessions:
                    lru_evicted = self._evict_lru_locked()
                    if lru_evicted:
                        evicted.append(lru_evicted)
                if needs_slot and self._counted_locked() >= max_sessions:
                    raise BrowserCDPError(
                        f"浏览器实例数已达上限 {max_sessions}：请关闭 Sage 打开的"
                        "浏览器窗口后重试（对话中可调用 browser_close 关闭实例）；"
                        "若有实例正在执行操作，请等其完成后重试"
                    )
                self._sessions[session.browser_id] = session
        finally:
            # 进程终止可能较慢，统一放到锁外执行；抛上限错误时也让位结果生效。
            for stale in evicted:
                _terminate_session(stale)

    def get(self, browser_id: Optional[str]) -> Optional[BrowserSession]:
        """按 id 取会话；None → 优先用户共享的日常浏览器，其次唯一实例。

        用户显式共享的标签页（EXTERNAL）优先于 Sage 自己启动的浏览器：
        这是用户刚刚做出的选择，agent 的下一步操作应符合该意图。

        保留 id（RESERVED_BROWSER_ID 及其 ``render-pool-`` 前缀槽位，web_fetch
        渲染池）不算用户实例——否则多槽渲染池会挤掉单用户浏览器免传 id 的
        便利解析（R24）。
        """
        if browser_id:
            with self._lock:
                return self._sessions.get(browser_id)
        with self._lock:
            external = self._sessions.get(EXTENSION_BROWSER_ID)
            if external is not None:
                return external
            user_sessions = [
                session
                for session_id, session in self._sessions.items()
                if session_id != RESERVED_BROWSER_ID
                and not session_id.startswith(RESERVED_BROWSER_ID + "-")
            ]
        if len(user_sessions) == 1:
            return user_sessions[0]
        return None

    def owned_sessions(self, owner: str) -> List[BrowserSession]:
        """返回 ``owner`` 会话拥有的存活用户实例（过滤保留渲染池）。

        ``owner == ""`` 表示无归属（REST/基础设施/旧调用方），返回空列表 ——
        这些调用方走 ``get(None)`` 的旧解析语义，不做归属区分。
        """
        if not owner:
            return []
        with self._lock:
            return [
                session
                for session_id, session in self._sessions.items()
                if session.owner == owner
                and not _is_reserved_browser_id(session_id)
                and session.is_alive()
            ]

    def resolve_owned(self, owner: str) -> BrowserSession:
        """按归属解析当前会话的浏览器实例；0 个或多个都抛可读错误。"""
        sessions = self.owned_sessions(owner)
        if len(sessions) == 1:
            sessions[0].touch()
            return sessions[0]
        if len(sessions) > 1:
            raise BrowserCDPError(
                "当前会话有多个浏览器实例在运行：请在 browser_* 调用中传 browser_id 指定"
            )
        raise BrowserCDPError(
            "当前会话还没有浏览器实例——先调用 browser_launch（browser_navigate 会自动拉起）"
        )

    def require(self, browser_id: Optional[str], owner: str = "") -> BrowserSession:
        """解析并校验会话归属（``owner`` 非空时）。

        缺省解析（``browser_id`` 为空）在归属模式下按“本会话自有实例 → 用户
        共享标签页”顺序进行，绝不回退到其他会话的实例；显式 id 属于其他会话
        时直接拒绝（EXTERNAL 共享标签页除外）。``owner == ""`` 保持旧语义。
        """
        if browser_id:
            session = self.get(browser_id)
            if session is None:
                raise BrowserCDPError(f"未知 browser_id: {browser_id}")
            if (
                owner
                and session.owner
                and session.owner != owner
                and getattr(session, "browser_type", None) != BrowserType.EXTERNAL
            ):
                raise BrowserCDPError(
                    "该浏览器实例属于另一个会话，不能跨会话操作；"
                    "请用 browser_launch 启动本会话自己的实例"
                )
        elif owner:
            owned = self.owned_sessions(owner)
            if len(owned) == 1:
                session = owned[0]
            elif len(owned) > 1:
                raise BrowserCDPError(
                    "当前会话有多个浏览器实例在运行：请在 browser_* 调用中传 browser_id 指定"
                )
            else:
                with self._lock:
                    session = self._sessions.get(EXTENSION_BROWSER_ID)
                if session is None:
                    raise BrowserCDPError(
                        "当前会话没有运行中的浏览器实例——先调用 browser_launch"
                        "（browser_navigate 会自动拉起）"
                    )
        else:
            session = self.get(None)
        if session is None:
            if browser_id:
                raise BrowserCDPError(f"未知 browser_id: {browser_id}")
            raise BrowserCDPError(
                "没有运行中的浏览器实例（可多实例时必须传 browser_id）——先调用 browser_launch"
            )
        if not session.is_alive():
            with self._lock:
                self._sessions.pop(session.browser_id, None)
            # 进程已自行退出（崩溃/用户关窗）：terminate 部分幂等跳过，
            # 重点是回收其一次性目录，否则永久遗留。
            _terminate_session(session)
            raise BrowserCDPError("浏览器进程已退出（可能被用户关闭）——请重新 browser_launch")
        # LRU 顺序：每次真实访问都刷新最后使用时间。
        session.touch()
        return session

    # ------------------------------------------------------------------
    # 租约：工具执行期间阻止上限/LRU 淘汰杀掉正在使用的实例
    # ------------------------------------------------------------------

    def acquire_lease(self, session: BrowserSession) -> None:
        """登记一次工具执行租约（线程安全；已移除会话也允许计数，释放幂等）。"""
        with self._lock:
            session.lease_count += 1
            session.touch()

    def release_lease(self, session: BrowserSession) -> None:
        """释放一次工具执行租约（计数不低于 0，任何异常都不上抛）。"""
        with self._lock:
            if session.lease_count > 0:
                session.lease_count -= 1
            session.touch()

    def remove(self, browser_id: str) -> Optional[BrowserSession]:
        with self._lock:
            return self._sessions.pop(browser_id, None)

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def all_sessions(self) -> List[BrowserSession]:
        """返回全部会话的副本列表（控制面列举用，遍历期间持锁）。"""
        with self._lock:
            return list(self._sessions.values())

    def close_all(self) -> int:
        """关闭全部实例（后端退出钩子）；返回关闭数。"""
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            _terminate_session(session)
        return len(sessions)

    def _evict_lru_locked(self) -> Optional[BrowserSession]:
        """LRU 回收：关闭最久未使用的实例（调用方必须持有 self._lock）。

        跳过：
        - EXTENSION_BROWSER_ID（用户日常浏览器）
        - EMBEDDED 类型（共享 Electron 进程）
        - RESERVED_BROWSER_ID 及其前缀（渲染池，由 register 单独处理）

        返回被回收的会话（供调用方加入 evicted 列表）；无可回收时返回 None。
        """
        candidates = [
            (sid, s)
            for sid, s in self._sessions.items()
            if s.is_alive()
            and not s.is_leased()
            and sid != EXTENSION_BROWSER_ID
            and getattr(s, "browser_type", None) != BrowserType.EMBEDDED
            and sid != RESERVED_BROWSER_ID
            and not sid.startswith(RESERVED_BROWSER_ID + "-")
        ]
        if not candidates:
            return None

        # 按 last_used_at 升序（最早的在前）
        def parse_time(session: BrowserSession) -> str:
            return session.last_used_at or "1970-01-01T00:00:00+00:00"

        oldest_id, oldest = min(candidates, key=lambda x: parse_time(x[1]))
        self._sessions.pop(oldest_id, None)
        logger.info(
            "LRU 回收浏览器会话: %s (name=%s, last_used=%s)",
            oldest_id,
            oldest.name or "(unnamed)",
            oldest.last_used_at,
        )
        return oldest

    def update_session_name(self, browser_id: str, name: str) -> bool:
        """设置会话名称（P2 功能）。返回是否成功。"""
        with self._lock:
            session = self._sessions.get(browser_id)
            if session is None:
                return False
            session.name = name
            return True

    def touch_session(self, browser_id: str) -> None:
        """更新会话最后使用时间（访问时调用，影响 LRU 顺序）。"""
        with self._lock:
            session = self._sessions.get(browser_id)
            if session is not None:
                session.touch()

    def get_status(self) -> Dict[str, Any]:
        """返回浏览器状态摘要（P1 状态栏用）。"""
        with self._lock:
            active = sum(
                1
                for s in self._sessions.values()
                if s.is_alive()
                and getattr(s, "browser_type", None)
                not in (BrowserType.EMBEDDED, BrowserType.EXTERNAL)
                and s.browser_id != RESERVED_BROWSER_ID
                and not s.browser_id.startswith(RESERVED_BROWSER_ID + "-")
            )
            sessions = [
                {
                    "id": s.browser_id,
                    "name": s.name,
                    "last_used_at": s.last_used_at,
                    "alive": s.is_alive(),
                    "persistent": s.persistent,
                    "profile_name": s.profile_name,
                    "owner": s.owner,
                    "busy": s.is_leased(),
                }
                for s in self._sessions.values()
                # 内部渲染池槽位（web_fetch 懒重建）不是用户会话，面板不展示。
                if s.browser_id != RESERVED_BROWSER_ID
                and not s.browser_id.startswith(RESERVED_BROWSER_ID + "-")
            ]
        return {
            "active": active,
            "max": get_max_sessions(),
            "lruEvict": get_lru_evict_enabled(),
            "sessions": sessions,
        }


def _terminate_session(session: BrowserSession) -> None:
    """终止浏览器进程 + 尽力清理临时目录（任何失败静默记日志）。

    持久 profile（session.persistent）只关进程不删目录 —— 登录态跨会话
    保留的前提；启动失败路径同样经由本函数，持久目录即使启动失败也不删
    （里面可能有用户既有登录态）。

    Embedded 会话的生命周期归 Electron 主进程：这里关闭本会话的目标后返回。
    External 会话是用户自己的标签页：Sage 只丢弃会话引用，绝不关闭页面。
    """
    _release_profile(session.user_data_dir, session.browser_id)
    if getattr(session, "browser_type", None) == BrowserType.EXTERNAL:
        return
    if getattr(session, "browser_type", None) == BrowserType.EMBEDDED:
        try:
            targets = _embedded_command(session, "Target.getTargets", {})
            for info in targets.get("targetInfos") or []:
                target_id = str(info.get("targetId") or "")
                if target_id:
                    _embedded_command(
                        session, "Target.closeTarget", {"targetId": target_id}
                    )
        except Exception:  # noqa: BLE001 — 关闭失败不阻断会话回收
            logger.debug("关闭内置浏览器目标失败", exc_info=True)
        return
    # SN3：先停事件通道（常驻 WS 线程），再杀进程
    try:
        from .browser_events import stop_download_tracking

        if session.browser_id:
            stop_download_tracking(session.browser_id)
    except Exception:  # noqa: BLE001 — 事件通道清理失败不阻断终止
        logger.debug("停止下载事件通道失败", exc_info=True)
    # R26：Windows 先在父进程存活时强杀整棵树 —— renderer/gpu/crashpad 等
    # 子进程仍持有 user_data_dir 句柄，若先 terminate，父退出后子进程被
    # 重派生（reparent），taskkill /T 找不到树，孤儿进程锁目录（实测单测
    # 跑一轮泄漏一棵进程树）。非 Windows 本函数为 no-op，走下方优雅终止。
    _kill_process_tree(session.process)
    try:
        session.process.terminate()
        try:
            session.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            session.process.kill()
    except OSError as exc:
        logger.warning("browser terminate 失败: %s", exc)
    # R46：树杀仍可能漏掉重派生的 crashpad-handler 等孤儿——按 profile
    # 路径精确清扫残留进程，避免临时目录被锁（实测单测跑一轮泄漏一棵树）。
    _kill_profile_stragglers(session.user_data_dir)
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


def _kill_profile_stragglers(user_data_dir: str) -> None:
    """Windows：按 profile 目录清扫脱离进程树的残留进程（R46）。

    crashpad-handler 等子进程在浏览器关闭过程会被系统重派生（脱离父子
    链），taskkill /T 按父 PID 遍历不到它们——实测每轮全量单测泄漏一棵
    进程树并锁住临时目录。此清扫按命令行中的 profile 路径精确匹配兜底。
    POSIX 上无此问题，不启用。
    """
    if os.name != "nt":
        return
    ps = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.CommandLine -ne $null -and "
        "$_.CommandLine -match [regex]::Escape('__UDD__') } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
        "-ErrorAction SilentlyContinue }"
    ).replace("__UDD__", user_data_dir)
    try:
        subprocess.run(  # noqa: S603 — powershell 为系统命令
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        logger.debug("profile 残留清扫失败（忽略）: %s", user_data_dir, exc_info=True)


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


# ---------------------------------------------------------------------------
# 持久 profile 占用互斥（按聊天会话归属启动的实例才启用）
# ---------------------------------------------------------------------------

#: 持久 profile 目录 → 占用它的 browser_id（进程内；进程退出即失效）
_profile_owners: Dict[str, str] = {}
_profile_owners_lock = threading.Lock()


def _claim_profile(profile_dir: str, browser_id: str, allow_suffix: bool = False) -> str:
    """登记持久 profile 占用；返回最终使用的目录（隐式 default 可自动后缀）。

    Chromium 不允许两个进程同时使用同一个 user-data-dir。同会话复用同 id
    视为幂等；其他 browser_id 占用时：
    - ``allow_suffix=True``（隐式默认 profile）：依次尝试 ``<dir>-2..-10``；
    - ``allow_suffix=False``（用户显式命名）：抛可读错误。
    """
    candidate = profile_dir
    for attempt in range(10):
        with _profile_owners_lock:
            holder = _profile_owners.get(candidate)
            if holder is None or holder == browser_id:
                _profile_owners[candidate] = browser_id
                return candidate
        if not allow_suffix:
            raise BrowserCDPError(
                f"持久 profile「{os.path.basename(profile_dir)}」正被另一个浏览器会话"
                "使用：请换一个 profile_name，或等待其关闭后重试"
            )
        candidate = f"{profile_dir}-{attempt + 2}"
    raise BrowserCDPError(
        f"持久 profile「{os.path.basename(profile_dir)}」占用过多（-2..-10 均已使用）"
    )


def _release_profile(profile_dir: str, browser_id: str) -> None:
    """释放持久 profile 占用（仅当占用者仍是该 browser_id）。"""
    if not profile_dir:
        return
    with _profile_owners_lock:
        if _profile_owners.get(profile_dir) == browser_id:
            _profile_owners.pop(profile_dir, None)


def _assert_firefox_single_instance(browser_id: str) -> None:
    """Firefox 调试端口固定 9229：已有存活 Firefox 实例时拒绝再启动。"""
    for session in get_browser_manager().all_sessions():
        if getattr(session, "browser_type", None) != BrowserType.FIREFOX:
            continue
        if session.browser_id == browser_id or not session.is_alive():
            continue
        raise BrowserCDPError(
            "同一时刻只能有一个 Firefox 调试实例（调试端口固定 9229）："
            "请先关闭正在运行的 Firefox 浏览器后重试"
        )


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

    Chromium 用 ``--remote-debugging-port=0`` 随机端口 + ``--user-data-dir``；
    Firefox 没有对应开关，用 ``-start-debugger-server <固定端口>`` +
    ``-profile`` + ``-no-remote``。Firefox v1 不支持 ``proxy_flag``
    （命令行无法覆盖代理，需要写 profile prefs，超出最小兼容层范围）。

    ``proxy_flag`` 非空时追加 ``--proxy-server=``（用户级代理配置，见
    http_factory.browser_proxy_flag）——否则浏览器通道绕过代理，代理用户
    经 headless 渲染访问被墙站点依旧不通。
    """
    if _infer_browser_type(executable) == BrowserType.FIREFOX:
        command = [
            executable,
            "-start-debugger-server",
            str(FIREFOX_CDP_PORT),
            "-profile",
            user_data_dir,
            "-no-remote",
        ]
        command.append("about:blank")
        if headless:
            command.insert(1, "-headless")
        return command
    command = [
        executable,
        "--remote-debugging-port=0",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-background-networking",
        "--window-size=1440,900",
        # R46：禁用 crashpad/breakpad —— crashpad-handler 子进程在 Windows
        # 上会脱离进程树存活（taskkill /T 遍历不到），持锁 user_data_dir
        # 导致临时目录删不掉（总账 §4 实证）。无头自动化浏览器不需要
        # 崩溃上报。
        "--disable-crashpad",
        "--disable-breakpad",
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
        # Chrome 109+ 才支持 new headless；旧内核（Win7 的 Edge 100 /
        # Chrome 107）由 headless_flag 降级为旧无头模式
        command.insert(1, headless_flag(executable))
    return command


def _wait_for_firefox_cdp(process: subprocess.Popen, deadline: float) -> Tuple[int, str]:
    """轮询 Firefox 的 ``/json/version`` 完成 CDP 握手。

    Firefox 不写 ``DevToolsActivePort`` 文件；固定端口上暴露 HTTP
    ``/json/version``，从中解析 ``webSocketDebuggerUrl`` 得到 browser
    端 WS 路径（可能带 query）。Firefox 的调试端点要求非空 User-Agent。
    """
    url = f"http://127.0.0.1:{FIREFOX_CDP_PORT}/json/version"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise BrowserCDPError(
                f"Firefox 进程提前退出（退出码 {process.returncode}）——可尝试 headless=false 排查"
            )
        try:
            request = urllib.request.Request(  # noqa: S310 — 仅回环地址
                url, headers={"User-Agent": "Sage-Diagnostic"}
            )
            with urllib.request.urlopen(request, timeout=1.0) as response:  # noqa: S310
                if response.getcode() == 200:
                    payload = json.loads(response.read().decode("utf-8"))
                    ws_url = str(payload.get("webSocketDebuggerUrl") or "")
                    if ws_url:
                        parsed = urlparse(ws_url)
                        ws_path = parsed.path
                        if parsed.query:
                            ws_path += "?" + parsed.query
                        if ws_path.startswith("/devtools/"):
                            return FIREFOX_CDP_PORT, ws_path
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(_FIREFOX_POLL_INTERVAL)
    raise BrowserCDPError(
        f"等待 Firefox CDP 接口超时（{LAUNCH_TIMEOUT_SECONDS:.0f} 秒，"
        f"端口 {FIREFOX_CDP_PORT}）——浏览器可能未完成启动"
    )


class _EmbeddedProcess:
    """占位的子进程接口：内置浏览器由 Electron 管理，无本进程句柄。"""

    pid = 0

    def poll(self) -> Optional[int]:
        return None  # 只要 Electron 存活，会话即视为存活

    def terminate(self) -> None:
        return None

    def kill(self) -> None:
        return None

    def wait(self, timeout: Optional[float] = None) -> int:
        return 0


def _register_or_release(session: BrowserSession) -> None:
    """注册会话；失败时终止进程并释放已占用的持久 profile，避免泄漏。"""
    try:
        get_browser_manager().register(session)
    except Exception:
        _terminate_session(session)
        raise


def launch_browser(
    headless: bool = True,
    browser_id: Optional[str] = None,
    persistent: bool = False,
    profile_name: Optional[str] = None,
    owner: str = "",
) -> BrowserSession:
    """启动浏览器实例并完成 DevToolsActivePort 握手。

    Args:
        headless:     无头模式（web_fetch 渲染池恒为 True）。
        browser_id:   显式指定会话 id（web_fetch 渲染池传保留 id
                      RESERVED_BROWSER_ID）；缺省生成随机 id。
        persistent:   使用持久 profile（``_profiles_root()/<profile_name>``，
                      登录态跨会话保留）；False = 一次性临时目录。
        profile_name: 持久 profile 目录名（净化为安全 basename）；None =
                      隐式默认（``default``，被其他会话占用时自动后缀）。
        owner:        启动该实例的聊天会话 id。非空时启用持久 profile 占用
                      互斥；"" 表示无归属调用方（基础设施/旧路径），保持
                      原行为。

    Raises:
        BrowserCDPError: 找不到浏览器 / 启动超时 / 实例数超限 /
            profile 被其他会话占用 / Firefox 已有实例。
    """
    # 设置页选择的浏览器优先于 Win7 内置兜底；显式环境变量仍最高（见 discover_and_select）
    cap = discover_and_select(_get_user_browser_path())
    if not cap:
        raise BrowserCDPError(
            "未找到 Chrome/Edge/Firefox 浏览器：请安装或用环境变量 SAGE_BROWSER_PATH / SAGE_FIREFOX_PATH 指定可执行文件路径"
        )
    session_id = browser_id or uuid.uuid4().hex[:12]
    if cap.browser_type == BrowserType.EMBEDDED:
        bridge_token = getattr(cap.launcher, "token", "")
        bridge_query = (
            f"token={quote(bridge_token, safe='')}"
            f"&session={quote(session_id, safe='')}"
            f"&headless={'1' if headless else '0'}"
        )
        session = BrowserSession(
            browser_id=session_id,
            executable=EMBEDDED_EXECUTABLE,
            headless=headless,
            user_data_dir="",
            process=_EmbeddedProcess(),
            port=cap.cdp_port,
            ws_path=f"/devtools/browser/embedded?{bridge_query}",
            persistent=True,
            profile_name="embedded",
            browser_type=BrowserType.EMBEDDED,
            bridge_token=bridge_token,
            owner=owner,
        )
        _register_or_release(session)
        return session
    executable = cap.executable
    if not executable or not Path(executable).is_file():
        raise BrowserCDPError(
            "未找到 Chrome/Edge/Firefox 浏览器：请安装或用环境变量 SAGE_BROWSER_PATH / SAGE_FIREFOX_PATH 指定可执行文件路径"
        )
    launcher = cap.launcher

    browser_type = cap.browser_type
    if browser_type == BrowserType.FIREFOX:
        _assert_firefox_single_instance(session_id)

    profile_claimed = False
    if persistent:
        from .download_tool import sanitize_filename

        base_name = profile_name or "default"
        profile_dir = _profiles_root() / sanitize_filename(base_name)
        if owner:
            # 归属启动：同一 profile 不允许被两个会话同时打开；隐式默认名
            # 被占用时自动后缀，显式命名直接报错。
            user_data_dir = _claim_profile(
                str(profile_dir), session_id, allow_suffix=profile_name is None
            )
            profile_claimed = True
        else:
            user_data_dir = str(profile_dir)
        Path(user_data_dir).mkdir(parents=True, exist_ok=True)
    else:
        user_data_dir = tempfile.mkdtemp(prefix=EPHEMERAL_PREFIX, dir=str(_ephemeral_root()))
    from .http_factory import browser_proxy_flag

    command = launcher.build_command(executable, headless, user_data_dir, browser_proxy_flag())

    try:
        process = subprocess.Popen(  # noqa: S603 — 可执行文件来自受控发现逻辑
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
    except OSError as exc:
        if profile_claimed:
            _release_profile(user_data_dir, session_id)
        if not persistent:
            _remove_dir_with_retry(user_data_dir)
        raise BrowserCDPError(f"浏览器启动失败: {exc}")

    try:
        port, ws_path = launcher.wait_for_cdp(process, user_data_dir, timeout=LAUNCH_TIMEOUT_SECONDS)
        session = BrowserSession(
            browser_id=session_id,
            executable=executable,
            headless=headless,
            user_data_dir=user_data_dir,
            process=process,
            port=port,
            ws_path=ws_path,
            persistent=persistent,
            profile_name=Path(user_data_dir).name if persistent else "",
            browser_type=cap.browser_type,
            owner=owner,
        )
        _register_or_release(session)
        return session
    except Exception as exc:
        # 提前退出/握手异常统一走 _terminate_session：其中已含杀进程树 +
        # 一次性目录带重试的回收（main 线 2a44025d 语义在此结构下的落点）。
        # browser_id 用本次 session_id：_terminate_session 据此释放持久 profile 占用。
        _terminate_session(
            BrowserSession(
                session_id,
                executable,
                headless,
                user_data_dir,
                process,
                0,
                "",
                persistent=persistent,
                browser_type=cap.browser_type,
            )
        )
        raise BrowserCDPError(f"浏览器启动握手失败: {exc}") from exc


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
    if getattr(session, "browser_type", None) == BrowserType.EXTERNAL:
        result = _external_command(session, "Target.getTargets", {})
        return [info for info in result.get("targetInfos", []) if info.get("type") == "page"]
    connection = _CDPConnection(session)
    try:
        result = connection.command("Target.getTargets")
    finally:
        connection.close()
    return [info for info in result.get("targetInfos", []) if info.get("type") == "page"]


def ensure_page_target(session: BrowserSession, target_id: Optional[str] = None) -> str:
    """解析可用页面目标；无页面 / 指定目标不存在时新建 about:blank 页。

    ``target_id`` 缺省时优先沿用 ``session.active_target_id``（由
    ``browser_tabs`` 的 switch/create 维护）；该目标已消失则清空跟踪并
    回退到第一个页面。不使用 ``Target.activateTarget`` —— Electron 内置
    浏览器桥不实现该方法。
    """
    pages = _list_page_targets(session)
    if target_id:
        if any(info.get("targetId") == target_id for info in pages):
            return target_id
        raise BrowserCDPError(f"未知 target_id: {target_id}")
    active_target_id = getattr(session, "active_target_id", None)
    if active_target_id:
        if any(info.get("targetId") == active_target_id for info in pages):
            return active_target_id
        # 跟踪的标签页已被关闭：清空并回退到默认解析
        session.active_target_id = None
    if pages:
        return pages[0]["targetId"]
    if getattr(session, "browser_type", None) == BrowserType.EXTERNAL:
        # 用户共享的标签页已关闭 / 尚未就绪；不替用户新建标签页。
        raise BrowserCDPError("共享的浏览器标签页不可用——请重新在扩展中共享标签页")
    connection = _CDPConnection(session)
    try:
        result = connection.command("Target.createTarget", {"url": "about:blank"})
    finally:
        connection.close()
    created = result.get("targetId")
    if not created:
        raise BrowserCDPError("创建页面目标失败")
    return created


def _embedded_command(
    session: BrowserSession,
    method: str,
    params: Optional[Dict[str, Any]] = None,
    target_id: Optional[str] = None,
    headless_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """把 CDP 命令转发到 Electron 主进程的内置浏览器 HTTP 桥。"""
    payload = json.dumps(
        {
            "method": method,
            "params": params or {},
            "targetId": target_id or "",
            "session": session.browser_id,
            "headless": (
                bool(headless_override)
                if headless_override is not None
                else bool(session.headless)
            ),
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{session.port}/command",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Sage-Bridge-Token": session.bridge_token,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=CDP_TIMEOUT_SECONDS + 10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise BrowserCDPError(f"内置浏览器桥不可用: {exc}") from exc
    if isinstance(data, dict) and data.get("error"):
        message = (data.get("error") or {}).get("message", "unknown")
        raise BrowserCDPError(f"CDP 错误 ({method}): {message}")
    return (data.get("result") if isinstance(data, dict) else None) or {}


def _external_command(
    session: BrowserSession,
    method: str,
    params: Optional[Dict[str, Any]] = None,
    target_id: Optional[str] = None,
) -> Dict[str, Any]:
    """把 CDP 命令转发到用户日常浏览器的扩展桥（长轮询 + chrome.debugger）。"""
    from backend.services.browser_extension_bridge import (
        BrowserExtensionError,
        browser_extension_bridge,
    )

    try:
        return browser_extension_bridge.execute_cdp(method, params, target_id)
    except BrowserExtensionError as exc:
        raise BrowserCDPError(f"浏览器扩展桥: {exc}") from exc


def cdp_command(
    session: BrowserSession,
    method: str,
    params: Optional[Dict[str, Any]] = None,
    target_id: Optional[str] = None,
) -> Dict[str, Any]:
    """向指定页面目标发送一条 CDP 命令并返回 result。

    一次调用 = 一条短连接（attach → command → close）。页面级方法
    自动带 sessionId；浏览器级方法（Target.*）不带。
    Embedded 会话经 Electron 主进程 HTTP 桥执行，External 会话经用户
    日常浏览器扩展桥执行，协议语义保持一致。
    """
    if getattr(session, "browser_type", None) == BrowserType.EXTERNAL:
        return _external_command(session, method, params, target_id)
    if getattr(session, "browser_type", None) == BrowserType.EMBEDDED:
        return _embedded_command(session, method, params, target_id)
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
    "BrowserCapability",
    "BrowserLauncher",
    "BrowserSession",
    "BrowserSessionManager",
    "BrowserType",
    "CdpEventPump",
    "CDP_TIMEOUT_SECONDS",
    "ChromeLauncher",
    "EPHEMERAL_PREFIX",
    "FirefoxLauncher",
    "LAUNCH_TIMEOUT_SECONDS",
    "MAX_BROWSER_SESSIONS",
    "RESERVED_BROWSER_ID",
    "STEALTH_SCRIPT",
    "SWEEP_MAX_AGE_SECONDS",
    "apply_stealth",
    "browser_downloads_root",
    "cdp_command",
    "discover_and_select",
    "discover_browser_executable",
    "ensure_page_target",
    "get_browser_manager",
    "launch_browser",
    "sweep_stale_browser_dirs",
]
