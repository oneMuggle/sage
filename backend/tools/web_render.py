"""web_fetch JS 渲染降级 + 页面就绪等待（docs/plans/2026-09-06_web-dynamic-render-access.md W1/W2）。

web_fetch 静态抽取命中"JS 壳"特征（SPA 空根挂载点 / script 占比过高）时，
经 G7 的 CDP 基建（browser_cdp / browser_ws）驱动专用 headless 渲染实例
取渲染后正文：

- **实例池**：进程级懒初始化多槽渲染实例（保留 id ``RENDER_POOL_IDS``，
  BrowserSessionManager 的"唯一实例"解析跳过它，不干扰用户 browser_launch
  的实例），空闲超时或进程死亡时自动重建；每次渲染用独立标签页，并发
  渲染互不干扰；
- **门禁**：与静态分支同口径 —— 导航前置 ``check_host``；OFFLINE 模式
  web_fetch 本就不注册，此处兜底拦截；
- **审批语义**：渲染内部的浏览器启动不单独走 EXEC 审批，由 web_fetch 的
  EXTERNAL 门禁覆盖（方案 §6）；浏览器内重定向无法逐跳 check_host，
  与既有 browser_* 工具同等风险口径，明示接受。

py3.8 纪律：from __future__ import annotations + typing.*（win7 对齐）。
"""

from __future__ import annotations

import contextlib
import json
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from .browser_cdp import (
    RESERVED_BROWSER_ID,
    BrowserCDPError,
    BrowserSession,
    apply_stealth,
    cdp_command,
    get_browser_manager,
    launch_browser,
)
from .browser_events import (
    detach_network_session,
    ensure_network_tracking,
    get_tracked_response,
    start_event_channel,
)
from .web_metrics import record_render_event

#: 渲染实例的保留 browser_id（web_fetch 专用，用户不可见）
RENDER_POOL_ID = RESERVED_BROWSER_ID

#: 渲染池默认槽位数与各槽 browser_id（R24 多实例：槽 1 沿用既有保留 id）。
#: 槽 2+ 必须落在 ``render-pool-`` 前缀内——browser_cdp.get(None) 的"用户
#: 实例"解析按该前缀排除，否则多槽会破坏单用户浏览器免传 id 的便利解析。
#: R25：实际槽位数可经 ``web_access_config.render_pool_size`` 配置（钳
#: RENDER_POOL_SIZE_MIN..MAX，默认仍是常量值）。
RENDER_POOL_SIZE = 2
RENDER_POOL_SIZE_MIN = 1
RENDER_POOL_SIZE_MAX = 4


def _render_pool_ids(size: int) -> tuple:
    """按槽位数生成保留 browser_id 元组（槽 1 无后缀，槽 2+ ``-n`` 后缀）。"""
    return (RENDER_POOL_ID,) + tuple(f"{RENDER_POOL_ID}-{i}" for i in range(2, size + 1))


RENDER_POOL_IDS = _render_pool_ids(RENDER_POOL_SIZE)


def _render_pool_size() -> int:
    """读 ``web_access_config.render_pool_size``（R25）；钳位/异常回退默认值。"""
    try:
        import json

        from backend.data.settings_repo import SettingsRepository

        raw = SettingsRepository().get(SETTINGS_KEY_WEB_ACCESS_CONFIG)
        if not raw:
            return RENDER_POOL_SIZE
        parsed = json.loads(raw)
        value = int(parsed.get("render_pool_size", RENDER_POOL_SIZE))
        return max(RENDER_POOL_SIZE_MIN, min(RENDER_POOL_SIZE_MAX, value))
    except Exception:  # noqa: BLE001 — 配置失败按默认处理（保持现状行为）
        return RENDER_POOL_SIZE

#: 渲染正文上限（字符，对齐 browser_tool.SNAPSHOT_TEXT_CAP）
RENDER_TEXT_CAP = 30 * 1024

#: 渲染后 outerHTML 抽取上限（字节）——喂给 html_extract 产出 links/tables（R1）
RENDER_HTML_CAP = 512 * 1024

#: readyState 就绪轮询窗口（navigate 后等待上限）
READY_TIMEOUT_SECONDS = 10.0

#: readyState 轮询间隔
_READY_POLL_INTERVAL = 0.3

#: readyState 达标后的正文稳定窗口上限（覆盖 SPA hydrate）
_SETTLE_MAX_SECONDS = 3.0

#: 正文长度稳定轮询间隔
_SETTLE_POLL_INTERVAL = 0.4

#: 判定"正文已稳定"所需的连续相同读数轮数
_SETTLE_STABLE_ROUNDS = 2

#: 懒加载触底滚动的最大轮数（R3）
_LAZY_SCROLL_MAX_ROUNDS = 3

#: 懒加载判定"到底了"所需的连续相同 scrollHeight 轮数
_LAZY_SCROLL_STABLE_ROUNDS = 2

#: 懒加载滚动轮间等待
_LAZY_SCROLL_PAUSE_SECONDS = 0.4

#: 渲染实例空闲回收（秒）：超时后下次 acquire 重建，避免常驻占用
RENDER_IDLE_TIMEOUT_SECONDS = 300.0

#: 渲染池持久 profile 的保留目录名（web_access_config.render_persistent 开启时用）
RENDER_PROFILE_NAME = "render-default"

#: AU3 自动刷新专用保留 browser_id（launch 后立即移出会话表，非用户实例）
REFRESH_POOL_ID = "refresh-pool"

#: preferences 表的 key（web_access_config，需在 SettingsRepository.KEYS 白名单内）
SETTINGS_KEY_WEB_ACCESS_CONFIG = "web_access_config"


def _auto_refresh_enabled() -> bool:
    """读 ``web_access_config.auto_refresh_credentials``（AU3，默认关）。

    开启后：带凭据请求被踢到登录页时，若档案记录了来源持久 profile
    （AU6），用该 profile 静默重导 cookie 并重放一次请求。
    """
    try:
        import json

        from backend.data.settings_repo import SettingsRepository

        raw = SettingsRepository().get(SETTINGS_KEY_WEB_ACCESS_CONFIG)
        if not raw:
            return False
        parsed = json.loads(raw)
        return bool(isinstance(parsed, dict) and parsed.get("auto_refresh_credentials"))
    except Exception:  # noqa: BLE001 — 配置失败按关闭处理
        return False


def _render_persistent_enabled() -> bool:
    """读 ``web_access_config.render_persistent``；任何失败回退 False。

    开启后渲染实例用持久 profile —— 需要登录态的 SPA（订阅源文献页）经
    web_fetch 自动渲染即可读到登录后内容。空闲重建与持久 profile 兼容：
    重建后 cookie 从磁盘 profile 重载。
    """
    try:
        import json

        from backend.data.settings_repo import SettingsRepository

        raw = SettingsRepository().get(SETTINGS_KEY_WEB_ACCESS_CONFIG)
        if not raw:
            return False
        parsed = json.loads(raw)
        return bool(isinstance(parsed, dict) and parsed.get("render_persistent"))
    except Exception:  # noqa: BLE001 — 配置失败按关闭处理（保持现状行为）
        return False


# ---------------------------------------------------------------------------
# JS 壳判定（auto 模式，纯函数）
# ---------------------------------------------------------------------------

#: 静态抽取正文低于该长度才可疑（正文足够长说明内容已渲染）
SHELL_TEXT_MIN_CHARS = 500

#: script 标签字节占比超过该值视为"脚本壳"
SHELL_SCRIPT_RATIO = 0.25

#: 常见 SPA 根挂载点（div id=root/app/__next/__nuxt）
_ROOT_MOUNT_RE = re.compile(
    r"<div[^>]+\bid=[\"']?(?:root|app|__next|__nuxt)[\"']?[^>]*>",
    re.IGNORECASE,
)

#: script 块（含内容）—— 占比按字符数估算
_SCRIPT_RE = re.compile(r"<script\b.*?</script>", re.IGNORECASE | re.DOTALL)


def looks_like_js_shell(html: str, extracted_text: str) -> bool:
    """判定静态 HTML 是否为 SPA 壳：正文过短且（script 占比高 或 有根挂载点）。

    三个条件独立成立的静态小页面（无脚本、无挂载点）不会命中 —— 静态站
    零开销不回退。
    """
    if not html:
        return False
    if len((extracted_text or "").strip()) >= SHELL_TEXT_MIN_CHARS:
        return False
    script_chars = sum(len(match) for match in _SCRIPT_RE.findall(html))
    if script_chars / len(html) > SHELL_SCRIPT_RATIO:
        return True
    return bool(_ROOT_MOUNT_RE.search(html))


class RenderError(RuntimeError):
    """JS 渲染失败（门禁拒绝 / 浏览器不可用 / 导航失败 / 页面读取异常）。"""


# ---------------------------------------------------------------------------
# 页面就绪等待（W2）—— browser_navigate 与渲染分支共用
# ---------------------------------------------------------------------------


def wait_page_ready(session: BrowserSession, target_id: Optional[str], wait_for: str = "") -> None:
    """navigate 后等页面可用：readyState 达标 → (可选)等 wait_for → 正文稳定。

    SPA 的 hydrate 发生在 readyState=complete 之后，只等 readyState 会拿到
    半空页面 —— 达标后再等 innerText 长度连续 ``_SETTLE_STABLE_ROUNDS`` 轮
    不变（上限 ``_SETTLE_MAX_SECONDS``）。

    ``wait_for``（R2）为 CSS 选择器：readyState 达标后轮询其出现，上限
    READY_TIMEOUT_SECONDS；超时不失败（半截内容好过没有），继续走 settle。

    BrowserCDPError（导航引发的上下文销毁）直接返回 —— 交给后续调用自查。
    """
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            state = _evaluate_json(session, "document.readyState", target_id)
        except BrowserCDPError:
            return
        if state in ("complete", "interactive"):
            break
        time.sleep(_READY_POLL_INTERVAL)

    if wait_for.strip():
        selector = json.dumps(wait_for.strip())
        deadline = time.monotonic() + READY_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            try:
                found = _evaluate_json(session, f"!!document.querySelector({selector})", target_id)
            except BrowserCDPError:
                return
            if found:
                break
            time.sleep(_READY_POLL_INTERVAL)

    settle_deadline = time.monotonic() + _SETTLE_MAX_SECONDS
    last_length = -1
    stable_rounds = 0
    while time.monotonic() < settle_deadline:
        try:
            length = _evaluate_json(
                session,
                "(document.body && document.body.innerText || '').length",
                target_id,
            )
        except BrowserCDPError:
            return
        if isinstance(length, int) and length == last_length:
            stable_rounds += 1
            if stable_rounds >= _SETTLE_STABLE_ROUNDS:
                return
        else:
            stable_rounds = 0
        if isinstance(length, int):
            last_length = length
        time.sleep(_SETTLE_POLL_INTERVAL)


def _evaluate_json(session: BrowserSession, expression: str, target_id: Optional[str]) -> Any:
    """Runtime.evaluate（returnByValue）→ 解析 value；异常细节透出。"""
    result = cdp_command(
        session,
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True},
        target_id=target_id,
    )
    details = result.get("exceptionDetails")
    if details:
        raise BrowserCDPError(f"页面脚本执行失败: {json.dumps(details)[:300]}")
    return (result.get("result") or {}).get("value")


def _scroll_for_lazy_load(session: BrowserSession, target_id: Optional[str]) -> None:
    """触底滚动触发懒加载（R3）：最多 ``_LAZY_SCROLL_MAX_ROUNDS`` 轮，
    scrollHeight 连续 ``_LAZY_SCROLL_STABLE_ROUNDS`` 轮不变即提前结束。

    纯 Runtime.evaluate 实现（滚到底读 scrollHeight），兼容 CDP 短连接
    架构 —— 不依赖事件帧。滚动失败静默返回（不影响已渲染内容）。
    """
    expression = (
        "(function(){"
        "window.scrollTo(0,document.body?document.body.scrollHeight:0);"
        "return document.body?document.body.scrollHeight:0;"
        "})()"
    )
    last_height = -1
    stable_rounds = 0
    for _ in range(_LAZY_SCROLL_MAX_ROUNDS):
        try:
            height = _evaluate_json(session, expression, target_id)
        except BrowserCDPError:
            return
        if isinstance(height, int):
            if height == last_height:
                stable_rounds += 1
                if stable_rounds >= _LAZY_SCROLL_STABLE_ROUNDS:
                    return
            else:
                stable_rounds = 0
            last_height = height
        time.sleep(_LAZY_SCROLL_PAUSE_SECONDS)


# ---------------------------------------------------------------------------
# 渲染实例池与渲染入口
# ---------------------------------------------------------------------------


class _RendererPool:
    """进程级渲染实例池：多槽 LRU、懒启动、复用、空闲/死亡重建（线程安全）。

    工具在 executor 线程执行，懒初始化必须持锁；渲染本身（cdp_command 短
    连接 + 独立标签页）在锁外进行。R24 起多槽（``RENDER_POOL_IDS``）：acquire
    按 last_used LRU 选槽，并发渲染自然分散到不同浏览器实例——单实例崩溃
    不再波及全部 in-flight 渲染。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: Dict[str, Dict[str, Any]] = {
            bid: {"session": None, "last_used": 0.0} for bid in RENDER_POOL_IDS
        }

    def acquire(self) -> BrowserSession:
        with self._lock:
            # R25：配置的槽位数超过既有槽时懒增（缩小不回收已活实例，LRU
            # 自然少用）；新增槽 last_used=0 会被优先选中。
            for bid in _render_pool_ids(_render_pool_size()):
                if bid not in self._entries:
                    self._entries[bid] = {"session": None, "last_used": 0.0}
            # LRU 序试槽：最久未用的优先；某槽启动失败降级下一槽，全部
            # 失败才抛（部分实例不可用时渲染仍可用）。
            order = sorted(self._entries, key=lambda k: self._entries[k]["last_used"])
            last_error: Optional[BrowserCDPError] = None
            for bid in order:
                entry = self._entries[bid]
                session = entry["session"]
                if (
                    session is not None
                    and session.is_alive()
                    and time.monotonic() - entry["last_used"] <= RENDER_IDLE_TIMEOUT_SECONDS
                ):
                    entry["last_used"] = time.monotonic()
                    return session
                if session is not None:
                    self._discard(session)
                    entry["session"] = None
                try:
                    session = launch_browser(
                        headless=True,
                        browser_id=bid,
                        persistent=_render_persistent_enabled(),
                        profile_name=RENDER_PROFILE_NAME,
                    )
                except BrowserCDPError as exc:
                    last_error = exc
                    continue
                entry["session"] = session
                entry["last_used"] = time.monotonic()
                return session
            raise RenderError(f"渲染浏览器启动失败: {last_error}")

    @staticmethod
    def _discard(session: BrowserSession) -> None:
        from .browser_cdp import _terminate_session

        get_browser_manager().remove(session.browser_id)
        _terminate_session(session)

    def reset(self) -> None:
        """测试钩子：清空池状态（不触碰进程）。"""
        with self._lock:
            for entry in self._entries.values():
                entry["session"] = None
                entry["last_used"] = 0.0


_pool = _RendererPool()


def get_renderer_pool() -> _RendererPool:
    """渲染池单例访问（测试注入 / 后续生命周期管理用）。"""
    return _pool


def _ensure_pool_channel(session: Any) -> bool:
    """R23：为渲染池浏览器接常驻事件通道（尽力而为）。

    R22 批次 2 的事件状态依赖通道存在，而渲染池不经 browser_launch 工具，
    此前从未建通道——事件状态在生产渲染路径始终回退。通道建立/复用失败
    不影响渲染（返回 False，状态走 Navigation Timing 兜底）；幂等，池重建
    后经既有 ``stop_download_tracking`` 清理、下次渲染自动重连。
    """
    try:
        return start_event_channel(
            session.browser_id, session.port, session.ws_path
        )
    except Exception:  # noqa: BLE001 — 事件通道尽力而为，测试桩/异常会话静默跳过
        return False


def _writeback_render_cookies(
    session: Any,
    credential_domain: str,
    request_url: str,
    repo: Any = None,
) -> Optional[List[str]]:
    """AU5 回写：Storage.getCookies 按域取回渲染浏览器的 cookie，合并回档案。

    host 亲和与归属域守卫在 ``merge_cdp_cookies`` 内；这里只做域过滤与
    静默容错——回写是尽力而为，失败不抛（返回 None）。
    """
    from urllib.parse import urlparse

    from .credential_vault import cookie_domain_matches, merge_cdp_cookies

    try:
        result = cdp_command(session, "Storage.getCookies", {})
    except BrowserCDPError:
        return None
    all_cookies = result.get("cookies") or []
    host = (urlparse(request_url or "").hostname or "").lower()
    if not host:
        return None
    matched = [
        c
        for c in all_cookies
        if isinstance(c, dict) and cookie_domain_matches(host, str(c.get("domain") or ""))
    ]
    if not matched:
        return None
    try:
        changed = merge_cdp_cookies(credential_domain, matched, request_url, repo=repo)
    except Exception:  # noqa: BLE001 — 回写失败不影响本次请求
        return None
    return sorted(set(changed)) or None


def refresh_credentials(  # noqa: PLR0911 — 各失败路径独立 return，扁平更直读
    credential_domain: str,
    url: str,
    profile_name: str,
    repo: Any = None,
) -> Tuple[bool, List[str]]:
    """AU3：用来源持久 profile 静默重访 ``url``，把有效 cookie 重导回档案。

    流程：独立持久会话（保留 id ``REFRESH_POOL_ID``，注册后立即移出会话表，
    不干扰用户实例解析）→ 注入现有档案 cookie（remember-me 场景可直接续期）
    → 导航 → 登录墙页判定（密码框 + 正文极短）→ ``Storage.getCookies`` 按域
    ``merge_cdp_cookies`` 回写 → 关标签页并终止会话。

    Returns:
        (ok, refreshed_names)：ok=False 时 refreshed_names 为空；任何异常吞掉
        返回失败（调用方回退为原 ``login_required`` 报错，不改变失败语义）。
    """
    from urllib.parse import urlparse

    from .credential_vault import (
        KIND_COOKIE,
        cookie_domain_matches,
        looks_like_login_html,
        merge_cdp_cookies,
        resolve_credential,
    )

    credential_domain = (credential_domain or "").strip().lower()
    profile_name = (profile_name or "").strip()
    if not credential_domain or not profile_name:
        return False, []

    resolution = resolve_credential(credential_domain, url=url, repo=repo)
    inject = list(resolution.cookies) if resolution.ok and resolution.kind == KIND_COOKIE else []

    session: Optional[BrowserSession] = None
    target_id: Optional[str] = None
    try:
        session = launch_browser(
            headless=True,
            browser_id=REFRESH_POOL_ID,
            persistent=True,
            profile_name=profile_name,
        )
        get_browser_manager().remove(REFRESH_POOL_ID)  # 不进会话表：非用户实例
        created = cdp_command(session, "Target.createTarget", {"url": "about:blank"})
        target_id = created.get("targetId")
        if not target_id:
            return False, []
        if inject:
            from .credential_vault import normalize_cookie_for_cdp

            normalized_inject = [normalize_cookie_for_cdp(c) for c in inject]
            cdp_command(session, "Storage.setCookies", {"cookies": normalized_inject})
        apply_stealth(session, target_id, command=cdp_command)
        result = cdp_command(session, "Page.navigate", {"url": url}, target_id=target_id)
        if result.get("errorText"):
            return False, []
        wait_page_ready(session, target_id)
        expression = (
            "JSON.stringify({url:location.href,"
            "html:document.documentElement.outerHTML.slice(0,60000),"
            "text:(document.body&&document.body.innerText||'').slice(0,2000)})"
        )
        info = _evaluate_json(session, expression, target_id)
        page: Dict[str, Any] = {}
        if isinstance(info, str):
            try:
                page = json.loads(info)
            except ValueError:
                return False, []
        html = str(page.get("html") or "")
        text = str(page.get("text") or "")
        if looks_like_login_html(html) and len(text.strip()) < 500:
            return False, []  # profile 也未登录：刷新失败，回退原语义
        cookies_result = cdp_command(session, "Storage.getCookies", {})
        host = (urlparse(url or "").hostname or "").lower()
        if not host:
            return False, []
        matched = [
            c
            for c in (cookies_result.get("cookies") or [])
            if isinstance(c, dict)
            and cookie_domain_matches(host, str(c.get("domain") or ""))
        ]
        if not matched:
            return False, []
        changed = merge_cdp_cookies(credential_domain, matched, url, repo=repo)
        return (bool(changed), sorted(set(changed)))
    except BrowserCDPError:
        return False, []
    except Exception:  # noqa: BLE001 — 刷新失败不影响原报错语义
        return False, []
    finally:
        if target_id and session is not None:
            with contextlib.suppress(BrowserCDPError):
                cdp_command(session, "Target.closeTarget", {"targetId": target_id})
        if session is not None:
            get_browser_manager().remove(REFRESH_POOL_ID)
            from .browser_cdp import _terminate_session

            _terminate_session(session)


def render_page(
    url: str,
    network_policy: Any,
    wait_for: str = "",
    credential_domain: str = "",
    repo: Any = None,
) -> Dict[str, Any]:
    """headless 渲染 ``url``，返回与 web_fetch._render 可拼接的 content 片段。

    渲染完成后取 ``document.documentElement.outerHTML``（上限
    RENDER_HTML_CAP）复用 ``html_extract.extract`` 产出 title/text/links/
    tables —— 与静态分支同一抽取器、同一产出结构（R1，关闭 W6 backlog）。
    页面无 HTML 返回时回退 innerText 路径（兼容旧读取形态）。

    AU5：``credential_domain`` 给定时先把档案 cookie 经 ``Storage.setCookies``
    注入渲染浏览器（导航前生效），渲染完成后经 ``Storage.getCookies`` 按域取回
    并合并回档案，结果带 ``credential_refreshed``（一次导出，静态 / 渲染 /
    交互三条通道共用）。header 型档案渲染通道不支持，跳过注入不报错。

    Raises:
        RenderError: 门禁拒绝 / 浏览器不可用 / 导航失败 / 页面读取异常 /
            cookie 注入失败（显式给了凭据却建立不了登录态，宁失败不静默降级）。
    """
    rejection = network_policy.check_host(url)
    if rejection:
        raise RenderError(rejection)

    # X2：渲染耗时（Round 15，与 web_fetch 的 net 块口径对齐）
    _t0 = time.monotonic()

    credential_domain = (credential_domain or "").strip().lower()
    credential_cookies: List[Dict[str, Any]] = []
    if credential_domain:
        from .credential_vault import (
            KIND_COOKIE,
            looks_like_login_html,
            resolve_credential,
        )

        resolution = resolve_credential(credential_domain, url=url, repo=repo)
        if resolution.ok and resolution.kind == KIND_COOKIE:
            credential_cookies = list(resolution.cookies or [])

    session = _pool.acquire()
    channel_ok = _ensure_pool_channel(session)
    target_id: Optional[str] = None
    net_session: Optional[str] = None
    refreshed: Optional[List[str]] = None
    try:
        created = cdp_command(session, "Target.createTarget", {"url": "about:blank"})
        target_id = created.get("targetId")
        if not target_id:
            raise RenderError("渲染标签页创建失败")
        # R22：事件通道可用时 attach 渲染标签页 + Network.enable——主文档
        # 响应（含 302 重定向链中间 hop）经事件记录，读状态优先取事件值；
        # 通道未建立返回 None，状态仍走 Navigation Timing 兜底。
        net_session = ensure_network_tracking(session.browser_id, target_id)
        # AU5：导航前注入档案 cookie（浏览器级命令，无需 attach；浏览器内
        # 重定向自动按域携带）。注入失败走 RenderError——显式带凭据渲染却
        # 拿到未登录正文会误导调用方。
        if credential_cookies:
            from .credential_vault import normalize_cookie_for_cdp

            normalized_cookies = [
                normalize_cookie_for_cdp(c) for c in credential_cookies
            ]
            cdp_command(session, "Storage.setCookies", {"cookies": normalized_cookies})
        # AB4：文档创建前注入 stealth（失败不阻断渲染）
        apply_stealth(session, target_id, command=cdp_command)
        result = cdp_command(session, "Page.navigate", {"url": url}, target_id=target_id)
        if result.get("errorText"):
            raise RenderError(f"渲染导航失败: {result['errorText']}")
        wait_page_ready(session, target_id, wait_for=wait_for)
        _scroll_for_lazy_load(session, target_id)
        tracked = (
            get_tracked_response(session.browser_id, net_session) if net_session else None
        )
        # AB1：主文档 HTTP 状态经 Navigation Timing 读取（CDP 短连接收不到
        # Network 事件帧）——让 Cloudflare 403/503 盾页在渲染分支也可见。
        expression = (
            "JSON.stringify({url:location.href,title:document.title,"
            "status:(function(){try{var e=performance.getEntriesByType('navigation')[0];"
            "return e&&e.responseStatus||0}catch(x){return 0}})(),"
            f"html:document.documentElement.outerHTML.slice(0,{RENDER_HTML_CAP})}})"
        )
        info = _evaluate_json(session, expression, target_id)
        # AU5：渲染标签页存活期间按域取回 cookie 合并回档案（续期回写；
        # 任何失败静默——与 AU2"回写失败不影响本次请求"同口径）。
        if credential_cookies:
            refreshed = _writeback_render_cookies(session, credential_domain, url, repo=repo)
    except BrowserCDPError as exc:
        raise RenderError(
            f"JS 渲染失败: {exc}"
            "（可经 coder 用 browser_launch + browser_navigate 手动渲染，"
            "或 web_fetch render=never 取静态内容）"
        ) from exc
    finally:
        if net_session:
            detach_network_session(session.browser_id, net_session)
        if target_id:
            with contextlib.suppress(BrowserCDPError):
                cdp_command(session, "Target.closeTarget", {"targetId": target_id})

    page: Dict[str, Any] = {}
    if isinstance(info, str):
        try:
            page = json.loads(info)
        except ValueError:
            raise RenderError("渲染结果解析失败（页面返回异常）") from None
    html = page.get("html") or ""
    final_url = page.get("url", url)
    if html:
        from backend.wiki.html_extract import extract

        extracted = extract(html, final_url)
        title = extracted.title or page.get("title", "")
        content_text = extracted.text
        links = extracted.links
        tables = extracted.tables
        truncated = len(html) >= RENDER_HTML_CAP
    else:
        title = page.get("title", "")
        content_text = page.get("text") or ""
        links = []
        tables = []
        truncated = len(content_text) >= RENDER_TEXT_CAP
    status = page.get("status")
    # R22：事件驱动的 Document 状态比 Navigation Timing（仅最终 hop）更准，
    # 多跳 302 中间被反爬拦截（403 盾页）时能看到中间状态码；取到才覆盖。
    event_hit = bool(
        tracked and isinstance(tracked.get("status"), int) and tracked["status"] > 0
    )
    # R24：渲染事件命中率（诊断视角）——成功渲染才计
    record_render_event(channel_ok, event_hit)
    if event_hit:
        status = tracked["status"]
    rendered: Dict[str, Any] = {
        "url": final_url,
        "title": title,
        "content": content_text,
        "links": links,
        "tables": tables,
        "rendered": True,
        "truncated": truncated,
    }
    if isinstance(status, int) and status > 0:
        rendered["rendered_status"] = status
    if refreshed:
        rendered["credential_refreshed"] = refreshed
    # AU7：带凭据渲染却落在密码框页（正文极短）→ 登录墙标记
    if (
        credential_cookies
        and looks_like_login_html(html)
        and len(content_text.strip()) < 500
    ):
        rendered["login_wall"] = True
    if html:
        # SN2：渲染后 DOM 交给调用方做候选文件链接嗅探（web_tool 不把它回传给模型）
        rendered["html"] = html
    # X2：渲染耗时（Round 15）
    rendered["net"] = {"elapsed_ms": int((time.monotonic() - _t0) * 1000)}
    return rendered


__all__ = [
    "RENDER_HTML_CAP",
    "RENDER_IDLE_TIMEOUT_SECONDS",
    "RENDER_POOL_ID",
    "RENDER_POOL_IDS",
    "RENDER_POOL_SIZE",
    "RENDER_TEXT_CAP",
    "READY_TIMEOUT_SECONDS",
    "RenderError",
    "get_renderer_pool",
    "looks_like_js_shell",
    "refresh_credentials",
    "render_page",
    "wait_page_ready",
]
