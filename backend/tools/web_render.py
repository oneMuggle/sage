"""web_fetch JS 渲染降级 + 页面就绪等待（docs/plans/2026-09-06_web-dynamic-render-access.md W1/W2）。

web_fetch 静态抽取命中"JS 壳"特征（SPA 空根挂载点 / script 占比过高）时，
经 G7 的 CDP 基建（browser_cdp / browser_ws）驱动专用 headless 渲染实例
取渲染后正文：

- **实例池**：进程级懒初始化单个渲染实例（保留 id ``RENDER_POOL_ID``，
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
from typing import Any, Dict

from .browser_cdp import (
    RESERVED_BROWSER_ID,
    BrowserCDPError,
    BrowserSession,
    apply_stealth,
    cdp_command,
    get_browser_manager,
    launch_browser,
)

#: 渲染实例的保留 browser_id（web_fetch 专用，用户不可见）
RENDER_POOL_ID = RESERVED_BROWSER_ID

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

#: preferences 表的 key（web_access_config，需在 SettingsRepository.KEYS 白名单内）
SETTINGS_KEY_WEB_ACCESS_CONFIG = "web_access_config"


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


def wait_page_ready(session: BrowserSession, target_id: str | None, wait_for: str = "") -> None:
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


def _evaluate_json(session: BrowserSession, expression: str, target_id: str | None) -> Any:
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


def _scroll_for_lazy_load(session: BrowserSession, target_id: str | None) -> None:
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
    """进程级渲染实例池：懒启动、复用、空闲/死亡重建（线程安全）。

    工具在 executor 线程执行，懒初始化必须持锁；渲染本身（cdp_command 短
    连接 + 独立标签页）在锁外进行，并发渲染共用实例但互不干扰。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._session: BrowserSession | None = None
        self._last_used = 0.0

    def acquire(self) -> BrowserSession:
        with self._lock:
            session = self._session
            if (
                session is not None
                and session.is_alive()
                and time.monotonic() - self._last_used <= RENDER_IDLE_TIMEOUT_SECONDS
            ):
                self._last_used = time.monotonic()
                return session
            if session is not None:
                self._discard(session)
            try:
                session = launch_browser(
                    headless=True,
                    browser_id=RENDER_POOL_ID,
                    persistent=_render_persistent_enabled(),
                    profile_name=RENDER_PROFILE_NAME,
                )
            except BrowserCDPError as exc:
                raise RenderError(f"渲染浏览器启动失败: {exc}") from exc
            self._session = session
            self._last_used = time.monotonic()
            return session

    @staticmethod
    def _discard(session: BrowserSession) -> None:
        from .browser_cdp import _terminate_session

        get_browser_manager().remove(session.browser_id)
        _terminate_session(session)

    def reset(self) -> None:
        """测试钩子：清空池状态（不触碰进程）。"""
        with self._lock:
            self._session = None
            self._last_used = 0.0


_pool = _RendererPool()


def get_renderer_pool() -> _RendererPool:
    """渲染池单例访问（测试注入 / 后续生命周期管理用）。"""
    return _pool


def render_page(url: str, network_policy: Any, wait_for: str = "") -> Dict[str, Any]:
    """headless 渲染 ``url``，返回与 web_fetch._render 可拼接的 content 片段。

    渲染完成后取 ``document.documentElement.outerHTML``（上限
    RENDER_HTML_CAP）复用 ``html_extract.extract`` 产出 title/text/links/
    tables —— 与静态分支同一抽取器、同一产出结构（R1，关闭 W6 backlog）。
    页面无 HTML 返回时回退 innerText 路径（兼容旧读取形态）。

    Raises:
        RenderError: 门禁拒绝 / 浏览器不可用 / 导航失败 / 页面读取异常。
    """
    rejection = network_policy.check_host(url)
    if rejection:
        raise RenderError(rejection)

    session = _pool.acquire()
    target_id: str | None = None
    try:
        created = cdp_command(session, "Target.createTarget", {"url": "about:blank"})
        target_id = created.get("targetId")
        if not target_id:
            raise RenderError("渲染标签页创建失败")
        # AB4：文档创建前注入 stealth（失败不阻断渲染）
        apply_stealth(session, target_id, command=cdp_command)
        result = cdp_command(session, "Page.navigate", {"url": url}, target_id=target_id)
        if result.get("errorText"):
            raise RenderError(f"渲染导航失败: {result['errorText']}")
        wait_page_ready(session, target_id, wait_for=wait_for)
        _scroll_for_lazy_load(session, target_id)
        # AB1：主文档 HTTP 状态经 Navigation Timing 读取（CDP 短连接收不到
        # Network 事件帧）——让 Cloudflare 403/503 盾页在渲染分支也可见。
        expression = (
            "JSON.stringify({url:location.href,title:document.title,"
            "status:(function(){try{var e=performance.getEntriesByType('navigation')[0];"
            "return e&&e.responseStatus||0}catch(x){return 0}})(),"
            f"html:document.documentElement.outerHTML.slice(0,{RENDER_HTML_CAP})}})"
        )
        info = _evaluate_json(session, expression, target_id)
    except BrowserCDPError as exc:
        raise RenderError(
            f"JS 渲染失败: {exc}"
            "（可经 coder 用 browser_launch + browser_navigate 手动渲染，"
            "或 web_fetch render=never 取静态内容）"
        ) from exc
    finally:
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
    return rendered


__all__ = [
    "RENDER_HTML_CAP",
    "RENDER_IDLE_TIMEOUT_SECONDS",
    "RENDER_POOL_ID",
    "RENDER_TEXT_CAP",
    "READY_TIMEOUT_SECONDS",
    "RenderError",
    "get_renderer_pool",
    "looks_like_js_shell",
    "render_page",
    "wait_page_ready",
]
