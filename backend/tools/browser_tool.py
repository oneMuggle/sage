"""浏览器自动化工具组（对标增强 G7，docs/plans §2.1）。

对标 ZCode browser-use / Codex 浏览器操作：LLM 可启动本机 Chrome/Edge、
导航、读页面、点击/输入/滚动、截图、关闭。底层经 CDP（见 browser_cdp /
browser_ws）—— 不经 Playwright（Win7 兼容 + 零新依赖）。

风险分级（与权限矩阵对齐）：

- ``browser_launch`` EXEC（启动子进程，INTERACTIVE 先审批）；
- ``browser_navigate`` EXTERNAL（拉取网络内容，最严门禁、逐次审批）；
- ``browser_snapshot`` / ``browser_screenshot`` READ；
- ``browser_interact`` / ``browser_close`` / ``browser_tabs`` WRITE_LOCAL。

全部工具 ``is_blocking=True``：CDP 走阻塞 socket I/O，必须卸载到
executor 线程执行（同时规避在事件循环线程内做同步 socket 的死锁面）。
v1 面向 coder（executor 边界）；导航仅允许 http/https/about/data。
"""

from __future__ import annotations

import base64
import contextlib
import functools
import io
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from backend.data import browser_action_repo
from backend.domain.risk import RiskClass
from backend.services import browser_safety
from backend.services.browser_control import (
    BrowserControlState,
    get_browser_control,
)

from . import browser_frames
from .base import BaseTool, ToolResult, ToolSchema
from .browser_cdp import (
    EXTENSION_BROWSER_ID,
    RESERVED_BROWSER_ID,
    BrowserCDPError,
    BrowserSession,
    _list_page_targets,
    browser_downloads_root,
    cdp_command,
    get_browser_manager,
    launch_browser,
)
from .browser_events import (
    DEFAULT_WAIT_TIMEOUT,
    MAX_WAIT_TIMEOUT,
    get_download_tracker,
    list_download_dir,
    start_download_tracking,
)
from .browser_observe import (
    SNAPSHOT_HARD_COLLECT_CAP,
    SNAPSHOT_INTERACTIVE_MAX_DEFAULT,
    STALE_REF_ERROR,
    STALE_REF_INFO,
    TARGET_NAME_SOURCE_JS,
    build_frame_ref_expression,
    build_frame_target_expression,
    build_ref_expression,
    build_snapshot_expression,
    merge_snapshot_payloads,
    parse_key_combo,
    parse_snapshot_payload,
)
from .context import current_tool_context
from .file_tool import _record_artifact_safely
from .network_config import load_network_policy
from .web_render import _wait_network_idle, inject_network_monitor, wait_page_ready

logger = logging.getLogger(__name__)

#: localStorage 快照 JSON 上限（字节；超限视为异常页面，不保存）
LOCAL_STORAGE_CAP = 512 * 1024

#: 允许的 URL scheme（file:// 可读本地文件 → 坚决拒绝；javascript: 注入面）
_ALLOWED_SCHEMES = frozenset({"http", "https", "about", "data"})

#: 子 frame 内容读取允许的 scheme；其余（file:/chrome:/javascript:）一律 block
_ALLOWED_FRAME_SCHEMES = frozenset({"http", "https", "about", "data", "blob"})

#: 子 frame 交互前读取真实 location（隔离世界可跨域读自身）
_FRAME_LOCATION_EXPRESSION = (
    "(function(){return JSON.stringify({href:location.href,origin:location.origin});})()"
)

_VALID_ACTIONS = (
    "click",
    "type",
    "press",
    "scroll",
    "select",
    "hover",
    "check",
    "uncheck",
    "upload",
    "attr",
)

#: 视觉注入的截图约束（data URL 上限 1.5MB / 宽 1568px）
SCREENSHOT_VISION_MAX_BYTES = 1536 * 1024
SCREENSHOT_VISION_MAX_WIDTH = 1568

_VALID_SNAPSHOT_MODES = ("interactive", "text", "full")

#: 合成 KeyboardEvent 的 keyCode 映射（按主键查表；单字母/数字走 ord）。
_KEY_CODES = {
    "Enter": 13,
    "Escape": 27,
    "Tab": 9,
    "Space": 32,
    " ": 32,
    "Backspace": 8,
    "Delete": 46,
    "Home": 36,
    "End": 35,
    "PageUp": 33,
    "PageDown": 34,
    "ArrowUp": 38,
    "ArrowDown": 40,
    "ArrowLeft": 37,
    "ArrowRight": 39,
}

_VALID_TAB_ACTIONS = ("list", "create", "switch", "close")

#: 控制门禁错误文案（前缀是前端/提示逻辑的契约，不可改名）
_CONTROL_PAUSED_ERROR = (
    "user_paused: 用户已暂停浏览器操作；请在用户恢复后继续（可先向用户确认）"
)
_CONTROL_TAKEOVER_ERROR = (
    "user_takeover: 用户正在手动操作浏览器；请等待用户归还控制后重新 browser_snapshot"
)

#: 步骤缩略图开关的 settings key（缺省按开启）
_SETTINGS_KEY_STEP_THUMBNAILS = "browser_step_thumbnails"

#: 默认可见性开关的 settings key（缺省按可见）
_SETTINGS_KEY_DEFAULT_VISIBLE = "browser_use_default_visible"

#: 会截步骤缩略图的动作（snapshot/screenshot 不截：降开销、防递归）
_THUMBNAIL_ACTIONS = ("navigate", "interact", "tabs")

#: 受控浏览器每会话最近一次的页面信息（navigate/snapshot/interact/tabs 更新）
_LAST_PAGE: Dict[str, Dict[str, str]] = {}

#: 受控浏览器每会话最近一次快照的登录墙判断
_LAST_LOGIN_WALL: Dict[str, bool] = {}

#: 最近一次快照中 ref → 所属子 frame 的归属（跨 frame 交互定位用）。
#: 结构：browser_id -> ref -> {frame_id, frame_url, name}；新快照覆盖写入。
_SNAPSHOT_FRAME_REFS: Dict[str, Dict[str, Dict[str, str]]] = {}


def _current_owner() -> str:
    """当前工具调用所属的聊天会话 id；无上下文（单测/REST）返回空串。"""
    ctx = current_tool_context()
    return (ctx.session_id or "") if ctx is not None else ""


#: 当前工具调用的租约作用域栈（executor 线程内有效）。
_lease_local = threading.local()


@contextlib.contextmanager
def _browser_lease_scope():
    """工具执行作用域：退出时统一释放本作用域内登记的会话租约。"""
    stack = getattr(_lease_local, "stack", None)
    if stack is None:
        stack = []
        _lease_local.stack = stack
    acquired: List[BrowserSession] = []
    stack.append(acquired)
    try:
        yield
    finally:
        stack.pop()
        release = getattr(get_browser_manager(), "release_lease", None)
        if release is not None:
            for session in acquired:
                release(session)


def _lease_session(session: BrowserSession) -> None:
    """在活动租约作用域内登记一次使用（无作用域时静默跳过）。"""
    stack = getattr(_lease_local, "stack", None)
    if not stack:
        return
    acquired = stack[-1]
    if any(item is session for item in acquired):
        return
    acquire = getattr(get_browser_manager(), "acquire_lease", None)
    if acquire is None:
        return
    acquire(session)
    acquired.append(session)


def _leased(fn):
    """浏览器工具 execute 装饰器：为整个调用持有租约。"""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with _browser_lease_scope():
            return fn(*args, **kwargs)

    return wrapper


#: 每聊天会话的自动拉起互斥（避免 check-then-act 双开孤儿实例）。
_launch_locks: Dict[str, threading.Lock] = {}
_launch_locks_guard = threading.Lock()


def _owner_launch_lock(owner: str) -> threading.Lock:
    key = owner or "__anonymous__"
    with _launch_locks_guard:
        lock = _launch_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _launch_locks[key] = lock
        return lock


def _error(exc: BrowserCDPError) -> ToolResult:
    return ToolResult(success=False, error=str(exc))


def _resolve_session(browser_id: Optional[str]) -> BrowserSession:
    """统一入口：按调用方会话归属解析会话，并登记执行租约。"""
    manager = get_browser_manager()
    session = manager.require(browser_id, owner=_current_owner())
    _lease_session(session)
    return session


# ---------------------------------------------------------------------------
# 控制面门禁 + 步骤元数据（M3）
# ---------------------------------------------------------------------------


def _control_state(session: BrowserSession) -> BrowserControlState:
    """读取会话控制状态（未知会话默认 agent）。"""
    return get_browser_control().get_state(session.browser_id)


def _blocked_by_control(
    session: BrowserSession, tool_name: str
) -> Optional[ToolResult]:
    """控制门禁：paused / user_takeover 时返回带 browser_meta 的拦截结果；agent 放行。"""
    state = _control_state(session)
    # 失败结果同样附步骤元数据：前端时间线需要展示“在哪一步被拦”
    action = tool_name.replace("browser_", "", 1)
    if state is BrowserControlState.PAUSED:
        logger.info(
            "%s 被控制门禁拦截: session=%s state=paused", tool_name, session.browser_id
        )
        return _meta_result(
            ToolResult(success=False, error=_CONTROL_PAUSED_ERROR), session, action
        )
    if state is BrowserControlState.USER_TAKEOVER:
        logger.info(
            "%s 被控制门禁拦截: session=%s state=user_takeover",
            tool_name,
            session.browser_id,
        )
        return _meta_result(
            ToolResult(success=False, error=_CONTROL_TAKEOVER_ERROR), session, action
        )
    return None


def _remember_page(session: BrowserSession, url: str, title: str) -> None:
    """记录会话最近一次页面信息（供失败结果 / 后续动作兜底）。"""
    if not session.browser_id or not (url or title):
        return
    _LAST_PAGE[session.browser_id] = {"url": url or "", "title": title or ""}


def _cached_page(session: BrowserSession) -> Tuple[str, str]:
    cached = _LAST_PAGE.get(session.browser_id) or {}
    return str(cached.get("url") or ""), str(cached.get("title") or "")


def _detect_login_wall(elements: Any) -> bool:
    """快照元素里存在角色 textbox 且类型 password 的输入框 → 疑似登录墙。"""
    if not isinstance(elements, list):
        return False
    return any(
        isinstance(item, dict)
        and item.get("role") == "textbox"
        and item.get("type") == "password"
        for item in elements
    )


def _browser_meta(
    session: BrowserSession,
    action: str,
    url: str = "",
    title: str = "",
    target_ref: str = "",
    target_name: str = "",
    screenshot_path: Optional[str] = None,
) -> Dict[str, Any]:
    """构造工具结果上的 ``browser_meta``（前端时间线 / Electron 面板消费）。"""
    cached_url, cached_title = _cached_page(session)
    return {
        "session_id": session.browser_id,
        "action": action,
        "url": url or cached_url,
        "title": title or cached_title,
        "target_ref": target_ref,
        "target_name": target_name,
        "login_wall": bool(_LAST_LOGIN_WALL.get(session.browser_id, False)),
        "screenshot_path": screenshot_path,
    }


def _with_meta(content: Any, session: BrowserSession, action: str, **fields: Any) -> Dict[str, Any]:
    """给 content 附 browser_meta；content 非 dict 时包成 ``{"result": ...}``。"""
    meta = _browser_meta(session, action, **fields)
    if isinstance(content, dict):
        merged = dict(content)
        merged["browser_meta"] = meta
        return merged
    return {"result": content, "browser_meta": meta}


def _meta_result(result: ToolResult, session: BrowserSession, action: str, **fields: Any) -> ToolResult:
    """复制 ToolResult 并附 browser_meta（不改动 output 语义）。"""
    return ToolResult(
        success=result.success,
        content=_with_meta(result.content, session, action, **fields),
        error=result.error,
        output=result.output,
    )


def _meta_error(
    exc: BrowserCDPError, session: Optional[BrowserSession], action: str
) -> ToolResult:
    """CDP 错误附 browser_meta；会话尚未解析（解析失败）时保持裸错误。"""
    result = _error(exc)
    if session is None:
        return result
    return _meta_result(result, session, action)


def _current_page_site_block(
    session: BrowserSession, action: str
) -> Optional[ToolResult]:
    """复检当前页面域名；命中 block 站点策略时返回拦截结果，否则 None。

    CDP 读不到 URL 时放行：复检失败不阻断主流程。
    """
    try:
        href_result = cdp_command(
            session, "Runtime.evaluate", {"expression": "location.href"}
        )
    except BrowserCDPError:
        return None
    current_url = str((href_result.get("result") or {}).get("value") or "")
    if not current_url:
        return None
    domain = (urlsplit(current_url).hostname or "").lower()
    if not domain or _safety_check_site(session.browser_id, current_url) != "block":
        return None
    return _meta_result(
        ToolResult(success=False, error=f"site_blocked: 当前页面已被禁止 {domain}"),
        session,
        action,
        url=current_url,
    )


def _step_thumbnails_enabled() -> bool:
    """步骤缩略图开关；读取失败 / 缺省一律按开启处理。"""
    try:
        from backend.data.settings_repo import SettingsRepository

        raw = SettingsRepository().get(_SETTINGS_KEY_STEP_THUMBNAILS)
    except Exception:  # noqa: BLE001 — 设置读取失败不阻断浏览器动作
        return True
    if raw is None:
        return True
    return str(raw).strip().lower() not in ("0", "false", "off", "no")


def _browser_default_visible() -> bool:
    """受控浏览器默认是否可见；读取失败 / 缺省按可见（"1"）处理。

    仅显式 ``"0"`` 才切到无头（与设置页语义一致）；其它值一律按可见。
    """
    try:
        from backend.data.settings_repo import SettingsRepository

        raw = SettingsRepository().get(_SETTINGS_KEY_DEFAULT_VISIBLE)
    except Exception:  # noqa: BLE001 — 设置读取失败不阻断浏览器动作
        return True
    if raw is None:
        return True
    return str(raw).strip() != "0"


def _has_usable_browser_session(owner: str) -> bool:
    """当前会话是否存在可直接使用的浏览器（自有实例 / 用户共享标签页）。

    归属模式下只看本会话拥有的实例与 ``external`` 共享标签页——绝不把其他
    会话的实例当作"可用"，因此自动拉起判断不会因别人开了浏览器而跳过。
    无归属（``owner == ""``）保持旧语义：存在任意非保留用户会话即可用。
    """
    manager = get_browser_manager()
    if owner:
        if manager.owned_sessions(owner):
            return True
        return manager.get(EXTENSION_BROWSER_ID) is not None
    for session in manager.all_sessions():
        browser_id = session.browser_id or ""
        if browser_id == RESERVED_BROWSER_ID:
            continue
        if browser_id.startswith(RESERVED_BROWSER_ID + "-"):
            continue
        return True
    return False


def _download_dir_for(session: BrowserSession, workspace_root: Optional[str]) -> Path:
    """下载落盘目录：工作区内 ``<root>/downloads``；否则数据目录按实例分目录。

    无工作区时按 ``browser_id`` 分子目录：多会话并发下载不再互相覆盖，
    ``browser_downloads`` 的目录列举回退也不会把别人的文件列进来。
    """
    if workspace_root:
        return Path(workspace_root) / "downloads"
    return browser_downloads_root() / (session.browser_id or "unknown")


def _apply_download_behavior(session: BrowserSession, workspace_root: Optional[str]) -> Path:
    """把浏览器内触发的下载重定向到工作区（或数据目录下按实例分目录）。

    Electron 内嵌桥在 ``will-download`` 时若拿不到保存目录会弹系统保存对话框，
    受控/隐藏窗口下无人可点 → 下载卡死。``browser_launch`` / ``browser_navigate``
    自动拉起 / ``browser_login`` 复用或新建会话都必须设置。
    设置失败只告警，不阻断主流程；返回目标目录供调用方启动下载跟踪。
    """
    download_dir = _download_dir_for(session, workspace_root)
    try:
        download_dir.mkdir(parents=True, exist_ok=True)
        cdp_command(
            session,
            "Browser.setDownloadBehavior",
            {"behavior": "allow", "downloadPath": str(download_dir)},
        )
    except BrowserCDPError as exc:
        logger.warning("setDownloadBehavior 失败（不影响主流程）: %s", exc)
    return download_dir


def _capture_step_thumbnail(session: BrowserSession) -> Optional[str]:
    """截当前页步骤缩略图到数据目录；任何失败静默返回 None。"""
    if not _step_thumbnails_enabled():
        return None
    try:
        result = cdp_command(session, "Page.captureScreenshot", {"format": "png"})
        data = result.get("data")
        if not data:
            return None
        png_bytes = base64.b64decode(data)
        # 数据目录，绝不写工作区（避免污染 artifact/用户工程）
        folder = browser_downloads_root().parent / "browser_steps" / session.browser_id
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{int(time.time() * 1000)}.png"
        target.write_bytes(png_bytes)
        return str(target.resolve())
    except Exception:  # noqa: BLE001 — 缩略图失败不影响工具结果
        logger.debug(
            "browser step thumbnail 失败: session=%s", session.browser_id, exc_info=True
        )
        return None


# ---------------------------------------------------------------------------
# 安全层接线（M4）：站点授权 / 敏感动作 / 元素元数据 / 审计
# ---------------------------------------------------------------------------


def _safety_check_site(session_id: str, url: str) -> str:
    """站点判定薄包装（allow/confirm/block）；单测可替换为固定值。"""
    return browser_safety.check_site(session_id, url)


def _site_access_gate(
    session: BrowserSession,
    url: str,
    domain: str,
    started: float,
    tool: str = "browser_navigate",
) -> Optional[ToolResult]:
    """M4 站点授权门禁：拒绝指纹 → 持久/会话策略 → block / confirm。

    返回拦截结果（已写审计）或 None（放行）。导航落地域名与请求域名
    不同（重定向/短链）时调用方用最终 URL 再调一次，避免 302 绕过。
    子 frame 交互传入 ``tool="browser_interact"``，把授权绑定到交互动作。
    """
    if not domain:
        return None
    meta_action = "interact" if tool == "browser_interact" else "navigate"
    site_fingerprint = browser_safety.action_fingerprint(
        tool,
        "site_access",
        domain,
        session_id=session.browser_id,
    )
    registry = browser_safety.get_confirmation_registry()
    if registry.is_denied(site_fingerprint, session.browser_id):
        # 用户拒绝后暂停会话：禁止页面继续被 snapshot/interact 读取。
        get_browser_control().set_state(session.browser_id, BrowserControlState.PAUSED)
        _record_browser_audit(
            session,
            tool,
            meta_action,
            "blocked",
            approval="denied",
            domain=domain,
            duration_ms=_elapsed_ms(started),
        )
        return _meta_result(
            ToolResult(
                success=False,
                error="denied_by_user: 用户拒绝了访问该站点，请换一种方式或询问用户",
            ),
            session,
            meta_action,
            url=url,
        )
    verdict = _safety_check_site(session.browser_id, url)
    if verdict == "block":
        get_browser_control().set_state(session.browser_id, BrowserControlState.PAUSED)
        _record_browser_audit(
            session,
            tool,
            meta_action,
            "blocked",
            approval="none",
            domain=domain,
            duration_ms=_elapsed_ms(started),
        )
        return _meta_result(
            ToolResult(success=False, error=f"site_blocked: 用户已禁止该站点 {domain}"),
            session,
            meta_action,
            url=url,
        )
    if verdict == "confirm":
        pending = registry.create(
            session.browser_id,
            "site_access",
            code="site_access",
            domain=domain,
            description=f"访问站点 {domain}：{url}",
            options=list(browser_safety.SITE_ACCESS_OPTIONS),
            screenshot_path=_capture_step_thumbnail(session) or "",
            fingerprint=site_fingerprint,
        )
        get_browser_control().set_state(session.browser_id, BrowserControlState.PAUSED)
        _record_browser_audit(
            session,
            tool,
            meta_action,
            "confirm_required",
            approval="none",
            domain=domain,
            duration_ms=_elapsed_ms(started),
        )
        return _meta_result(
            ToolResult(
                success=False,
                error=(
                    f"needs_confirmation: {pending.id} 访问站点 {domain}"
                    "（请在右栏浏览器面板确认）"
                ),
            ),
            session,
            meta_action,
            url=url,
        )
    return None


def _blocked_current_page(session: BrowserSession) -> Optional[Tuple[str, str]]:
    """当前页面域名被持久策略禁止时返回 ``(domain, url)``，否则 None。

    用于 snapshot/interact 的前置短路：即使导航门禁曾放行（例如策略在
    会话中途被改写成 block），也不允许继续读取/操作被禁止的站点。
    """
    url, _title = _cached_page(session)
    if not url:
        return None
    domain = browser_safety.domain_of(url)
    if not domain:
        return None
    if _safety_check_site(session.browser_id, url) != "block":
        return None
    return domain, url


def _site_blocked_result(session: BrowserSession, action: str) -> Optional[ToolResult]:
    """当前页面被禁止时的统一 ``site_blocked:`` 结果（附带 browser_meta）。"""
    blocked = _blocked_current_page(session)
    if blocked is None:
        return None
    domain, url = blocked
    return _meta_result(
        ToolResult(success=False, error=f"site_blocked: 用户已禁止该站点 {domain}"),
        session,
        action,
        url=url,
    )


def _read_target_metadata(
    session: BrowserSession,
    ref: str = "",
    selector: str = "",
    *,
    use_focused: bool = False,
) -> Optional[Dict[str, Any]]:
    """只读读取交互目标元数据（tag/role/name/type/placeholder）。

    ref 优先、selector 回退；无定位且 ``use_focused``（press）时读取
    当前焦点元素。失败或元素不存在返回 None（调用方用 text 参数兜底，
    否则按 fail-closed 分类），不抛错、不产生页面副作用。
    """
    if not ref and not selector and not use_focused:
        return None
    if ref:
        owner = _SNAPSHOT_FRAME_REFS.get(session.browser_id, {}).get(str(ref))
        if owner:
            try:
                context_id = browser_frames.create_world(session, owner["frame_id"])
                value = browser_frames.evaluate_in_context(
                    session,
                    build_frame_target_expression(ref, str(owner.get("name") or "")),
                    context_id,
                )
            except BrowserCDPError:
                logger.debug("子 frame 交互目标元数据读取失败", exc_info=True)
                return None
            return value if isinstance(value, dict) else None
        locator = f"(window.__SAGE_REFS__||{{}})[{json.dumps(str(ref))}]"
    elif selector:
        locator = f"document.querySelector({json.dumps(str(selector))})"
    else:
        locator = "(document.activeElement||document.body)"
    # body/documentElement 永不取正文；宽泛容器（div/main/section… 且没有
    # 交互角色）只取直接文本节点，避免整页/整块 innerText 进入 name →
    # 审计/确认描述（I3）。focused 与非 focused 路径共用同一守卫。
    expression = (
        "(function(){var el=" + locator + ";if(!el)return null;"
        + TARGET_NAME_SOURCE_JS
        + "return{tag:(el.tagName||'').toLowerCase(),"
        "role:(el.getAttribute&&el.getAttribute('role'))||'',"
        "name:String(name).trim().slice(0,120),"
        "type:String((el.getAttribute&&el.getAttribute('type'))||'').toLowerCase(),"
        "placeholder:String((el.getAttribute&&el.getAttribute('placeholder'))||'').slice(0,120)};"
        "})()"
    )
    try:
        value = _evaluate_json(session, expression, None)
    except BrowserCDPError:
        logger.debug("交互目标元数据读取失败", exc_info=True)
        return None
    return value if isinstance(value, dict) else None


def _elapsed_ms(started: float) -> int:
    """自 started（time.monotonic）以来的毫秒数；异常按 0。"""
    try:
        return max(0, int((time.monotonic() - started) * 1000))
    except Exception:  # noqa: BLE001 — 审计耗时统计不得影响工具
        return 0


def _record_browser_audit(
    session: Optional[BrowserSession],
    tool: str,
    action: str,
    result: str,
    *,
    approval: str = "auto",
    target_ref: str = "",
    target_desc: str = "",
    domain: str = "",
    duration_ms: int = 0,
) -> None:
    """写一条动作审计；不落页面正文 / 输入值 / 凭据，失败静默。"""
    try:
        resolved_domain = domain
        if not resolved_domain and session is not None:
            resolved_domain = browser_safety.domain_of(_cached_page(session)[0])
        browser_action_repo.record(
            {
                "session_id": session.browser_id if session is not None else "unknown",
                "conversation_id": _current_owner() or None,
                "ts": int(time.time() * 1000),
                "domain": resolved_domain,
                "tool": tool,
                "action": action,
                "target_ref": target_ref or "",
                "target_desc": (target_desc or "")[: browser_action_repo.MAX_TARGET_DESC],
                "result": result,
                "approval": approval,
                "duration_ms": int(duration_ms),
            }
        )
    except Exception:  # noqa: BLE001 — 审计失败不得影响工具结果
        logger.debug("browser audit 记录失败", exc_info=True)


def _snapshot_untrusted_text(content: Dict[str, Any]) -> str:
    """从快照结果提取可扫描文本（text 正文优先，其次元素可访问名）。"""
    text = content.get("text")
    if isinstance(text, str) and text:
        return text
    elements = content.get("elements")
    if isinstance(elements, list):
        return " ".join(
            str(item.get("name") or "") for item in elements if isinstance(item, dict)
        )
    return ""


def validate_url(url: str) -> Optional[str]:
    """导航 scheme 校验；返回错误文案或 None。"""
    if not isinstance(url, str) or not url.strip():
        return "url 不能为空"
    scheme = (urlsplit(url.strip()).scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        return (
            f"不允许的 URL scheme: {scheme or '(空)'}"
            f"（允许: {', '.join(sorted(_ALLOWED_SCHEMES))}；"
            "file:// 可读取本地文件，已拒绝）"
        )
    return None


# ---------------------------------------------------------------------------
# JS 交互构造器（独立函数便于单测：断言转义与选择器分支）
# ---------------------------------------------------------------------------


def _js_click(selector: str = "", text: str = "") -> str:
    """构造点击表达式：selector 优先，其次按可见文本找最深匹配元素。"""
    if selector:
        target = f"document.querySelector({json.dumps(selector)})"
    else:
        needle = json.dumps(text)
        target = (
            "(function(){"
            "const els=[...document.querySelectorAll('a,button,[role=button],input[type=submit],input[type=button],summary,label,li,span,div')];"
            f"const hits=els.filter(e=>e.offsetParent!==null&&e.textContent&&e.textContent.trim()==={needle});"
            f"const hit=hits.find(e=>e.children.length===0)||hits[0];"
            f"return hit||[...document.querySelectorAll('*')].find(e=>e.offsetParent!==null&&e.textContent&&e.textContent.trim()==={needle})||null;"
            "})()"
        )
    return (
        "(function(){"
        f"const el={target};"
        "if(!el)return{ok:false,info:'not-found'};"
        "el.scrollIntoView({block:'center'});"
        "el.click();"
        f"return{{ok:true,info:(el.tagName||'')+' '+(el.textContent||'').trim().slice(0,80)}};"
        "})()"
    )


def _js_type(selector: str, value: str, clear: bool) -> str:
    """构造输入表达式：React 兼容的原生 setter + input/change 事件。"""
    return (
        "(function(){"
        f"const el=document.querySelector({json.dumps(selector)});"
        "if(!el)return{ok:false,info:'not-found'};"
        "el.scrollIntoView({block:'center'});"
        "el.focus();"
        "const isContenteditable=el.isContentEditable;"
        "const proto=isContenteditable?HTMLElement.prototype:(el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype);"
        "const desc=isContenteditable?null:Object.getOwnPropertyDescriptor(proto,'value');"
        "if(desc&&desc.set){desc.set.call(el," + json.dumps(value) + ");}"
        "else{el.textContent=" + json.dumps(value) + ";}"
        "el.dispatchEvent(new Event('input',{bubbles:true}));"
        "el.dispatchEvent(new Event('change',{bubbles:true}));"
        f"return{{ok:true,info:'typed '+(el.value||el.textContent||'').length+' chars'+({json.dumps(' cleared-first' if clear else '')})}};"
        "})()"
    )


def _key_event_options(key: str) -> str:
    """构造 KeyboardEvent 初始化对象字面量（含组合键 modifier 标志）。"""
    modifiers, main = parse_key_combo(key)
    code = _KEY_CODES.get(main)
    if code is None and len(main) == 1:
        upper = main.upper()
        if ("A" <= upper <= "Z") or ("0" <= upper <= "9"):
            code = ord(upper)
    key_code = code or 0
    return (
        "{key:"
        + json.dumps(main)
        + ",keyCode:"
        + str(key_code)
        + ",which:"
        + str(key_code)
        + ",ctrlKey:"
        + ("true" if modifiers["ctrlKey"] else "false")
        + ",shiftKey:"
        + ("true" if modifiers["shiftKey"] else "false")
        + ",altKey:"
        + ("true" if modifiers["altKey"] else "false")
        + ",metaKey:"
        + ("true" if modifiers["metaKey"] else "false")
        + ",bubbles:true,cancelable:true}"
    )


def _js_press(key: str) -> str:
    """无定位目标时的按键：作用于当前焦点元素。"""
    options = _key_event_options(key)
    return (
        "(function(){"
        "const el=document.activeElement||document.body;"
        f"const opts={options};"
        "el.dispatchEvent(new KeyboardEvent('keydown',opts));"
        "el.dispatchEvent(new KeyboardEvent('keyup',opts));"
        f"return{{ok:true,info:'pressed '+{json.dumps(key)}}};"
        "})()"
    )


def _js_scroll(amount: int) -> str:
    return (
        "(function(){"
        f"window.scrollBy(0,{int(amount)});"
        f"return{{ok:true,info:'scrolled to y='+window.scrollY}};"
        "})()"
    )


#: 元素描述片段：调用方已把元素绑定为 ``el``，此处拼出 "TAG 可访问名"。
_DESCRIBE_JS = (
    "var __sageLabel=(el.getAttribute&&el.getAttribute('data-sage-ref-name'))"
    "||(el.getAttribute&&el.getAttribute('aria-label'))"
    "||(el.innerText||el.value||'');"
    "var __sageDesc=String((el.tagName||'')+' '+String(__sageLabel).trim()).slice(0,120);"
)


def _js_on_selector(selector: str, action_js: str) -> str:
    """把元素级片段包装成"按 CSS selector 定位后执行"。"""
    return (
        "(function(){"
        f"const el=document.querySelector({json.dumps(selector)});"
        "if(!el)return{ok:false,info:'not-found'};"
        f"return {action_js};"
        "})()"
    )


def _js_click_element() -> str:
    return (
        "(function(){"
        "el.scrollIntoView({block:'center'});"
        "if(el.click){el.click();}else{el.dispatchEvent(new MouseEvent('click',{bubbles:true}));}"
        + _DESCRIBE_JS
        + "return{ok:true,info:'clicked '+__sageDesc};"
        "})()"
    )


def _js_attr_element(name: str) -> str:
    return (
        "(function(){"
        f"var next={json.dumps(name)};"
        "if(!el.getAttribute){return{ok:false,info:'no-attribute-api'};}"
        "var v=el.getAttribute(next);"
        "if(v===null){return{ok:false,info:'attribute-not-found: '+next};}"
        "return{ok:true,info:String(v).slice(0,4000)};"
        "})()"
    )


def _js_type_element(value: str, clear: bool) -> str:
    cleared = json.dumps(" cleared-first" if clear else "")
    return (
        "(function(){"
        "el.scrollIntoView({block:'center'});"
        "if(el.focus){el.focus();}"
        f"const next={json.dumps(value)};"
        "if(el.isContentEditable){el.textContent=next;}"
        "else{"
        "const proto=(el.tagName==='TEXTAREA')?HTMLTextAreaElement.prototype:(el.tagName==='SELECT'?HTMLSelectElement.prototype:HTMLInputElement.prototype);"
        "const desc=Object.getOwnPropertyDescriptor(proto,'value');"
        "if(desc&&desc.set){desc.set.call(el,next);}else{el.value=next;}"
        "}"
        "el.dispatchEvent(new Event('input',{bubbles:true}));"
        "el.dispatchEvent(new Event('change',{bubbles:true}));"
        f"return{{ok:true,info:'typed '+(el.value||el.textContent||'').length+' chars'+{cleared}}};"
        "})()"
    )


def _js_select_element(value: str) -> str:
    """选择 <select> 的 option（value 或可见文本匹配），派发 input/change。"""
    return (
        "(function(){"
        "el.scrollIntoView({block:'center'});"
        f"const want={json.dumps(value)};"
        "let matched=false;"
        "if((el.tagName||'').toUpperCase()==='SELECT'&&el.options){"
        "for(let i=0;i<el.options.length;i++){"
        "const option=el.options[i];"
        "if(option.value===want||String(option.text||'').trim()===want){"
        "el.value=option.value;matched=true;break;"
        "}"
        "}"
        "}"
        "if(!matched&&'value' in el){try{el.value=want;matched=true;}catch(err){}}"
        "if(!matched)return{ok:false,info:'option-not-found'};"
        "el.dispatchEvent(new Event('input',{bubbles:true}));"
        "el.dispatchEvent(new Event('change',{bubbles:true}));"
        "return{ok:true,info:'selected '+String(el.value)};"
        "})()"
    )


def _js_hover_element() -> str:
    return (
        "(function(){"
        "el.scrollIntoView({block:'center'});"
        "const rect=el.getBoundingClientRect();"
        "const x=rect.left+rect.width/2;"
        "const y=rect.top+rect.height/2;"
        "el.dispatchEvent(new MouseEvent('mouseover',{bubbles:true,cancelable:true,clientX:x,clientY:y}));"
        "el.dispatchEvent(new MouseEvent('mouseenter',{bubbles:false,cancelable:true,clientX:x,clientY:y}));"
        "el.dispatchEvent(new MouseEvent('mousemove',{bubbles:true,cancelable:true,clientX:x,clientY:y}));"
        + _DESCRIBE_JS
        + "return{ok:true,info:'hover '+__sageDesc};"
        "})()"
    )


def _js_set_checked_element(checked: bool) -> str:
    flag = "true" if checked else "false"
    label = "checked" if checked else "unchecked"
    return (
        "(function(){"
        "el.scrollIntoView({block:'center'});"
        f"const want={flag};"
        "if('checked' in el){el.checked=want;}"
        "else if(el.setAttribute){el.setAttribute('aria-checked',want?'true':'false');}"
        "el.dispatchEvent(new Event('input',{bubbles:true}));"
        "el.dispatchEvent(new Event('change',{bubbles:true}));"
        + _DESCRIBE_JS
        + f"return{{ok:true,info:'{label} '+__sageDesc}};"
        "})()"
    )


def _js_press_element(key: str) -> str:
    """聚焦元素后派发组合键（先 focus，再 keydown/keyup）。"""
    options = _key_event_options(key)
    return (
        "(function(){"
        "el.scrollIntoView({block:'center'});"
        "if(el.focus){el.focus();}"
        f"const opts={options};"
        "el.dispatchEvent(new KeyboardEvent('keydown',opts));"
        "el.dispatchEvent(new KeyboardEvent('keyup',opts));"
        f"return{{ok:true,info:'pressed '+{json.dumps(key)}}};"
        "})()"
    )


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


def _evaluate_element_object_id(
    session: BrowserSession, expression: str, target_id: Optional[str] = None
) -> str:
    """Runtime.evaluate（returnByValue=False）→ 元素 objectId。

    ``DOM.setFileInputFiles`` 必须拿到远端节点句柄（objectId），不能用
    ``returnByValue`` 序列化元素。
    """
    result = cdp_command(
        session,
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": False},
        target_id=target_id,
    )
    details = result.get("exceptionDetails")
    if details:
        raise BrowserCDPError(f"页面脚本执行失败: {json.dumps(details)[:300]}")
    object_id = str((result.get("result") or {}).get("objectId") or "")
    if not object_id:
        raise BrowserCDPError("未找到上传目标元素（objectId 缺失）")
    return object_id


def _upload_lookup_js(ref: str, selector: str) -> str:
    """上传目标元素的定位 JS 片段（ref 优先，selector 回退）。"""
    if ref:
        return "(window.__SAGE_REFS__||{})[" + json.dumps(str(ref)) + "]||null"
    return "document.querySelector(" + json.dumps(str(selector)) + ")"


def _build_upload_check_expression(ref: str, selector: str) -> str:
    """校验上传目标存在、ref 未失效且为 ``input[type=file]``。"""
    if ref:
        guard = (
            "var key=" + json.dumps(str(ref)) + ";"
            "var el=(window.__SAGE_REFS__||{})[key]||null;"
            "var names=window.__SAGE_REF_NAMES__||{};"
            "if(!el||el.isConnected!==true)"
            "{return{ok:false,reason:'stale-ref'};}"
            "if(el.getAttribute('data-sage-ref-name')!==names[key])"
            "{return{ok:false,reason:'stale-ref'};}"
        )
    else:
        guard = (
            "var el=document.querySelector(" + json.dumps(str(selector)) + ");"
            "if(!el){return{ok:false,reason:'element_not_found'};}"
        )
    return (
        "(function(){"
        + guard
        + "var tag=(el.tagName||'').toLowerCase();"
        "var type=((el.getAttribute&&el.getAttribute('type'))||'').toLowerCase();"
        "if(tag!=='input'||type!=='file')"
        "{return{ok:false,reason:'not_file_input',tag:tag,type:type};}"
        "return{ok:true};"
        "})()"
    )


def _build_upload_element_expression(ref: str, selector: str) -> str:
    """返回目标元素句柄的表达式（配合 ``returnByValue=False`` 取 objectId）。"""
    return "(function(){return " + _upload_lookup_js(ref, selector) + ";})()"


def _upload_file_to_input(
    session: BrowserSession, ref: str, selector: str, file_path: Path
) -> str:
    """校验目标为 file input 后经 CDP 注入文件；返回可读成功信息。"""
    check = _evaluate_json(session, _build_upload_check_expression(ref, selector), None)
    if not isinstance(check, dict):
        raise BrowserCDPError("上传目标校验结果异常（非 JSON）")
    if not check.get("ok"):
        reason = str(check.get("reason") or "")
        if reason == STALE_REF_INFO:
            raise BrowserCDPError(STALE_REF_ERROR)
        if reason == "not_file_input":
            raise BrowserCDPError(
                "upload_target_not_file_input: 目标不是 input[type=file]"
                f"（tag={check.get('tag') or '?'}, type={check.get('type') or '?'}）"
            )
        raise BrowserCDPError("upload_target_not_found: 未找到上传目标元素")
    object_id = _evaluate_element_object_id(
        session, _build_upload_element_expression(ref, selector)
    )
    cdp_command(
        session,
        "DOM.setFileInputFiles",
        {"files": [str(file_path)], "objectId": object_id},
        target_id=None,
    )
    return f"uploaded {file_path.name}"


def _png_width(png_bytes: bytes) -> Optional[int]:
    """从 PNG IHDR 读取宽度（无需 Pillow）；非 PNG 返回 None。"""
    if len(png_bytes) < 24 or png_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    try:
        return int.from_bytes(png_bytes[16:20], "big")
    except Exception:  # noqa: BLE001 — 头损坏按未知宽度处理
        return None


def _build_screenshot_vision_payload(png_bytes: bytes) -> Dict[str, Any]:
    """为视觉注入生成 data URL（≤1.5MB、宽 ≤1568px）。

    Pillow 是可选依赖（随 OCR 引擎附带，不做硬依赖）：可用时按宽缩放到
    1568px，PNG 仍超限再降级为 JPEG；不可用时只做尺寸检查，超限返回
    ``vision_skipped: "too_large"``（调用方只回路径）。
    """
    data = png_bytes
    mime = "image/png"
    try:
        from PIL import Image  # type: ignore
    except Exception:  # noqa: BLE001 — Pillow 缺失按无缩放路径处理
        Image = None  # type: ignore[assignment]
    if Image is not None:
        try:
            with Image.open(io.BytesIO(png_bytes)) as source:
                img = source
                width, height = img.size
                scale = 1.0
                if width > SCREENSHOT_VISION_MAX_WIDTH:
                    scale = SCREENSHOT_VISION_MAX_WIDTH / float(width)
                best_png: Optional[bytes] = None
                current_scale = scale
                for _ in range(4):
                    frame = img
                    if current_scale < 1.0:
                        frame = img.resize(
                            (
                                max(1, int(width * current_scale)),
                                max(1, int(height * current_scale)),
                            )
                        )
                    buf = io.BytesIO()
                    frame.save(buf, format="PNG")
                    candidate = buf.getvalue()
                    best_png = candidate
                    if len(candidate) <= SCREENSHOT_VISION_MAX_BYTES:
                        break
                    current_scale *= 0.75
                if best_png is not None and len(best_png) <= SCREENSHOT_VISION_MAX_BYTES:
                    data = best_png
                    mime = "image/png"
                else:
                    # PNG 仍超限 → JPEG 质量阶梯（视觉 API 均接受）
                    rgb = img.convert("RGB")
                    if current_scale < 1.0:
                        rgb = rgb.resize(
                            (
                                max(1, int(width * current_scale)),
                                max(1, int(height * current_scale)),
                            )
                        )
                    for quality in (85, 70, 55):
                        buf = io.BytesIO()
                        rgb.save(buf, format="JPEG", quality=quality, optimize=True)
                        candidate = buf.getvalue()
                        if len(candidate) <= SCREENSHOT_VISION_MAX_BYTES:
                            data = candidate
                            mime = "image/jpeg"
                            break
        except Exception:  # noqa: BLE001 — 压缩失败退回未缩放原图
            data = png_bytes
            mime = "image/png"

    width = _png_width(data) if mime == "image/png" else None
    if len(data) > SCREENSHOT_VISION_MAX_BYTES or (
        width is not None and width > SCREENSHOT_VISION_MAX_WIDTH
    ):
        return {"vision_skipped": "too_large"}
    encoded = base64.b64encode(data).decode("ascii")
    return {
        "image_data_url": f"data:{mime};base64,{encoded}",
        "image_bytes": len(data),
    }


def _locate_tab(
    pages: List[Dict[str, Any]], tab_id: str, index: Optional[int]
) -> Dict[str, Any]:
    """在 ``_list_page_targets`` 结果中定位标签页（tab_id 优先，其次 1-based index）。"""
    if tab_id:
        for info in pages:
            if info.get("targetId") == tab_id:
                return info
        raise BrowserCDPError(f"未知 tab_id: {tab_id}")
    if index is not None:
        if index < 1 or index > len(pages):
            raise BrowserCDPError(
                f"index 超出范围: {index}（当前 {len(pages)} 个标签页）"
            )
        return pages[index - 1]
    raise BrowserCDPError("需要 tab_id 或 index")


def _interact_arg_error(
    action: str,
    selector: str,
    text: str,
    value: str,
    key: str,
    ref: str,
    path: str = "",
) -> Optional[str]:
    """按动作返回参数错误文案；None 表示放行。"""
    located = bool(ref or selector)
    error: Optional[str] = None
    if action not in _VALID_ACTIONS:
        error = f"action 必须是 {', '.join(_VALID_ACTIONS)}"
    elif action == "click":
        if not located and not text:
            error = "click 需要 ref、selector 或 text 之一"
    elif action == "type":
        if not located:
            error = "type 需要 ref 或 selector"
        elif not isinstance(value, str) or value == "":
            error = "type 需要 value（输入内容）"
    elif action == "select":
        if not located:
            error = "select 需要 ref 或 selector"
        elif not isinstance(value, str) or value == "":
            error = "select 需要 value（option 的 value 或文本）"
    elif action == "upload":
        if not located:
            error = "upload 需要 ref 或 selector"
        elif not (path or value):
            error = "upload 需要 path（工作区内文件路径，也可复用 value）"
    elif action in ("hover", "check", "uncheck"):
        if not located:
            error = f"{action} 需要 ref 或 selector"
    elif action == "attr":
        if not located:
            error = "attr 需要 ref 或 selector"
    elif action == "press":
        if not isinstance(key, str) or not key:
            error = "press 需要 key"
    elif action == "scroll":
        try:
            int(value)
        except (TypeError, ValueError):
            error = "scroll 的 value 必须是整数像素"
    return error


def _validate_interact_args(
    kwargs: Dict[str, Any],
    action: str,
    selector: str,
    text: str,
    value: str,
    key: str,
    ref: str,
    path: str = "",
) -> Optional[ToolResult]:
    """browser_interact 参数校验；返回拒绝结果或 None（放行）。

    定位优先级 ref > selector > text：三者同时给出不报错（按优先级取用），
    但 click/type/select/hover/check/uncheck 至少要有 ref 或 selector
    （click 也可用 text）。upload 还需要 path（或复用 value）。
    """
    if kwargs:
        return ToolResult(
            success=False,
            error=f"未知参数: {', '.join(sorted(kwargs))}",
        )
    error = _interact_arg_error(action, selector, text, value, key, ref, path)
    return None if error is None else ToolResult(success=False, error=error)


def _expression_with_page_info(expression: str) -> str:
    """把交互 JS 结果补上当前 url/title（保留原有 ok/info 字段）。"""
    return (
        "(function(){var __sage=(" + expression + ");"
        "try{__sage.url=location.href;__sage.title=document.title;}catch(e){}"
        "return __sage;})()"
    )


def _build_interact_expression(  # noqa: PLR0911 — 每个动作分支独立返回，扁平更直读
    action: str,
    selector: str,
    text: str,
    value: str,
    key: str,
    clear: bool,
    ref: str,
    name: str = "",
    frame_owner: Optional[Dict[str, str]] = None,
) -> str:
    """按定位优先级构造交互 JS（ref > selector > text，scroll 无定位）。

    ``frame_owner`` 非空表示 ref 来自子 frame：用 data 属性定位、在目标
    frame 的隔离世界执行，且不附加页面 url/title（保持顶层页面缓存）。
    """
    frame_name = str((frame_owner or {}).get("name") or "")
    if action == "attr":
        snippet = _js_attr_element(name or "href")
        if ref and frame_owner:
            return build_frame_ref_expression(snippet, ref, frame_name)
        if ref:
            return _expression_with_page_info(build_ref_expression(snippet, ref))
        return _expression_with_page_info(_js_on_selector(selector, snippet))
    if action == "click":
        if ref and frame_owner:
            return build_frame_ref_expression(_js_click_element(), ref, frame_name)
        expression = (
            build_ref_expression(_js_click_element(), ref)
            if ref
            else _js_click(selector=selector, text=text)
        )
        return _expression_with_page_info(expression)
    if action == "scroll":
        # 子 frame 内滚动不写 page 信息：否则 frame 的 url/title 会被当成
        # 顶层页面写回 _LAST_PAGE。
        if frame_owner:
            return _js_scroll(int(value))
        return _expression_with_page_info(_js_scroll(int(value)))
    if action == "press" and not ref and not selector:
        return _expression_with_page_info(_js_press(key))

    if action == "type":
        snippet = _js_type_element(value, bool(clear))
    elif action == "select":
        snippet = _js_select_element(value)
    elif action == "hover":
        snippet = _js_hover_element()
    elif action == "check":
        snippet = _js_set_checked_element(True)
    elif action == "uncheck":
        snippet = _js_set_checked_element(False)
    else:  # press（有 ref 或 selector）
        snippet = _js_press_element(key)

    if ref:
        if frame_owner:
            return build_frame_ref_expression(snippet, ref, frame_name)
        return _expression_with_page_info(build_ref_expression(snippet, ref))
    return _expression_with_page_info(_js_on_selector(selector, snippet))


def _wait_after_click(session: BrowserSession) -> None:
    """点击后的就绪等待：有子 frame 等全帧稳定，否则沿用顶层网络空闲等待。

    被封禁/待确认的 frame 不参与探活（不读取其 DOM，避免侧信道）。
    """
    try:
        frames = browser_frames.list_frames(session)
    except BrowserCDPError as exc:
        logger.debug("点击后 frame tree 不可用，回退网络空闲等待: %s", exc)
        frames = []
    if len(frames) > 1:
        frames_by_id = {frame.frame_id: frame for frame in frames}
        allowed = [
            frame
            for frame in frames
            if frame.is_main
            or _frame_site_decision(session.browser_id, frame, frames_by_id)[0] == "allow"
        ]
        browser_frames.wait_frames_settled(session, frames=allowed or frames[:1])
        return
    _wait_network_idle(session, None, timeout=5.0)


def _wait_page_settled(
    session: BrowserSession, target_id: Optional[str], wait_for: str = ""
) -> None:
    """navigate 后等页面可用（readyState + 正文稳定，见 web_render.wait_page_ready）。

    SPA 的 hydrate 发生在 readyState=complete 之后 —— 只等 readyState 会
    拿到半空页面，稳定等待逻辑统一收口在 web_render（渲染分支共用，W2）。
    ``wait_for``（R2）为 CSS 选择器：出现才继续（超时不失败）。
    """
    wait_page_ready(session, target_id, wait_for=wait_for)


# ---------------------------------------------------------------------------
# 工具定义
# ---------------------------------------------------------------------------


class BrowserLaunchTool(BaseTool):
    """启动一个受控浏览器实例（默认临时 profile，可选持久 profile）。"""

    risk = RiskClass.EXEC
    is_blocking = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="browser_launch",
            description=(
                "启动一个受控浏览器实例（Chrome/Edge）。默认独立临时配置目录，"
                "关闭即清理；persistent=true 使用持久 profile（登录态跨会话"
                "保留，适合先登录再抓取的场景）。返回 browser_id，后续 "
                "browser_* 工具用它与浏览器交互。headless 默认 true（无窗口）；"
                "需要可视化调试或手动登录时传 false。注意：若用户已在浏览器"
                "扩展中共享标签页，browser_* 工具会自动优先使用共享标签页；"
                "本工具会另行启动独立实例（用返回的 browser_id 显式指定它）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "headless": {"type": "boolean", "description": "无头模式（默认 true）"},
                    "persistent": {
                        "type": "boolean",
                        "description": "持久 profile，登录态跨会话保留（默认 false）",
                    },
                    "profile_name": {
                        "type": "string",
                        "description": "持久 profile 名称（不传时自动选择可用目录）",
                    },
                },
                "required": [],
            },
        )

    @_leased
    def execute(
        self,
        headless: bool = True,
        persistent: bool = False,
        profile_name: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        if kwargs:
            return ToolResult(
                success=False,
                error=(
                    f"未知参数: {', '.join(sorted(kwargs))}"
                    "（合法参数: headless, persistent, profile_name）"
                ),
            )
        try:
            session = launch_browser(
                headless=bool(headless),
                persistent=bool(persistent),
                profile_name=(str(profile_name).strip() or None),
                owner=_current_owner(),
            )
        except BrowserCDPError as exc:
            return _error(exc)

        # 下载黑洞修复：把浏览器内触发的下载重定向到工作区（或数据目录下按
        # 浏览器实例分目录），否则文件落在临时 profile 目录，browser_close
        # 时一并被删；不同会话的下载也不再互相覆盖。
        root = self._policy.workspace_root
        download_dir = _apply_download_behavior(session, root)

        # SN3：常驻事件通道跟踪下载（downloadWillBegin / downloadProgress）。
        # embedded 也走同一 WS 通道（P2 桥已支持事件升级）。
        tracker = start_download_tracking(
            session.browser_id, session.port, session.ws_path, str(download_dir)
        )
        if not tracker.connected:
            logger.warning(
                "下载事件通道未建立（browser_downloads 将退化为目录列举）: %s",
                tracker.error,
            )

        if getattr(session, "browser_type", "") == "embedded":
            note = "使用 Sage 内置浏览器；cookie/localStorage 共享持久分区，browser_close 不会清除。"
        else:
            note = "用 browser_navigate 打开页面；browser_close 结束会话。"
            if session.persistent:
                note += "持久 profile 关闭后登录态保留。"

        return ToolResult(
            success=True,
            content={
                "browser_id": session.browser_id,
                "executable": session.executable,
                "headless": session.headless,
                "persistent": session.persistent,
                "profile_dir": session.user_data_dir,
                "download_dir": str(download_dir),
                "download_tracking": bool(tracker is not None and tracker.connected),
                "note": note,
            },
        )


class BrowserNavigateTool(BaseTool):
    """导航到 URL（http/https/about/data；拒绝 file:// 等本地 scheme）。"""

    risk = RiskClass.EXTERNAL
    is_blocking = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="browser_navigate",
            description=(
                "让受控浏览器打开 URL（仅 http/https/about/data；file:// "
                "被拒绝；受网络模式门禁约束，OFFLINE/白名单外拒绝）。等待"
                "页面就绪（含 SPA 渲染稳定）后返回标题与最终 URL。多实例时"
                "传 browser_id。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "目标 URL"},
                    "browser_id": {
                        "type": "string",
                        "description": "browser_launch 返回的 id（单实例可省略）",
                    },
                    "new_tab": {
                        "type": "boolean",
                        "description": "在新标签页打开（默认 false，用当前页）",
                    },
                    "wait_for": {
                        "type": "string",
                        "description": "CSS 选择器：等它出现再返回（默认空 = 就绪+稳定即返回）",
                    },
                },
                "required": ["url"],
            },
        )

    @_leased
    def execute(  # noqa: PLR0911 — 每个拒绝路径独立 return，扁平比提取辅助函数更直读
        self,
        url: str = "",
        browser_id: str = "",
        new_tab: bool = False,
        wait_for: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        if kwargs:
            return ToolResult(
                success=False,
                error=(
                    f"未知参数: {', '.join(sorted(kwargs))}"
                    "（合法参数: url, browser_id, new_tab, wait_for）"
                ),
            )
        scheme_error = validate_url(url)
        if scheme_error is not None:
            return ToolResult(success=False, error=scheme_error)
        # 网络模式门禁，与 web_fetch 同口径（W4）：仅 http/https 出网导航受
        # check_host 约束，否则离线/内网白名单模式下浏览器可绕过 web_fetch
        # 的注册门禁。about:/data: 无网络访问不在此列 —— check_host 解析不
        # 出其主机名，会误伤 G7 明确允许的测试导航。
        if (urlsplit(url.strip()).scheme or "").lower() in ("http", "https"):
            network_rejection = load_network_policy().check_host(url)
            if network_rejection:
                return ToolResult(success=False, error=network_rejection)
        # 可见受控浏览器（M3）：门禁全部通过且当前会话没有可用浏览器时自动
        # 拉起（实例归属当前聊天会话）。同一会话的"检查 + 拉起"持锁串行，
        # 避免并发首次导航各开一个、随后又因多实例无法解析而双报错。
        owner = _current_owner()
        if not browser_id and not _has_usable_browser_session(owner):
            with _owner_launch_lock(owner):
                if not _has_usable_browser_session(owner):
                    try:
                        launch_browser(
                            headless=not _browser_default_visible(),
                            persistent=False,
                            profile_name=None,
                            owner=owner,
                        )
                    except BrowserCDPError as exc:
                        return _error(exc)
        session: Optional[BrowserSession] = None
        started = time.monotonic()
        try:
            session = _resolve_session(browser_id or None)
            # 自动拉起/复用会话后确保下载目录已设置——否则 Electron 内嵌桥
            # 会在 will-download 时弹保存对话框（受控窗口下无人可点 → 卡死）。
            _apply_download_behavior(session, self._policy.workspace_root)
            blocked = _blocked_by_control(session, "browser_navigate")
            if blocked is not None:
                return blocked
            # M4 站点授权：拒绝指纹优先（避免同一站点反复弹确认），
            # 其次持久/会话策略；未知站点 → 待用户确认。
            domain = browser_safety.domain_of(url)
            gate = _site_access_gate(session, url, domain, started)
            if gate is not None:
                return gate
            if new_tab:
                # 先建空白标签页，注入网络监控后再导航（确保 monkey-patch 早于页面脚本）
                created = cdp_command(
                    session, "Target.createTarget", {"url": "about:blank"}
                ).get("targetId")
                if not created:
                    return _meta_result(
                        ToolResult(success=False, error="新标签页创建失败"),
                        session,
                        "navigate",
                        url=url,
                    )
                session.active_target_id = created
                inject_network_monitor(session, created)
                nav = cdp_command(
                    session, "Page.navigate", {"url": url.strip()}
                )
                if nav.get("errorText"):
                    return _meta_result(
                        ToolResult(success=False, error=f"导航失败: {nav['errorText']}"),
                        session,
                        "navigate",
                        url=url,
                    )
                _wait_page_settled(session, created, wait_for)
                info = _evaluate_json(
                    session,
                    "JSON.stringify({url:location.href,title:document.title})",
                    created,
                )
            else:
                # 导航前注入网络空闲监控（覆盖 SPA AJAX 加载）
                inject_network_monitor(session, None)
                result = cdp_command(session, "Page.navigate", {"url": url.strip()})
                if result.get("errorText"):
                    return _meta_result(
                        ToolResult(success=False, error=f"导航失败: {result['errorText']}"),
                        session,
                        "navigate",
                        url=url,
                    )
                _wait_page_settled(session, None, wait_for)
                info = _evaluate_json(
                    session,
                    "JSON.stringify({url:location.href,title:document.title})",
                    None,
                )
            page = json.loads(info) if isinstance(info, str) else {}
        except BrowserCDPError as exc:
            return _meta_error(exc, session, "navigate")
        page_url = str(page.get("url") or url)
        page_title = str(page.get("title") or "")
        _remember_page(session, page_url, page_title)
        # 新页面上的旧 ref（含子 frame 归属）全部失效
        _SNAPSHOT_FRAME_REFS.pop(session.browser_id, None)
        # 302/短链/JS 跳转可能落到与请求不同的域名：对最终落地域名重跑
        # 站点授权（block → site_blocked；confirm → 站点确认 + paused），
        # 否则允许域名重定向到禁止域名即可绕过策略。
        final_domain = browser_safety.domain_of(page_url)
        if final_domain and final_domain != domain:
            redirect_gate = _site_access_gate(session, page_url, final_domain, started)
            if redirect_gate is not None:
                return redirect_gate
        thumbnail = _capture_step_thumbnail(session)
        _record_browser_audit(
            session,
            "browser_navigate",
            "navigate",
            "ok",
            domain=browser_safety.domain_of(page_url),
            duration_ms=_elapsed_ms(started),
        )
        return _meta_result(
            ToolResult(
                success=True,
                content={"url": page.get("url", url), "title": page.get("title", "")},
            ),
            session,
            "navigate",
            url=page_url,
            title=page_title,
            screenshot_path=thumbnail,
        )


def _coerce_frame_payload(value: Any) -> Optional[Dict[str, Any]]:
    """把 frame 快照返回值（dict 或 JSON 字符串）归一为 dict；异常返回 None。"""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _frame_site_decision(  # noqa: PLR0911 — 来源判定各分支独立早退
    session_id: str,
    frame: browser_frames.FrameInfo,
    frames_by_id: Dict[str, browser_frames.FrameInfo],
    url_override: str = "",
    origin_override: str = "",
) -> Tuple[str, str]:
    """子 frame 的站点策略判定；返回 ``(decision, policy_url)``。

    优先级：本次采集到的真实 ``location.origin`` → CDP ``securityOrigin`` →
    本次 ``location.href`` → frame tree 的 ``url``。originless frame
    （about:blank / srcdoc / data: / 空 URL）继承最近有 host 的祖先 frame 的
    判定；scheme 不在白名单或无法确定来源时 fail-closed（block）。
    """
    candidates = (origin_override, frame.security_origin, url_override, frame.url)
    for candidate in candidates:
        text = str(candidate or "").strip()
        if not text:
            continue
        try:
            parts = urlsplit(text)
        except ValueError:
            return "block", text
        scheme = (parts.scheme or "").lower()
        if scheme and scheme not in _ALLOWED_FRAME_SCHEMES:
            return "block", text
        if parts.hostname:
            return _safety_check_site(session_id, text), text

    ancestor = frames_by_id.get(frame.parent_id)
    visited = set()
    while ancestor is not None and ancestor.frame_id not in visited:
        visited.add(ancestor.frame_id)
        for candidate in (ancestor.security_origin, ancestor.url):
            text = str(candidate or "").strip()
            if not text:
                continue
            try:
                parts = urlsplit(text)
            except ValueError:
                return "block", text
            scheme = (parts.scheme or "").lower()
            if scheme and scheme not in _ALLOWED_FRAME_SCHEMES:
                return "block", text
            if parts.hostname:
                return _safety_check_site(session_id, text), text
        ancestor = frames_by_id.get(ancestor.parent_id)
    return "block", frame.url or str(url_override or "")


def _collect_frame_snapshot(
    session: BrowserSession,
    main_payload: Dict[str, Any],
    mode: str,
    include_offscreen: bool,
) -> Optional[
    Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Dict[str, str]]]
]:
    """CDP 巡检所有子 frame 的快照（跨域 / frameset / 多层嵌套）。

    返回 ``(payloads, frames_meta, ref_map)``；``payloads`` 与 ``frames_meta``
    一一对应（被策略拦截或读取失败的 frame 对应空 payload）。CDP frame API
    不可用时返回 ``None``，由调用方回退页面内同源 iframe 遍历。
    """
    try:
        frames = browser_frames.list_frames(session)
    except BrowserCDPError as exc:
        logger.debug("CDP frame tree 不可用，回退页面内 iframe 遍历: %s", exc)
        return None
    children = [frame for frame in frames if not frame.is_main]
    if not children:
        return [], [], {}
    frames_by_id = {frame.frame_id: frame for frame in frames}
    try:
        next_ref = max(1, int(main_payload.get("next_ref") or 0))
    except (TypeError, ValueError):
        next_ref = 1

    payloads: List[Dict[str, Any]] = []
    metas: List[Dict[str, Any]] = []
    ref_map: Dict[str, Dict[str, str]] = {}
    scanned_children = children[: browser_frames.MAX_FRAMES]
    truncated_children = children[browser_frames.MAX_FRAMES :]
    for frame in scanned_children:
        meta: Dict[str, Any] = {
            "frame_id": frame.frame_id,
            "url": frame.url,
            "name": frame.name,
            "state": "scanned",
            "elements": 0,
            "text_len": 0,
        }
        # 跨 frame 读取绕过同源策略：按真实来源（securityOrigin / 祖先继承）判定，
        # 非 allow 一律不读内容。
        decision, policy_url = _frame_site_decision(
            session.browser_id, frame, frames_by_id
        )
        meta["policy_url"] = policy_url
        if decision != "allow":
            meta["state"] = "blocked" if decision == "block" else "needs_confirmation"
            payloads.append({})
            metas.append(meta)
            continue
        try:
            context_id = browser_frames.create_world(session, frame.frame_id)
            expression = build_snapshot_expression(
                mode=mode,
                max_collect=SNAPSHOT_HARD_COLLECT_CAP,
                include_offscreen=include_offscreen,
                include_iframes=False,
                ref_offset=next_ref,
                frame_url=frame.url,
            )
            payload = _coerce_frame_payload(
                browser_frames.evaluate_in_context(session, expression, context_id)
            )
            if payload is None:
                raise BrowserCDPError("frame 快照返回异常")
        except BrowserCDPError as exc:
            logger.debug("frame 快照失败 frame=%s: %s", frame.frame_id, exc)
            meta["state"] = "error"
            payloads.append({})
            metas.append(meta)
            continue
        # TOCTOU 防护：payload 自带采集时刻的 location.origin/href；来源在检查后
        # 发生变化（frame 自导航到被禁站点）时丢弃本次内容。
        decision, policy_url = _frame_site_decision(
            session.browser_id,
            frame,
            frames_by_id,
            url_override=str(payload.get("url") or ""),
            origin_override=str(payload.get("origin") or ""),
        )
        meta["policy_url"] = policy_url
        if decision != "allow":
            meta["state"] = "blocked" if decision == "block" else "needs_confirmation"
            payloads.append({})
            metas.append(meta)
            continue
        payloads.append(payload)
        metas.append(meta)
        elements = [item for item in payload.get("elements") or [] if isinstance(item, dict)]
        meta["elements"] = len(elements)
        meta["text_len"] = len(str(payload.get("text") or ""))
        for item in elements:
            ref = str(item.get("ref") or "")
            if ref:
                ref_map[ref] = {
                    "frame_id": frame.frame_id,
                    "frame_url": frame.url,
                    "policy_url": policy_url,
                    "name": str(item.get("name") or ""),
                }
        try:
            next_ref = max(next_ref, int(payload.get("next_ref") or 0))
        except (TypeError, ValueError):
            continue

    for frame in truncated_children:
        payloads.append({})
        metas.append(
            {
                "frame_id": frame.frame_id,
                "url": frame.url,
                "name": frame.name,
                "state": "truncated",
                "elements": 0,
                "text_len": 0,
            }
        )
    return payloads, metas, ref_map


class BrowserSnapshotTool(BaseTool):
    """读取当前页面：无障碍树交互元素（带 ref）/ 文本正文。"""

    risk = RiskClass.READ
    is_blocking = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="browser_snapshot",
            description=(
                "看页面主入口。默认 mode=interactive：返回当前页面可交互元素的"
                "无障碍树列表（每个元素带 ref、role、可访问名与状态），交互工具"
                "应优先用 ref 定位；动作后页面可能变化，应重新快照确认。"
                "mode=text 只返回正文文本（上限 30KiB，超出标记 truncated）；"
                "mode=full 同时返回元素与文本。可用 query 按 role/名称过滤，"
                "max_nodes 限制返回节点数（1-500），include_offscreen 是否包含"
                "视口外元素。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["interactive", "text", "full"],
                        "description": "interactive（默认，带 ref 的元素列表）| text | full",
                    },
                    "max_nodes": {
                        "type": "integer",
                        "description": "最多返回节点数（默认 120，钳位 1-500）",
                    },
                    "query": {
                        "type": "string",
                        "description": "按 role / 可访问名小写子串过滤",
                    },
                    "include_offscreen": {
                        "type": "boolean",
                        "description": "包含视口外元素（默认 false）",
                    },
                    "browser_id": {"type": "string", "description": "单实例可省略"},
                },
                "required": [],
            },
        )

    @_leased
    def execute(  # noqa: PLR0911 — 门禁/校验各走独立早退分支，扁平更直读
        self,
        mode: str = "interactive",
        max_nodes: int = SNAPSHOT_INTERACTIVE_MAX_DEFAULT,
        query: str = "",
        include_offscreen: bool = False,
        browser_id: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        if kwargs:
            return ToolResult(
                success=False,
                error=(
                    f"未知参数: {', '.join(sorted(kwargs))}"
                    "（合法参数: mode, max_nodes, query, include_offscreen, browser_id）"
                ),
            )
        if mode not in _VALID_SNAPSHOT_MODES:
            return ToolResult(
                success=False,
                error=f"mode 必须是 {', '.join(_VALID_SNAPSHOT_MODES)}",
            )
        session: Optional[BrowserSession] = None
        try:
            session = _resolve_session(browser_id or None)
            blocked = _blocked_by_control(session, "browser_snapshot")
            if blocked is not None:
                return blocked
            # I1：当前页面域名被持久策略禁止时，snapshot 不得读取页面内容
            site_blocked = _site_blocked_result(session, "snapshot")
            if site_blocked is not None:
                return site_blocked
            expression = build_snapshot_expression(
                mode=mode,
                max_collect=SNAPSHOT_HARD_COLLECT_CAP,
                include_offscreen=bool(include_offscreen),
                include_iframes=False,
            )
            raw_payload = _evaluate_json(session, expression, None)
            payload_dict = _coerce_frame_payload(raw_payload)
            if payload_dict is None:
                # 非 JSON 交由 parse_snapshot_payload 统一报错，不重复抓取
                payload: Any = raw_payload
                _SNAPSHOT_FRAME_REFS.pop(session.browser_id, None)
            else:
                frame_result = _collect_frame_snapshot(
                    session, payload_dict, mode, bool(include_offscreen)
                )
                if frame_result is None:
                    # CDP frame API 不可用：回退页面内同源 iframe 遍历（旧路径）
                    payload = _evaluate_json(
                        session,
                        build_snapshot_expression(
                            mode=mode,
                            max_collect=SNAPSHOT_HARD_COLLECT_CAP,
                            include_offscreen=bool(include_offscreen),
                            include_iframes=True,
                        ),
                        None,
                    )
                    _SNAPSHOT_FRAME_REFS.pop(session.browser_id, None)
                else:
                    frame_payloads, frames_meta, ref_map = frame_result
                    if frame_payloads:
                        payload = merge_snapshot_payloads(
                            payload_dict, frame_payloads, frames_meta
                        )
                    elif frames_meta:
                        payload = dict(payload_dict)
                        payload["frames"] = frames_meta
                    else:
                        payload = payload_dict
                    if any(meta.get("state") == "truncated" for meta in frames_meta):
                        payload["iframes_truncated"] = True
                    _SNAPSHOT_FRAME_REFS[session.browser_id] = ref_map
        except BrowserCDPError as exc:
            return _meta_error(exc, session, "snapshot")
        content = parse_snapshot_payload(
            payload,
            mode=mode,
            max_nodes=max_nodes,
            query=query,
            include_offscreen=bool(include_offscreen),
        )
        if content.get("error"):
            return _meta_result(
                ToolResult(success=False, error=str(content["error"])), session, "snapshot"
            )
        pending_frames = [
            frame
            for frame in content.get("frames") or []
            if isinstance(frame, dict)
            and frame.get("state") in ("blocked", "needs_confirmation")
        ]
        if pending_frames:
            note = "；".join(
                f"{frame.get('state')}: {browser_safety.domain_of(str(frame.get('url') or ''))}"
                for frame in pending_frames
            )
            hint = str(content.get("hint") or "")
            content["hint"] = (hint + "；" if hint else "") + (
                f"部分子 frame 未读取（{note}）；可在设置→网络→浏览器站点策略中放行"
            )
        # M4 注入告警：命中只标注 trust/injection_warning，保留原有字段，不阻断
        injection_warning = browser_safety.scan_untrusted_text(
            _snapshot_untrusted_text(content)
        )
        if injection_warning:
            content["trust"] = "untrusted"
            content["injection_warning"] = injection_warning
        page_url = str(content.get("url") or "")
        page_title = str(content.get("title") or "")
        _remember_page(session, page_url, page_title)
        # mode=text 不带元素列表 —— 保留上一次快照的登录墙判定，不误清
        if "elements" in content:
            _LAST_LOGIN_WALL[session.browser_id] = _detect_login_wall(content.get("elements"))
        _record_browser_audit(
            session,
            "browser_snapshot",
            mode,
            "ok",
            domain=browser_safety.domain_of(page_url),
            target_desc=page_title,
        )
        return _meta_result(
            ToolResult(success=True, content=content),
            session,
            "snapshot",
            url=page_url,
            title=page_title,
        )


class BrowserInteractTool(BaseTool):
    """点击 / 输入 / 按键 / 滚动 / 选择 / 悬停 / 勾选（ref 优先）。"""

    risk = RiskClass.WRITE_LOCAL
    is_blocking = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="browser_interact",
            description=(
                "与当前页面交互。首选 ref（browser_snapshot 返回的元素引用）；"
                "也可用 selector（CSS）或 text（可见文本精确匹配）定位，优先级 "
                "ref > selector > text。action=click | type | press | scroll | "
                "select | hover | check | uncheck | upload。type 需 value（React "
                "兼容，clear=true 先清空）；press 支持组合键（Control+A / "
                "Shift+Tab / Meta+Enter）；select 的 value 为 option 的 value 或"
                "文本；scroll 的 value 为像素（正下负上）；upload 需 path（仅允许"
                "工作区内文件，目标须为 input[type=file]，且需用户确认）。操作后"
                "请重新 browser_snapshot 确认效果（页面变化会使旧 ref 失效）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "click",
                            "type",
                            "press",
                            "scroll",
                            "select",
                            "hover",
                            "check",
                            "uncheck",
                            "upload",
                            "attr",
                        ],
                        "description": "要执行的动作",
                    },
                    "name": {
                        "type": "string",
                        "description": "attr 动作要读取的元素属性名（默认 href）",
                    },
                    "ref": {
                        "type": "string",
                        "description": "browser_snapshot 返回的元素引用（优先于 selector/text）",
                    },
                    "selector": {"type": "string", "description": "CSS 选择器（回退定位）"},
                    "text": {
                        "type": "string",
                        "description": "按可见文本定位（click 用，ref/selector 缺省时生效）",
                    },
                    "value": {
                        "type": "string",
                        "description": "type/select 的目标值 / scroll 的像素 / upload 的路径",
                    },
                    "path": {
                        "type": "string",
                        "description": "upload 的文件路径（相对工作区，也可复用 value）",
                    },
                    "key": {
                        "type": "string",
                        "description": "press 的键名，支持组合键（如 Control+A）",
                    },
                    "clear": {"type": "boolean", "description": "type 前先清空（默认 false）"},
                    "browser_id": {"type": "string", "description": "单实例可省略"},
                },
                "required": ["action"],
            },
        )

    @_leased
    def execute(  # noqa: PLR0911 — 每个校验/门禁路径独立 return，扁平更直读
        self,
        action: str = "",
        selector: str = "",
        text: str = "",
        value: str = "",
        key: str = "",
        clear: bool = False,
        ref: str = "",
        browser_id: str = "",
        path: str = "",
        name: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        rejection = _validate_interact_args(
            kwargs, action, selector, text, value, key, ref, path
        )
        if rejection is not None:
            return rejection
        name = (name or "").strip() or "href"

        upload_file: Optional[Path] = None
        expression = ""
        if action == "upload":
            root = self._policy.workspace_root
            if not root:
                return ToolResult(
                    success=False, error="browser_interact upload 需要绑定工作区（workspace）"
                )
            raw_path = str(path or value)
            candidate = Path(raw_path).expanduser()
            if not candidate.is_absolute():
                candidate = Path(root) / candidate
            blocked = self._enforce_workspace(str(candidate))
            if blocked is not None:
                return blocked
            resolved = candidate.resolve()
            if not resolved.is_file():
                return ToolResult(
                    success=False, error=f"upload_file_not_found: {raw_path}"
                )
            upload_file = resolved
        session: Optional[BrowserSession] = None
        started = time.monotonic()
        try:
            session = _resolve_session(browser_id or None)
            blocked = _blocked_by_control(session, "browser_interact")
            if blocked is not None:
                return blocked
            # I1：当前页面域名被持久策略禁止时，交互不得作用于该页面
            site_blocked = _site_blocked_result(session, "interact")
            if site_blocked is not None:
                return site_blocked
            target_fields = {"target_ref": ref or selector, "target_name": text}
            frame_owner = (
                _SNAPSHOT_FRAME_REFS.get(session.browser_id, {}).get(str(ref))
                if ref
                else None
            )
            frame_context_id: Optional[int] = None
            if frame_owner:
                # 跨 frame 交互同样受站点策略约束：读 frame 当前 location（隔离
                # 世界可跨域读自身），按真实来源过门禁；来源不明一律拒绝。
                try:
                    frame_context_id = browser_frames.create_world(
                        session, frame_owner["frame_id"]
                    )
                    location = _coerce_frame_payload(
                        browser_frames.evaluate_in_context(
                            session, _FRAME_LOCATION_EXPRESSION, frame_context_id
                        )
                    )
                except BrowserCDPError as exc:
                    return _meta_error(exc, session, "interact")
                current_url = str((location or {}).get("href") or "")
                current_origin = str((location or {}).get("origin") or "")
                check_url = current_url
                if current_origin and urlsplit(current_origin).hostname:
                    check_url = current_origin
                if not check_url or not urlsplit(check_url).hostname:
                    check_url = str(
                        frame_owner.get("policy_url")
                        or frame_owner.get("frame_url")
                        or ""
                    )
                frame_gate = _site_access_gate(
                    session,
                    check_url,
                    browser_safety.domain_of(check_url),
                    started,
                    tool="browser_interact",
                )
                if frame_gate is not None:
                    return frame_gate
                if not browser_safety.domain_of(check_url):
                    return _meta_result(
                        ToolResult(
                            success=False,
                            error="site_blocked: 子 frame 来源无法确认，已拒绝交互",
                        ),
                        session,
                        "interact",
                        **target_fields,
                    )
            if action == "upload" and frame_owner:
                return _meta_result(
                    ToolResult(
                        success=False,
                        error=(
                            "upload 暂不支持子 frame 元素；"
                            "请先 browser_navigate 到 frame_url 再上传"
                        ),
                    ),
                    session,
                    "interact",
                    **target_fields,
                )
            if action != "upload":
                expression = _build_interact_expression(
                    action,
                    selector,
                    text,
                    value,
                    key,
                    bool(clear),
                    ref,
                    name=name,
                    frame_owner=frame_owner,
                )
            # M4 敏感动作：先取目标元数据再分类；hard_block 不允许用户放行。
            # 仅 press Enter/Return 需要读焦点元素（触发默认提交/点击语义），
            # 其他按键不产生副作用，省一次 Runtime.evaluate。
            press_enter = (
                action == "press" and str(key or "").strip().lower() in ("enter", "return")
            )
            target_meta = _read_target_metadata(
                session, ref=ref, selector=selector, use_focused=press_enter
            )
            metadata_unavailable = target_meta is None and not text
            if not target_meta and text:
                target_meta = {"name": text}
            verdict = browser_safety.classify_interact(
                action,
                target=target_meta,
                value=value,
                selector=selector,
                key=key,
                metadata_unavailable=metadata_unavailable,
            )
            cached_url, cached_title = _cached_page(session)
            domain = browser_safety.domain_of(cached_url)
            target_name = (
                str(target_meta.get("name") or "") if isinstance(target_meta, dict) else ""
            ) or text
            # I2：批准指纹绑定会话；upload/select 额外绑定解析后的路径/目标值，
            # 防止「批准上传 A」被重放为上传 B 或替换选项值。
            approval_scope = ""
            if action == "upload" and upload_file is not None:
                approval_scope = str(upload_file)
            elif action == "select":
                approval_scope = str(value or "")
            # MEDIUM：批准指纹绑定 frame 身份，防止同一 ref 序号跨 frame 复用
            # 造成「批了 A frame 的提交、被重放到 B frame」。
            if frame_owner:
                frame_scope = (
                    "frame:"
                    + str(frame_owner.get("frame_id") or "")
                    + "|"
                    + str(frame_owner.get("policy_url") or frame_owner.get("frame_url") or "")
                )
                approval_scope = (
                    approval_scope + "|" + frame_scope if approval_scope else frame_scope
                )
            fingerprint = browser_safety.action_fingerprint(
                "browser_interact",
                action,
                domain,
                ref,
                selector,
                target_name,
                session_id=session.browser_id,
                scope=approval_scope,
            )
            registry = browser_safety.get_confirmation_registry()
            audit_target = {
                "target_ref": ref or selector,
                "target_desc": target_name or cached_title,
                "domain": domain,
            }
            approval = "auto"
            if verdict.kind == "hard_block":
                _record_browser_audit(
                    session,
                    "browser_interact",
                    action,
                    "blocked",
                    approval="none",
                    duration_ms=_elapsed_ms(started),
                    **audit_target,
                )
                return _meta_result(
                    ToolResult(
                        success=False,
                        error=(
                            f"hard_blocked: {verdict.description}；请用户接管完成"
                            "（browser_login 或控制面板接管）"
                        ),
                    ),
                    session,
                    "interact",
                    **target_fields,
                )
            if verdict.kind == "confirm":
                if not registry.consume_approval(fingerprint, session.browser_id):
                    if registry.is_denied(fingerprint, session.browser_id):
                        # 用户拒绝后暂停会话：被拒绝的页面/动作不得继续被读取。
                        get_browser_control().set_state(
                            session.browser_id, BrowserControlState.PAUSED
                        )
                        _record_browser_audit(
                            session,
                            "browser_interact",
                            action,
                            "blocked",
                            approval="denied",
                            duration_ms=_elapsed_ms(started),
                            **audit_target,
                        )
                        return _meta_result(
                            ToolResult(
                                success=False,
                                error="denied_by_user: 用户拒绝了该操作，请换一种方式或询问用户",
                            ),
                            session,
                            "interact",
                            **target_fields,
                        )
                    if action == "upload" and upload_file is not None:
                        # 描述里带解析后的文件名，用户才能确认「传的是哪个文件」。
                        description = (
                            f"上传文件 {upload_file.name}"
                            f"（{target_name or '文件输入框'} @ {cached_url}）"
                        )
                    else:
                        description = (
                            f"{verdict.description}（{target_name or action} @ {cached_url}）"
                        )
                    pending = registry.create(
                        session.browser_id,
                        "sensitive_action",
                        code=verdict.code,
                        domain=domain,
                        description=description,
                        options=list(browser_safety.SENSITIVE_ACTION_OPTIONS),
                        screenshot_path=_capture_step_thumbnail(session) or "",
                        fingerprint=fingerprint,
                    )
                    get_browser_control().set_state(
                        session.browser_id, BrowserControlState.PAUSED
                    )
                    _record_browser_audit(
                        session,
                        "browser_interact",
                        action,
                        "confirm_required",
                        approval="none",
                        duration_ms=_elapsed_ms(started),
                        **audit_target,
                    )
                    return _meta_result(
                        ToolResult(
                            success=False,
                            error=(
                                f"needs_confirmation: {pending.id} {pending.description}"
                                "（请在右栏浏览器面板确认）"
                            ),
                        ),
                        session,
                        "interact",
                        **target_fields,
                    )
                approval = "approved"
            if action == "upload":
                if upload_file is None:
                    # 参数层已解析；-O 下 assert 会被移除，这里显式兜底。
                    return ToolResult(success=False, error="upload_file_not_found: 未解析到上传文件")
                info_text = _upload_file_to_input(session, ref, selector, upload_file)
                page_url, page_title = _cached_page(session)
                outcome = {
                    "ok": True,
                    "info": info_text,
                    "url": page_url,
                    "title": page_title,
                }
            elif frame_owner:
                context_id = (
                    frame_context_id
                    if frame_context_id is not None
                    else browser_frames.create_world(session, frame_owner["frame_id"])
                )
                outcome = browser_frames.evaluate_in_context(
                    session, expression, context_id
                )
            else:
                outcome = _evaluate_json(session, expression, None)
        except BrowserCDPError as exc:
            return _meta_error(exc, session, "interact")
        if not isinstance(outcome, dict):
            _record_browser_audit(
                session,
                "browser_interact",
                action,
                "error",
                approval=approval,
                duration_ms=_elapsed_ms(started),
                **audit_target,
            )
            return _meta_result(
                ToolResult(success=False, error="交互结果异常（非 JSON）"),
                session,
                "interact",
                **target_fields,
            )
        page_url = str(outcome.get("url") or "")
        page_title = str(outcome.get("title") or "")
        if frame_owner and outcome.get("ok"):
            # 子 frame 动作可能触发顶层导航（target=_top 等）：补读顶层 URL，
            # 让随后的 I1 站点门禁与页面缓存更新仍然生效。
            try:
                top_info = _evaluate_json(
                    session, "({url:location.href,title:document.title})", None
                )
            except BrowserCDPError as exc:
                logger.debug("子 frame 交互后顶层 URL 读取失败: %s", exc)
                top_info = None
            if isinstance(top_info, dict):
                page_url = str(top_info.get("url") or page_url)
                page_title = str(top_info.get("title") or page_title)
        if page_url or page_title:
            _remember_page(session, page_url, page_title)
        info = outcome.get("info", "")
        if info == STALE_REF_INFO:
            _record_browser_audit(
                session,
                "browser_interact",
                action,
                "error",
                approval=approval,
                duration_ms=_elapsed_ms(started),
                **audit_target,
            )
            return _meta_result(
                ToolResult(success=False, error=STALE_REF_ERROR),
                session,
                "interact",
                url=page_url,
                title=page_title,
                **target_fields,
            )
        if not outcome.get("ok"):
            _record_browser_audit(
                session,
                "browser_interact",
                action,
                "error",
                approval=approval,
                duration_ms=_elapsed_ms(started),
                domain=domain or browser_safety.domain_of(page_url),
                target_ref=ref or selector,
                target_desc=target_name or page_title,
            )
            return _meta_result(
                ToolResult(
                    success=False,
                    error=f"交互未生效: {info or 'unknown'}（可用 browser_snapshot 查看页面结构）",
                ),
                session,
                "interact",
                url=page_url,
                title=page_title,
                **target_fields,
            )
        # I1：点击链接 / JS 跳转可能把页面带到新域名；交互成功后按最终 URL
        # 重跑站点门禁，避免「在允许站点点一个链接」绕过站点策略。
        # 在此之前，若 action 为 click，等待子 frame 导航/SPA AJAX 完成
        # （无子 frame 时退化为顶层网络空闲，最多 5 秒），确保后续站点门禁
        # 与 snapshot 能拿到正确 URL/内容。
        if action == "click" and outcome.get("ok"):
            # 就绪等待失败不阻断主流程，降级为不等待
            with contextlib.suppress(Exception):
                _wait_after_click(session)
        final_domain = browser_safety.domain_of(page_url)
        if page_url and final_domain and final_domain != domain:
            navigation_gate = _site_access_gate(session, page_url, final_domain, started)
            if navigation_gate is not None:
                return navigation_gate
        thumbnail = _capture_step_thumbnail(session)
        _record_browser_audit(
            session,
            "browser_interact",
            action,
            "ok",
            approval=approval,
            duration_ms=_elapsed_ms(started),
            domain=domain or browser_safety.domain_of(page_url),
            target_ref=ref or selector,
            target_desc=target_name or page_title,
        )
        return _meta_result(
            ToolResult(success=True, content={"action": action, "info": info}),
            session,
            "interact",
            url=page_url,
            title=page_title,
            screenshot_path=thumbnail,
            **target_fields,
        )


class BrowserScreenshotTool(BaseTool):
    """截取当前页面 PNG 到工作区（可作 artifact 预览）。"""

    risk = RiskClass.READ
    is_blocking = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="browser_screenshot",
            description=(
                "截取当前页面为 PNG，保存到工作区（默认 "
                "browser_screenshot_<时间戳>.png，可用 path 指定）。返回"
                "文件路径，可用 read_file/预览面板查看。return_image=true 时"
                "额外返回 data URL 供下一轮视觉识别（受 ≤1.5MB / 宽 ≤1568px "
                "约束）；full_page=true 尝试整页截图（不支持时回退视口）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "保存路径（相对工作区，可选）"},
                    "return_image": {
                        "type": "boolean",
                        "description": "附带 image_data_url 供视觉模型看当前画面（默认 false）",
                    },
                    "full_page": {
                        "type": "boolean",
                        "description": "尝试整页截图（captureBeyondViewport，默认 false）",
                    },
                    "browser_id": {"type": "string", "description": "单实例可省略"},
                },
                "required": [],
            },
        )

    @_leased
    def execute(  # noqa: PLR0911 — 多个早退错误分支更清晰
        self,
        path: str = "",
        browser_id: str = "",
        return_image: bool = False,
        full_page: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        if kwargs:
            return ToolResult(
                success=False,
                error=(
                    f"未知参数: {', '.join(sorted(kwargs))}"
                    "（合法参数: path, browser_id, return_image, full_page）"
                ),
            )
        # 工作区检查在前（纯本地、便宜）；会话解析在后（可能打 CDP）
        root = self._policy.workspace_root
        if not root:
            return ToolResult(success=False, error="browser_screenshot 需要绑定工作区（workspace）")

        session: Optional[BrowserSession] = None
        full_page_ok = False
        full_page_note = ""
        try:
            session = _resolve_session(browser_id or None)
            if path:
                target = Path(root) / path
            else:
                # 默认文件名带实例 id：多会话同一秒截图不再互相覆盖。
                target = Path(root) / (
                    f"browser_screenshot_{session.browser_id}_"
                    f"{time.strftime('%Y%m%d-%H%M%S')}.png"
                )
            blocked = self._enforce_workspace(str(target))
            if blocked is not None:
                return blocked
            blocked = _blocked_by_control(session, "browser_screenshot")
            if blocked is not None:
                return blocked
            # I1 补强：截图前复检当前页面域名，命中 block 策略时拒绝。
            # 防止 navigate 后页面已被禁、但截图仍可读内容的漏洞。
            blocked_site = _current_page_site_block(session, "screenshot")
            if blocked_site is not None:
                return blocked_site
            if bool(full_page):
                try:
                    result = cdp_command(
                        session,
                        "Page.captureScreenshot",
                        {"format": "png", "captureBeyondViewport": True},
                    )
                    full_page_ok = True
                except BrowserCDPError:
                    # embedded 桥的 capturePage 不支持全页 → 回退视口截图
                    result = cdp_command(session, "Page.captureScreenshot", {"format": "png"})
                    full_page_note = "整页截图不受支持，已回退为当前视口截图"
            else:
                result = cdp_command(session, "Page.captureScreenshot", {"format": "png"})
            png_bytes = base64.b64decode(result.get("data") or "")
        except BrowserCDPError as exc:
            return _meta_error(exc, session, "screenshot")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(png_bytes)
        except OSError as exc:
            return _meta_result(
                ToolResult(success=False, error=f"截图写入失败: {exc}"), session, "screenshot"
            )
        try:
            _record_artifact_safely(str(target), len(png_bytes))
        except Exception:  # noqa: BLE001 — artifact 记录失败不影响截图
            logger.warning("browser_screenshot artifact 记录失败", exc_info=True)
        resolved = str(target.resolve())
        content: Dict[str, Any] = {"path": resolved, "bytes": len(png_bytes)}
        if full_page:
            content["full_page"] = full_page_ok
            if full_page_note:
                content["full_page_note"] = full_page_note
        if bool(return_image):
            vision = _build_screenshot_vision_payload(png_bytes)
            content.update(vision)
            if vision.get("image_data_url"):
                content["attach_image_to_next_turn"] = True
        return _meta_result(
            ToolResult(success=True, content=content),
            session,
            "screenshot",
            screenshot_path=resolved,
        )


class BrowserCloseTool(BaseTool):
    """关闭标签页（target_id）或整个浏览器实例（browser_id）。"""

    risk = RiskClass.WRITE_LOCAL
    is_blocking = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="browser_close",
            description=(
                "关闭受控浏览器：只传 target_id 关闭单个标签页；传 browser_id"
                "（或不传，唯一实例时）关闭整个浏览器并清理临时目录。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "browser_id": {"type": "string", "description": "要关闭的实例（单实例可省略）"},
                    "target_id": {"type": "string", "description": "只关闭这个标签页"},
                },
                "required": [],
            },
        )

    @_leased
    def execute(  # noqa: PLR0911 — 每个拒绝路径独立 return，扁平更直读
        self, browser_id: str = "", target_id: str = "", **kwargs: Any
    ) -> ToolResult:
        if kwargs:
            return ToolResult(
                success=False,
                error=f"未知参数: {', '.join(sorted(kwargs))}（合法参数: browser_id, target_id）",
            )
        manager = get_browser_manager()
        try:
            session = _resolve_session(browser_id or None)
        except BrowserCDPError as exc:
            return _error(exc)

        if target_id:
            if getattr(session, "browser_type", None) == "external":
                return ToolResult(
                    success=False,
                    error="共享标签页由用户控制，Sage 无法关闭；请在浏览器扩展中停止共享",
                )
            try:
                cdp_command(session, "Target.closeTarget", {"targetId": target_id})
            except BrowserCDPError as exc:
                return _error(exc)
            # 控制器裁定：browser_close 保持门禁豁免，但单标签关闭不得让
            # Agent 借“关掉无关标签页”间接解除用户暂停/接管。因此仅当该
            # 会话已无剩余页面目标时才复位控制面；整机关闭始终复位。
            try:
                has_remaining_pages = bool(_list_page_targets(session))
            except BrowserCDPError:
                # 无法确认剩余页面时保守保留控制状态（宁可不复位）
                has_remaining_pages = True
            if not has_remaining_pages:
                get_browser_control().reset(session.browser_id)
                browser_safety.reset_session(session.browser_id)
            return ToolResult(success=True, content={"closed": "target", "target_id": target_id})

        if getattr(session, "browser_type", None) == "external":
            return ToolResult(
                success=False,
                error="共享标签页由用户控制，Sage 无法关闭；请在浏览器扩展中停止共享",
            )

        from .browser_cdp import _terminate_session

        manager.remove(session.browser_id)
        _terminate_session(session)
        # 控制面复位：关闭后不残留 paused/takeover，元数据缓存一并清理
        get_browser_control().reset(session.browser_id)
        browser_safety.reset_session(session.browser_id)
        _LAST_PAGE.pop(session.browser_id, None)
        _SNAPSHOT_FRAME_REFS.pop(session.browser_id, None)
        _LAST_LOGIN_WALL.pop(session.browser_id, None)
        return ToolResult(
            success=True,
            content={"closed": "browser", "browser_id": session.browser_id},
        )


class BrowserTabsTool(BaseTool):
    """标签页管理：列出 / 新建 / 切换 / 关闭受控浏览器的标签页。"""

    risk = RiskClass.WRITE_LOCAL
    is_blocking = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="browser_tabs",
            description=(
                "管理受控浏览器的标签页。action=list 列出所有标签页（active "
                "标记当前页）；create 新建标签页（url 可选，默认 about:blank）；"
                "switch 按 tab_id 或 index（1-based）切换活动标签页；close 关闭"
                "指定标签页。switch/create 之后，browser_snapshot / "
                "browser_interact 等工具默认作用于活动标签页。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "list | create | switch | close",
                    },
                    "url": {
                        "type": "string",
                        "description": "create 时的目标 URL（默认 about:blank）",
                    },
                    "tab_id": {
                        "type": "string",
                        "description": "switch/close 的目标标签页 id",
                    },
                    "index": {
                        "type": "integer",
                        "description": "switch/close 备用：1-based 序号（与 tab_id 二选一）",
                    },
                    "browser_id": {"type": "string", "description": "单实例可省略"},
                },
                "required": ["action"],
            },
        )

    @_leased
    def execute(  # noqa: PLR0911 — 每个拒绝路径独立 return，扁平更直读
        self,
        action: str = "",
        url: str = "",
        tab_id: str = "",
        index: Optional[int] = None,
        browser_id: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        if kwargs:
            return ToolResult(
                success=False,
                error=(
                    f"未知参数: {', '.join(sorted(kwargs))}"
                    "（合法参数: action, url, tab_id, index, browser_id）"
                ),
            )
        if action not in _VALID_TAB_ACTIONS:
            return ToolResult(
                success=False,
                error=f"action 必须是 {', '.join(_VALID_TAB_ACTIONS)}",
            )
        if index is not None:
            try:
                index = int(index)
            except (TypeError, ValueError):
                return ToolResult(success=False, error="index 必须是正整数")
        if action in ("switch", "close"):
            if tab_id and index is not None:
                return ToolResult(success=False, error="tab_id 与 index 只能二选一")
            if not tab_id and index is None:
                return ToolResult(success=False, error=f"{action} 需要 tab_id 或 index")
        target_url = ""
        if action == "create":
            target_url = (url or "").strip() or "about:blank"
            scheme_error = validate_url(target_url)
            if scheme_error is not None:
                return ToolResult(success=False, error=scheme_error)
            # 与 browser_navigate 同口径：http/https 出网受网络模式门禁约束，
            # 否则 create 可绕过离线/白名单模式。
            if (urlsplit(target_url).scheme or "").lower() in ("http", "https"):
                network_rejection = load_network_policy().check_host(target_url)
                if network_rejection:
                    return ToolResult(success=False, error=network_rejection)

        session: Optional[BrowserSession] = None
        started = time.monotonic()
        try:
            session = _resolve_session(browser_id or None)
            blocked = _blocked_by_control(session, "browser_tabs")
            if blocked is not None:
                return blocked
            if action == "list":
                return _meta_result(self._list_tabs(session), session, "tabs")
            if action == "create":
                # I1：新建标签页同样是导航，必须先过站点授权门禁
                # （block → site_blocked；confirm → 站点确认 + paused）。
                create_domain = browser_safety.domain_of(target_url)
                create_gate = _site_access_gate(session, target_url, create_domain, started)
                if create_gate is not None:
                    return create_gate
                created = cdp_command(
                    session, "Target.createTarget", {"url": target_url}
                ).get("targetId")
                if not created:
                    return _meta_result(
                        ToolResult(success=False, error="新标签页创建失败"),
                        session,
                        "tabs",
                        url=target_url,
                    )
                session.active_target_id = created
                _remember_page(session, target_url, "")
                _SNAPSHOT_FRAME_REFS.pop(session.browser_id, None)
                thumbnail = _capture_step_thumbnail(session)
                return _meta_result(
                    ToolResult(
                        success=True,
                        content={"tab_id": created, "url": target_url, "active": True},
                    ),
                    session,
                    "tabs",
                    url=target_url,
                    title="",
                    screenshot_path=thumbnail,
                )

            pages = _list_page_targets(session)
            info = _locate_tab(pages, tab_id, index)
            target = str(info.get("targetId") or "")
            if action == "switch":
                session.active_target_id = target
                page_info = _evaluate_json(
                    session,
                    "JSON.stringify({url:location.href,title:document.title})",
                    target,
                )
                if not isinstance(page_info, str):
                    return _meta_result(
                        ToolResult(success=False, error="页面信息返回异常（非 JSON）"),
                        session,
                        "tabs",
                    )
                try:
                    page = json.loads(page_info)
                except ValueError:
                    return _meta_result(
                        ToolResult(success=False, error="页面信息不是合法 JSON"),
                        session,
                        "tabs",
                    )
                if not isinstance(page, dict):
                    return _meta_result(
                        ToolResult(success=False, error="页面信息返回异常（非对象）"),
                        session,
                        "tabs",
                    )
                page_url = str(page.get("url") or "")
                page_title = str(page.get("title") or "")
                _remember_page(session, page_url, page_title)
                _SNAPSHOT_FRAME_REFS.pop(session.browser_id, None)
                thumbnail = _capture_step_thumbnail(session)
                return _meta_result(
                    ToolResult(
                        success=True,
                        content={
                            "tab_id": target,
                            "url": page.get("url", ""),
                            "title": page.get("title", ""),
                        },
                    ),
                    session,
                    "tabs",
                    url=page_url,
                    title=page_title,
                    screenshot_path=thumbnail,
                )

            cdp_command(session, "Target.closeTarget", {"targetId": target})
            was_active = session.active_target_id == target
            if was_active:
                session.active_target_id = None
            thumbnail = _capture_step_thumbnail(session)
            return _meta_result(
                ToolResult(
                    success=True,
                    content={
                        "closed": target,
                        "was_active": was_active,
                        "remaining": max(len(pages) - 1, 0),
                    },
                ),
                session,
                "tabs",
                screenshot_path=thumbnail,
            )
        except BrowserCDPError as exc:
            return _meta_error(exc, session, "tabs")

    @staticmethod
    def _list_tabs(session: BrowserSession) -> ToolResult:
        pages = _list_page_targets(session)
        active_target_id = getattr(session, "active_target_id", None)
        if active_target_id and any(
            info.get("targetId") == active_target_id for info in pages
        ):
            active = active_target_id
        else:
            if active_target_id:
                # 与 ensure_page_target 一致：跟踪的标签页已消失 → 清空跟踪
                session.active_target_id = None
            active = str(pages[0]["targetId"]) if pages else ""
        tabs = [
            {
                "tab_id": info.get("targetId", ""),
                "url": info.get("url", ""),
                "title": info.get("title", ""),
                "active": info.get("targetId") == active,
            }
            for info in pages
        ]
        return ToolResult(success=True, content={"tabs": tabs, "count": len(tabs)})


class BrowserDownloadsTool(BaseTool):
    """列出 / 等待浏览器内触发的下载（Round 5 SN3）。

    ``browser_interact click`` 点了下载按钮之后，模型需要知道：文件叫什么、
    下完没有、落在哪。事件通道（``browser_events``）把 CDP 的
    ``Browser.downloadWillBegin/downloadProgress`` 落成状态表；本工具读表、
    可选阻塞等待全部完成，并把完成文件登记为 artifact。事件通道不可用时
    退化为列举下载目录（``.crdownload`` 视为进行中）。
    """

    risk = RiskClass.READ
    is_blocking = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="browser_downloads",
            description=(
                "查看受控浏览器里触发的下载（browser_interact 点击下载按钮后调用）："
                "返回每个下载的 url / 文件名 / 状态 / 字节数 / 最终路径。"
                "wait_for_complete=true 时阻塞直到全部完成或超时（timeout 秒，默认 60）。"
                "路径可直接交给 read_file / office 工具。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "browser_id": {"type": "string", "description": "单实例可省略"},
                    "wait_for_complete": {
                        "type": "boolean",
                        "description": "等待进行中的下载全部完成（默认 false）",
                    },
                    "timeout": {
                        "type": "number",
                        "description": f"等待上限秒数（默认 {DEFAULT_WAIT_TIMEOUT:.0f}，最大 {MAX_WAIT_TIMEOUT:.0f}）",
                    },
                },
                "required": [],
            },
        )

    @_leased
    def execute(
        self,
        browser_id: str = "",
        wait_for_complete: bool = False,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
        **kwargs: Any,
    ) -> ToolResult:
        if kwargs:
            return ToolResult(
                success=False,
                error=(
                    f"未知参数: {', '.join(sorted(kwargs))}"
                    "（合法参数: browser_id, wait_for_complete, timeout）"
                ),
            )
        session: Optional[BrowserSession] = None
        try:
            session = _resolve_session(browser_id or None)
            blocked = _blocked_by_control(session, "browser_downloads")
            if blocked is not None:
                return blocked
        except BrowserCDPError as exc:
            return _meta_error(exc, session, "downloads")
        try:
            wait_seconds = float(timeout)
        except (TypeError, ValueError):
            return ToolResult(success=False, error="timeout 必须是数字")
        wait_seconds = max(0.0, min(wait_seconds, MAX_WAIT_TIMEOUT))

        tracker = get_download_tracker(session.browser_id)
        if tracker is None or not tracker.connected:
            download_dir = (
                tracker.download_dir
                if tracker is not None
                else str(_download_dir_for(session, self._policy.workspace_root))
            )
            items = list_download_dir(download_dir)
            if wait_for_complete and any(i["state"] == "inProgress" for i in items):
                deadline = time.monotonic() + wait_seconds
                while time.monotonic() < deadline:
                    time.sleep(0.5)
                    items = list_download_dir(download_dir)
                    if not any(i["state"] == "inProgress" for i in items):
                        break
            return _meta_result(
                ToolResult(
                    success=True,
                    content={
                        "browser_id": session.browser_id,
                        "download_dir": download_dir,
                        "tracking": False,
                        "downloads": items,
                        "note": (
                            "下载事件通道不可用"
                            + (
                                f"（{tracker.error}）"
                                if tracker is not None and tracker.error
                                else ""
                            )
                            + "，以上为下载目录列举（.crdownload = 进行中）。"
                        ),
                    },
                ),
                session,
                "downloads",
            )

        completed_all = True
        if wait_for_complete:
            completed_all = tracker.wait_for_complete(wait_seconds)
        downloads = tracker.snapshot()
        for record in downloads:
            if record.get("state") != "completed":
                continue
            path = record.get("path") or tracker.resolve_completed_path(record["guid"])
            record["path"] = path
            if path and tracker.mark_artifact_recorded(record["guid"]):
                try:
                    _record_artifact_safely(str(path), int(record.get("received_bytes") or 0))
                except Exception:  # noqa: BLE001 — artifact 记录失败不影响结果
                    logger.warning("browser_downloads artifact 记录失败", exc_info=True)
        pending = [r for r in downloads if r.get("state") == "inProgress"]
        content: Dict[str, Any] = {
            "browser_id": session.browser_id,
            "download_dir": tracker.download_dir,
            "tracking": True,
            "downloads": downloads,
            "pending": len(pending),
        }
        if wait_for_complete and not completed_all:
            content["note"] = (
                f"等待 {wait_seconds:.0f}s 后仍有 {len(pending)} 个下载进行中（可再次调用继续等待）"
            )
        elif not downloads:
            content["note"] = (
                "尚未观察到下载：先用 browser_interact 点击下载按钮 / 链接；"
                "若链接是直接的文件 URL，也可改用 http_download。"
            )
        return _meta_result(
            ToolResult(success=True, content=content), session, "downloads"
        )


class BrowserCookiesTool(BaseTool):
    """导出/管理站点凭据档案（cookie 桥，方案 2026-09-13 §2.5；Round 5 AU1/AU4）。

    导出当前页面 cookie domain 的 cookie（含 expires/secure 元数据），经 SecretBox
    加密落档案；之后 ``web_fetch`` / ``http_download`` 用 ``credential_domain``
    引用，登录墙后的资源（订阅源文献 PDF）即可达。``set_header`` 动作另存
    头部型凭据（Bearer / API key），无需浏览器。返回结果恒为脱敏预览（只有名字）。
    """

    risk = RiskClass.WRITE_LOCAL
    is_blocking = True

    _VALID_ACTIONS = ("export", "list", "delete", "set_header")

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="browser_cookies",
            description=(
                "站点 cookie 凭据档案。action=export：把当前浏览器页面的 "
                "cookie（按其 domain）加密存入凭据档案，供 web_fetch / "
                "http_download 用 credential_domain 参数引用（先登录后导出，"
                "即可抓登录墙后的资源）；action=list：列出档案（脱敏，含剩余时效）；"
                "action=delete：删除某 domain 的档案；action=set_header：保存头部型凭据"
                "（如 header_name=Authorization header_value='Bearer xxx' 或 API key 自定义头，"
                "无需浏览器，值不回显），同样以 credential_domain 引用、跨域剥离。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "export | list | delete | set_header",
                    },
                    "domain": {
                        "type": "string",
                        "description": "delete / set_header 用的档案 domain（如 .cnki.net、api.example.com）",
                    },
                    "header_name": {
                        "type": "string",
                        "description": "set_header：头名（如 Authorization、X-API-Key）",
                    },
                    "header_value": {
                        "type": "string",
                        "description": "set_header：头值（如 'Bearer xxx'）；只加密落库，不回显",
                    },
                    "ttl_seconds": {
                        "type": "integer",
                        "description": "set_header：可选有效期（秒），过期后报 credential_expired",
                    },
                    "browser_id": {"type": "string", "description": "单实例可省略"},
                },
                "required": ["action"],
            },
        )

    @_leased
    def execute(  # noqa: PLR0911, PLR0913 — 每个拒绝/动作路径独立 return，扁平更直读
        self,
        action: str = "",
        domain: str = "",
        browser_id: str = "",
        header_name: str = "",
        header_value: str = "",
        ttl_seconds: int = 0,
        **kwargs: Any,
    ) -> ToolResult:
        if kwargs:
            return ToolResult(
                success=False,
                error=(
                    f"未知参数: {', '.join(sorted(kwargs))}"
                    "（合法参数: action, domain, browser_id, header_name, header_value, ttl_seconds）"
                ),
            )
        if action not in self._VALID_ACTIONS:
            return ToolResult(
                success=False, error=f"action 必须是 {', '.join(self._VALID_ACTIONS)}"
            )

        # 控制门禁：能解析到会话时与其它浏览器工具同口径；纯凭据管理
        # （无浏览器在跑）不因控制面受限。
        try:
            gate_session = _resolve_session(browser_id or None)
        except BrowserCDPError:
            gate_session = None
        if gate_session is not None:
            blocked = _blocked_by_control(gate_session, "browser_cookies")
            if blocked is not None:
                return blocked
            # I1 补强：export 动作实际读取当前页 cookie，需复检域名是否在 block 策略中。
            # list/delete/set_header 不碰浏览器页面，跳过。
            if action == "export":
                blocked_site = _current_page_site_block(gate_session, "cookies")
                if blocked_site is not None:
                    return blocked_site

        if action == "set_header":
            from .credential_vault import save_header_credential

            if not domain.strip() or not header_name.strip() or not str(header_value).strip():
                return ToolResult(
                    success=False, error="set_header 需要 domain、header_name、header_value"
                )
            try:
                save_header_credential(
                    domain,
                    {header_name.strip(): str(header_value)},
                    ttl_seconds=int(ttl_seconds) if ttl_seconds else None,
                )
            except ValueError as exc:
                return ToolResult(success=False, error=f"invalid_header: {exc}")
            return ToolResult(
                success=True,
                content={
                    "domain": domain.strip().lower(),
                    "kind": "header",
                    "header_names": [header_name.strip()],
                    "expires_in_seconds": int(ttl_seconds) if ttl_seconds else None,
                    "note": (
                        "头部凭据已加密存档（值不回显）。web_fetch / http_download "
                        "传 credential_domain=<上述 domain> 即可附加该头（跨域自动剥离）。"
                    ),
                },
            )

        if action == "list":
            from .credential_vault import list_credentials

            return ToolResult(success=True, content={"credentials": list_credentials()})

        if action == "delete":
            from .credential_vault import delete_credential

            if not domain.strip():
                return ToolResult(success=False, error="delete 需要 domain")
            deleted = delete_credential(domain)
            if not deleted:
                return ToolResult(
                    success=False, error=f"credential_not_found: 无 {domain!r} 的档案"
                )
            return ToolResult(success=True, content={"deleted": domain.strip().lower()})

        # 余下分支：action == "export"
        try:
            session = _resolve_session(browser_id or None)
            result = cdp_command(session, "Network.getCookies", {})
        except BrowserCDPError as exc:
            return _error(exc)
        raw_cookies = result.get("cookies") or []
        if not raw_cookies:
            return ToolResult(
                success=False, error="no_cookies: 当前页面没有可导出的 cookie（先登录？）"
            )
        # 当前页 cookie 按 domain 分组存档（一个页面可能带多 domain 的 cookie）
        from .credential_vault import (
            cookie_domain_matches,
            save_credential,
            save_storage_state,
        )

        pages = _http_page_infos(session)
        page_target = pages[0][0] if pages else ""
        page_hosts: List[str] = []
        for _, page_url in pages:
            try:
                host = (urlsplit(page_url).hostname or "").lower()
            except ValueError:
                host = ""
            if host:
                page_hosts.append(host)
        by_domain: Dict[str, list] = {}
        now = time.time()
        for item in raw_cookies:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            cookie_domain = str(item.get("domain") or "").lower()
            if not cookie_domain:
                continue
            # 有页面上下文时只导出归属这些页面的 cookie（数据最小化）
            if page_hosts and not any(
                cookie_domain_matches(host, cookie_domain) for host in page_hosts
            ):
                continue
            by_domain.setdefault(cookie_domain, []).append(item)
        if not by_domain and page_hosts:
            return ToolResult(
                success=False,
                error=(
                    "no_cookies_for_page: 未找到归属当前页面的 cookie。"
                    "请先切换到要导出登录态的目标站点标签页再重试。"
                ),
            )
        origins = _capture_local_storage(session, page_target)
        origin_hosts = []
        for origin_item in origins:
            try:
                origin_hosts.append(urlsplit(origin_item["origin"]).hostname or "")
            except ValueError:
                origin_hosts.append("")
        saved = []
        for cookie_domain, cookies in sorted(by_domain.items()):
            profile_name = str(getattr(session, "profile_name", "") or "")
            if origins and any(
                _storage_domain_matches(cookie_domain, host) for host in origin_hosts
            ):
                save_storage_state(
                    cookie_domain, cookies, origins, source_profile=profile_name
                )
            else:
                save_credential(cookie_domain, cookies, source_profile=profile_name)
            # AU1：告知最短剩余时效，模型 / 用户可预知失效
            expiries = [
                int(c["expires"] - now)
                for c in cookies
                if isinstance(c.get("expires"), (int, float)) and c["expires"] > 0  # noqa: UP038 — py3.8
            ]
            saved.append(
                {
                    "domain": cookie_domain,
                    "cookie_names": [str(c.get("name")) for c in cookies],
                    "count": len(cookies),
                    "expires_in_seconds": min(expiries) if expiries else None,
                }
            )
        return ToolResult(
            success=True,
            content={
                "saved": saved,
                "note": (
                    "cookie 已加密存档（值不回显）。web_fetch / http_download "
                    "传 credential_domain=<上述 domain> 即可携带登录态。"
                ),
            },
        )


#: browser_login 使用的持久 profile 名（区别于 render pool 的 "render-default"）
_LOGIN_PROFILE_NAME = "login-default"

#: 登录完成检测轮询间隔（秒）
_LOGIN_POLL_INTERVAL = 2.0

#: 默认登录超时（秒）
_LOGIN_DEFAULT_TIMEOUT = 300

#: 页面内注入的 Sage 登录辅助悬浮条（Shadow DOM 隔离）
_LOGIN_BANNER_JS = """(function() {
  if (window.__sage_login_confirmed) {
    return { confirmed: true, url: location.href, hasPassword: false };
  }
  if (!document.getElementById('sage-login-helper-host') && document.body) {
    try {
      const host = document.createElement('div');
      host.id = 'sage-login-helper-host';
      host.style.cssText = 'position:fixed;top:0;left:0;width:100vw;z-index:2147483647;pointer-events:none;';
      const shadow = host.attachShadow({ mode: 'open' });
      const bar = document.createElement('div');
      bar.id = 'sage-banner';
      bar.style.cssText = (
        'pointer-events:auto;background:#18181b;color:#f4f4f5;' +
        'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;' +
        'font-size:13px;padding:9px 18px;display:flex;align-items:center;' +
        'justify-content:space-between;box-shadow:0 4px 16px rgba(0,0,0,0.35);' +
        'border-bottom:2px solid #3b82f6;'
      );
      bar.innerHTML = (
        '<div style="display:flex;align-items:center;gap:8px;">' +
        '<span style="font-size:16px;">🔐</span>' +
        '<strong style="color:#60a5fa;">Sage 登录助手</strong>' +
        '<span style="color:#d4d4d8;">请在下方完成登录。登录后会自动同步；您也可以随时点击右侧按钮立即同步。</span>' +
        '</div>' +
        '<button id="sage-btn" style="' +
        'background:#2563eb;color:#fff;border:none;padding:6px 14px;border-radius:6px;' +
        'font-size:12px;font-weight:600;cursor:pointer;display:flex;align-items:center;gap:4px;' +
        '">已完成登录，点击同步 ➔</button>'
      );
      shadow.appendChild(bar);
      document.documentElement.appendChild(host);
      const btn = shadow.getElementById('sage-btn');
      btn.onclick = () => {
        window.__sage_login_confirmed = true;
        btn.style.background = '#059669';
        btn.textContent = '⏳ 正在同步并返回...';
      };
    } catch (e) {}
  }
  return {
    confirmed: !!window.__sage_login_confirmed,
    url: location.href,
    hasPassword: !!document.querySelector('input[type=password]'),
    htmlLen: document.documentElement ? document.documentElement.outerHTML.length : 0
  };
})()
"""

#: 登录成功时的页面提示动画
_LOGIN_SUCCESS_JS = """
(function() {
  try {
    const host = document.getElementById('sage-login-helper-host');
    if (host && host.shadowRoot) {
      const bar = host.shadowRoot.getElementById('sage-banner');
      if (bar) {
        bar.style.background = '#064e3b';
        bar.style.borderBottomColor = '#10b981';
        bar.innerHTML = (
          '<div style="display:flex;align-items:center;justify-content:center;' +
          'gap:8px;width:100%;font-size:14px;">' +
          '<span style="font-size:18px;">🎉</span>' +
          '<strong style="color:#a7f3d0;">' +
          '登录成功！凭据已自动加密保存，窗口即将自动关闭并返回 Sage...' +
          '</strong></div>'
        );
      }
    }
  } catch (e) {}
})()
"""


_LOGIN_STORAGE_JS = (
    "(function(){try{var out={};var ls=window.localStorage;"
    "for(var i=0;i<ls.length;i++){var k=ls.key(i);out[k]=ls.getItem(k);}"
    "return JSON.stringify({origin:location.origin,localStorage:out});}"
    "catch(e){return ''}})()"
)


def _capture_local_storage(  # noqa: PLR0911 — 各失败路径独立 return，扁平更直读
    session: BrowserSession, target_id: str = ""
) -> List[Dict[str, Any]]:
    """读取目标页面的 localStorage（按 origin 打包）；失败 / 空 / 超限返回空列表。"""
    if not target_id:
        return []
    try:
        result = cdp_command(
            session,
            "Runtime.evaluate",
            {"expression": _LOGIN_STORAGE_JS, "returnByValue": True},
            target_id=target_id,
        )
    except BrowserCDPError:
        return []
    value = (result.get("result") or {}).get("value")
    if not isinstance(value, str) or not value or len(value) > LOCAL_STORAGE_CAP:
        return []
    try:
        parsed = json.loads(value)
    except ValueError:
        return []
    if not isinstance(parsed, dict):
        return []
    origin = str(parsed.get("origin") or "")
    storage = parsed.get("localStorage")
    if not origin.startswith(("http://", "https://")) or not isinstance(storage, dict):
        return []
    cleaned = {
        str(key): str(val)
        for key, val in storage.items()
        if isinstance(key, str) and isinstance(val, str) and val != ""
    }
    if not cleaned:
        return []
    return [{"origin": origin, "localStorage": cleaned}]


def _storage_domain_matches(domain: str, host: str) -> bool:
    """cookie domain（可能带前导点）是否覆盖页面 host。"""
    bare = domain.strip().lower().lstrip(".")
    host = (host or "").strip().lower()
    return bool(bare) and (host == bare or host.endswith("." + bare))


def _http_page_infos(session: BrowserSession) -> List[Tuple[str, str]]:
    """当前会话所有 http(s) 页面 (targetId, url)；按 CDP 返回顺序。"""
    try:
        result = cdp_command(session, "Target.getTargets", {})
    except BrowserCDPError:
        return []
    pages: List[Tuple[str, str]] = []
    for info in result.get("targetInfos") or []:
        if not isinstance(info, dict) or info.get("type") != "page":
            continue
        url = str(info.get("url") or "")
        if url.startswith(("http://", "https://")) and info.get("targetId"):
            pages.append((str(info["targetId"]), url))
    return pages


def _first_page_info(session: BrowserSession) -> Tuple[str, str]:
    """当前会话中第一个 http(s) 页面 (targetId, url)；无则 ("", "")。"""
    pages = _http_page_infos(session)
    return pages[0] if pages else ("", "")


def _first_page_target(session: BrowserSession) -> str:
    """当前会话中第一个 http(s) 页面 target（用于尽力捕获 localStorage）。"""
    return _first_page_info(session)[0]


class BrowserLoginTool(BaseTool):
    """一键登录站点：打开可见浏览器 → 用户登录 → 自动保存 cookie。

    把 ``browser_launch`` + ``browser_navigate`` + 用户手动登录 +
    ``browser_cookies(action=export)`` 四步合为单一工具调用。用户无需理解
    cookie/导出等概念，只需在弹出的浏览器窗口完成登录即可。

    登录完成检测（轮询）：
    - 当前 URL 不再是登录页（``looks_like_login_url()`` 返回 False）
    - 页面没有密码输入框（``looks_like_login_html()`` 返回 False）
    - 浏览器有目标域的非 WAF cookie（``Network.getCookies`` 当前页可见集合）

    凭据导出：使用 ``Storage.getCookies``（浏览器级，全量 cookie，含
    host-only 跨子域认证 cookie）；导出结果按 domain 分组保存到加密档案，
    返回内容包含 ``export_summary``（总数/跨域数/候选认证 cookie 数）供 LLM
    诊断。

    风险分级 EXTERNAL：导航到外部 URL 拉取内容；is_blocking=True 因为需要
    等待用户完成登录（可能几分钟）。
    """

    risk = RiskClass.EXTERNAL
    is_blocking = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="browser_login",
            description=(
                "一键登录站点：打开可见浏览器窗口，导航到指定 URL，等待用户完成"
                "登录后自动保存 cookie 到加密档案。之后 web_fetch 访问该站点会"
                "自动携带登录态，无需手动传 credential_domain。"
                "\n\n多账号：可传 account_id 将凭据存入指定账号（见"
                " browser_list_accounts）；或传 account_label 新建一个命名账号并"
                "把本次登录的凭据存入该账号。不传则沿用默认单账号行为。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "要登录的站点 URL（如 https://example.com/login）",
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "description": "等待登录完成的超时秒数（默认 300 = 5 分钟）",
                    },
                    "account_id": {
                        "type": "string",
                        "description": "可选：登录后把凭据存入该账号 ID（已存在的账号）",
                    },
                    "account_label": {
                        "type": "string",
                        "description": "可选：新建一个以此命名的账号并存入本次登录凭据（与 account_id 二选一）",
                    },
                },
                "required": ["url"],
            },
        )

    @_leased
    def execute(  # noqa: PLR0911
        self,
        url: str = "",
        timeout_seconds: int = _LOGIN_DEFAULT_TIMEOUT,
        account_id: Optional[str] = None,
        account_label: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        if kwargs:
            return ToolResult(
                success=False,
                error=(
                    f"未知参数: {', '.join(sorted(kwargs))}"
                    "（合法参数: url, timeout_seconds, account_id, account_label）"
                ),
            )
        url = (url or "").strip()
        if not url:
            return ToolResult(success=False, error="url 不能为空")
        if not url.startswith(("http://", "https://")):
            return ToolResult(success=False, error="url 必须以 http:// 或 https:// 开头")
        # 门禁二次校验：REST 登录任务直接调用本工具时也必须遵守
        # 离线 / 内网白名单模式（与 browser_navigate 同口径）
        rejection = load_network_policy().check_host(url)
        if rejection:
            return ToolResult(success=False, error=rejection)

        # 提取目标域名用于后续 cookie 匹配
        parsed = urlsplit(url)
        target_host = (parsed.hostname or "").lower()
        if not target_host:
            return ToolResult(success=False, error="无法从 url 解析出域名")

        # 多账号：account_label 新建账号（account_id 优先，二选一）。
        # created_account_id 非空表示本账号是本次登录刚建的——登录失败时清理，
        # 避免账号池留下没有凭据的孤儿账号。
        account_id = (account_id or "").strip() or None
        account_label = (account_label or "").strip() or None
        created_account_id: Optional[str] = None
        if account_id and account_label:
            return ToolResult(
                success=False,
                error="account_id 与 account_label 只能二选一",
            )
        if account_label:
            from backend.services.browser_account_service import browser_account_service

            try:
                account = browser_account_service.create_account(
                    label=account_label, domain=target_host
                )
            except ValueError as exc:
                return ToolResult(success=False, error=f"create_account_failed: {exc}")
            account_id = account.id
            created_account_id = account.id
        elif account_id:
            from backend.services.browser_account_service import browser_account_service

            account = browser_account_service.get_account(account_id)
            if account is None:
                return ToolResult(
                    success=False, error=f"account_not_found: 账号 {account_id!r} 不存在"
                )
            # 账号域名须与登录站点匹配（含子域关系），否则凭据会存到错误 domain
            bare = account.domain.lstrip(".")
            if not (
                target_host == bare
                or target_host.endswith("." + bare)
                or bare.endswith("." + target_host)
            ):
                return ToolResult(
                    success=False,
                    error=(
                        f"account_domain_mismatch: 账号「{account.label}」属于 {account.domain}，"
                        f"与登录站点 {target_host} 不匹配"
                    ),
                )

        def _abort_and_cleanup(msg: str) -> ToolResult:
            """失败退出：若是本次新建的账号则删除，避免孤儿账号。"""
            if created_account_id:
                import contextlib

                from backend.services.browser_account_service import browser_account_service

                with contextlib.suppress(Exception):
                    browser_account_service.delete_account(created_account_id)
            return ToolResult(success=False, error=msg)

        # I1：登录同样是导航；只应用站点策略的 block 部分（用户主动登录
        # 未知站点保持允许，不做 confirm，避免登录流程被站点确认卡住）。
        if _safety_check_site("", url) == "block":
            return _abort_and_cleanup(
                f"site_blocked: 用户已禁止该站点 {browser_safety.domain_of(url)}"
            )

        # 检查是否已有活跃的登录浏览器（避免重复启动）
        owner = _current_owner()
        manager = get_browser_manager()
        existing = manager.get(_LOGIN_PROFILE_NAME)
        if existing is not None and existing.is_alive():
            if owner and existing.owner and existing.owner != owner:
                return _abort_and_cleanup(
                    "login_busy: 另一个会话正在使用登录浏览器，请等待其完成后再试"
                )
            # 复用已有浏览器，直接导航到目标 URL
            session = existing
            reuse = True
        else:
            # 启动新的可见持久浏览器（归属当前会话；profile 被占用时给可读错误）
            try:
                session = launch_browser(
                    headless=False,
                    browser_id=_LOGIN_PROFILE_NAME,
                    persistent=True,
                    profile_name=_LOGIN_PROFILE_NAME,
                    owner=owner,
                )
            except BrowserCDPError as exc:
                return _abort_and_cleanup(
                    f"browser_launch_failed: 无法启动浏览器（{exc}）"
                )
            reuse = False
        _lease_session(session)

        # 登录会话同样确保下载目录已设置（登录后可能直接触发下载）。
        _apply_download_behavior(session, self._policy.workspace_root)

        # 创建新标签页并导航到目标 URL
        target_id: Optional[str] = None
        try:
            created = cdp_command(session, "Target.createTarget", {"url": url})
            target_id = created.get("targetId")
            if not target_id:
                return _abort_and_cleanup("导航失败：无法创建标签页")

            # 等待页面初始加载
            _wait_for_page_load(session, target_id, timeout=15.0)

            # 轮询等待用户完成登录
            timeout_secs = max(30, int(timeout_seconds))
            deadline = time.monotonic() + timeout_secs
            login_completed = False
            last_status = ""

            while time.monotonic() < deadline:
                status = _check_login_status(session, target_id, target_host)
                if status == "logged_in":
                    login_completed = True
                    break
                if status != last_status:
                    last_status = status
                time.sleep(_LOGIN_POLL_INTERVAL)

            # 登录成功：在页面上展示成功提示并稍作停留，让用户有明确的视觉反馈
            if login_completed and target_id:
                try:
                    cdp_command(
                        session,
                        "Runtime.evaluate",
                        {"expression": _LOGIN_SUCCESS_JS},
                        target_id=target_id,
                    )
                    time.sleep(1.5)
                except BrowserCDPError:
                    pass

            # 导出并保存 cookie（同域 localStorage 一并保存）
            saved_domains, export_summary = self._export_cookies(
                session, target_host, target_id or "", account_id=account_id
            )

            if saved_domains:
                return ToolResult(
                    success=True,
                    content={
                        "saved_domains": saved_domains,
                        "export_summary": export_summary,
                        "note": (
                            f"登录成功！站点 {target_host} 的登录凭据已加密保存到本地。"
                            f"后续 web_fetch 访问该站点会自动携带登录态。"
                        ),
                        "instruction": (
                            f"站点 {target_host} 登录态已成功保存！"
                            f"请立即调用 web_fetch 工具重新访问目标页面 {url}，并将获取到的数据完整总结呈现给用户。"
                        ),
                        "browser_id": session.browser_id,
                        "reused": reuse,
                        "account_id": account_id or "",
                    },
                )
            else:
                return _abort_and_cleanup(
                    "no_cookies_saved: 未找到可保存的 cookie。"
                    "请确认已经在浏览器窗口中完成登录。"
                )

        except BrowserCDPError as exc:
            # 容错：若用户手动关闭了窗口/标签页，尝试检查是否已有保存的 cookies
            try:
                saved_domains, export_summary = self._export_cookies(
                    session, target_host, target_id or "", account_id=account_id
                )
                if saved_domains:
                    return ToolResult(
                        success=True,
                        content={
                            "saved_domains": saved_domains,
                            "export_summary": export_summary,
                            "note": (
                                f"登录窗口已关闭，检测并成功保存了 {target_host} 的登录态。"
                            ),
                            "instruction": (
                                f"请立即调用 web_fetch 工具访问 {url}，并将获取到的页面内容呈现给用户。"
                            ),
                            "browser_id": getattr(session, "browser_id", ""),
                            "reused": reuse,
                            "account_id": account_id or "",
                        },
                    )
            except Exception:
                pass
            return _abort_and_cleanup(f"browser_error: {exc}")
        finally:
            # 关闭标签页但保持浏览器运行（用户可能还要操作其他页面）
            if target_id:
                import contextlib
                with contextlib.suppress(BrowserCDPError):
                    cdp_command(session, "Target.closeTarget", {"targetId": target_id})

    def _export_cookies(
        self,
        session: BrowserSession,
        target_host: str,
        target_id: str = "",
        account_id: Optional[str] = None,
    ) -> tuple:
        """浏览器级导出 cookie 并按 domain 分组保存。

        使用 ``Storage.getCookies``（浏览器级 CDP，不 attach 页面）而不是
        ``Network.getCookies``（页面级，只返回当前 frame URL 可见的 cookie）：
        后者会漏掉 host-only 的跨子域认证 cookie（典型例子：登录流程产生
        ``www.example.cn/_token`` + ``account.example.cn/_sid``，而当前页
        是 ``app.example.cn/console``，页面级 CDP 完全看不到这两条，导致
        web_fetch 后续注入的凭据档案只有 WAF/UI cookie，永远登录墙）。

        同域 localStorage 一并保存为 storage_state（知网等双 token 站点）。

        Returns:
            ``(saved_domains, summary)`` —— ``summary`` 包含总数 / 跨域数 /
            候选认证 cookie 数（httpOnly+secure）用于 LLM 诊断输出。
        """
        from .credential_vault import (
            cookie_domain_matches,
            save_credential,
            save_storage_state,
        )

        try:
            result = cdp_command(session, "Storage.getCookies", {})
        except BrowserCDPError:
            return [], {}

        raw_cookies = result.get("cookies") or []
        if not raw_cookies:
            return [], {}

        origins = _capture_local_storage(session, target_id)
        page_hosts: List[str] = []
        for origin_item in origins:
            try:
                host = (urlsplit(origin_item["origin"]).hostname or "").lower()
            except ValueError:
                host = ""
            if host:
                page_hosts.append(host)
        allowed_hosts = [target_host] + [h for h in page_hosts if h]

        def _allowed(cookie_domain: str) -> bool:
            bare = (cookie_domain or "").strip().lower().lstrip(".")
            for host in allowed_hosts:
                if not host:
                    continue
                # 标准 RFC 6265：cookie 域覆盖 host（如 .example.com 覆盖 www.example.com）
                if cookie_domain_matches(host, cookie_domain):
                    return True
                # 跨子域认证：cookie 域是 host 的子域（如 www.example.cn 属于 example.cn 站点）
                if bare and (bare == host or bare.endswith("." + host)):
                    return True
            return False

        # 按 domain 分组（只保留归属目标站的 cookie，避免把持久 profile 里
        # 其他站点的登录态一并导出）
        by_domain: Dict[str, list] = {}
        for item in raw_cookies:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            cookie_domain = str(item.get("domain") or "").lower()
            if not cookie_domain or not _allowed(cookie_domain):
                continue
            by_domain.setdefault(cookie_domain, []).append(item)

        saved = []
        profile_name = getattr(session, "profile_name", "") or ""

        # 多账号：命中指定账号时，把归属目标站的全部 cookie 存入该账号的
        # domain 条目（vault key = account.domain::account_id），不另存兜底，
        # 避免污染默认账号。
        account_vault_id: Optional[str] = None
        account_domain = ""
        if account_id:
            from backend.services.browser_account_service import browser_account_service

            account = browser_account_service.get_account(account_id)
            if account is not None:
                account_domain = account.domain
                if not account.is_default:
                    account_vault_id = account.id

        if account_id and account_domain:
            allowed_cookies = [
                item
                for cookies in by_domain.values()
                for item in cookies
                if isinstance(item, dict) and item.get("name")
            ]
            try:
                if origins:
                    save_storage_state(
                        account_domain,
                        allowed_cookies,
                        origins,
                        source_profile=str(profile_name),
                        account_id=account_vault_id,
                    )
                else:
                    save_credential(
                        account_domain,
                        allowed_cookies,
                        source_profile=str(profile_name),
                        account_id=account_vault_id,
                    )
                saved.append(account_domain)
            except Exception:
                pass
        else:
            for cookie_domain, cookies in sorted(by_domain.items()):
                try:
                    if origins and any(
                        _storage_domain_matches(cookie_domain, host) for host in allowed_hosts
                    ):
                        save_storage_state(
                            cookie_domain,
                            cookies,
                            origins,
                            source_profile=str(profile_name),
                        )
                    else:
                        save_credential(
                            cookie_domain,
                            cookies,
                            source_profile=str(profile_name),
                        )
                    saved.append(cookie_domain)
                except Exception:
                    # 单个 domain 保存失败不影响其他
                    pass

        # P1 跨域认证 cookie 兜底：把全量 cookie（含 host-only 跨子域认证
        # cookie）也存一份到 target_host 档案下，保留每个 cookie 的原始
        # domain 字段。这样 web_fetch(credential_domain=target_host) 注入
        # 渲染浏览器时，跨子域的认证 cookie 能在 OAuth 跳转中被浏览器
        # 按原始 domain 自动携带（典型场景：platform.example.cn 控制台依
        # 赖 www.example.cn/_token + account.example.cn/_sid）。
        # 多账号登录不兜底（凭据已整包存入指定账号）。
        if target_host and not (account_id and account_domain):
            try:
                save_credential(
                    target_host,
                    raw_cookies,
                    source_profile=str(profile_name),
                )
                if target_host not in saved:
                    saved.append(target_host)
            except Exception:
                pass

        summary = {
            "total_cookies": len(raw_cookies),
            "domain_count": len(by_domain),
            "domains": sorted(by_domain.keys()),
            "auth_candidates": sum(
                1
                for item in raw_cookies
                if isinstance(item, dict) and item.get("httpOnly") and item.get("secure")
            ),
        }
        return saved, summary


class BrowserListAccountsTool(BaseTool):
    """列出浏览器多账号（可按域名过滤）。"""

    risk = RiskClass.READ
    is_blocking = False

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="browser_list_accounts",
            description=(
                "列出所有已登记的浏览器账号（同一网站可多个账号），返回账号 ID、"
                "名称、所属域名、是否默认账号、以及当前浏览器激活的账号。"
                "配合 browser_switch_account 在多账号接力流程中切换身份。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "可选：按域名过滤（如 cnki.net）",
                    },
                    "browser_id": {"type": "string", "description": "单实例可省略"},
                },
            },
        )

    @_leased
    def execute(
        self,
        domain: str = "",
        browser_id: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        if kwargs:
            return ToolResult(
                success=False,
                error=(
                    f"未知参数: {', '.join(sorted(kwargs))}"
                    "（合法参数: domain, browser_id）"
                ),
            )
        from backend.services.browser_account_service import browser_account_service

        try:
            accounts = browser_account_service.list_accounts(domain or None)
        except Exception as exc:  # noqa: BLE001 — 列表失败如实回传
            return ToolResult(success=False, error=f"list_accounts_failed: {exc}")

        active_id = ""
        if browser_id:
            active = browser_account_service.get_active_account(browser_id)
            active_id = active.id if active else ""
        items = []
        for account in accounts:
            item = account.to_dict()
            item["active"] = bool(active_id and account.id == active_id)
            items.append(item)
        return ToolResult(
            success=True,
            content={
                "accounts": items,
                "count": len(items),
                "active_account_id": active_id,
            },
        )


class BrowserSwitchAccountTool(BaseTool):
    """切换浏览器当前激活的账号（Cookie State Swap）。"""

    risk = RiskClass.WRITE_LOCAL
    is_blocking = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="browser_switch_account",
            description=(
                "把浏览器切换到指定账号：快照当前账号登录态 → 清空浏览器 cookie/"
                "localStorage → 注入目标账号登录态 → 刷新页面。切换后浏览器只携带"
                "目标账号凭据，账号间不串号。适用于多用户接力完成网页流程、或同一"
                "网站多账号操作。可用 browser_list_accounts 查看可用账号。"
                "切换前请确认用户同意（这是对外部网站的身份切换）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "account_id": {
                        "type": "string",
                        "description": "目标账号 ID（从 browser_list_accounts 获取）",
                    },
                    "account_label": {
                        "type": "string",
                        "description": "或通过账号名称指定（可选域名内唯一匹配）",
                    },
                    "domain": {
                        "type": "string",
                        "description": "配合 account_label 消歧的域名",
                    },
                    "browser_id": {"type": "string", "description": "单实例可省略"},
                },
            },
        )

    @_leased
    def execute(  # noqa: PLR0911 — 每个拒绝/动作路径独立 return，扁平更直读
        self,
        account_id: str = "",
        account_label: str = "",
        domain: str = "",
        browser_id: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        if kwargs:
            return ToolResult(
                success=False,
                error=(
                    f"未知参数: {', '.join(sorted(kwargs))}"
                    "（合法参数: account_id, account_label, domain, browser_id）"
                ),
            )
        from backend.services.browser_account_service import browser_account_service

        account_id = (account_id or "").strip()
        account_label = (account_label or "").strip()
        if not account_id and not account_label:
            return ToolResult(
                success=False, error="account_id 或 account_label 至少提供一个"
            )
        if not account_id and account_label:
            try:
                accounts = browser_account_service.list_accounts(domain or None)
            except Exception as exc:  # noqa: BLE001 — 列表失败如实回传
                return ToolResult(success=False, error=f"list_accounts_failed: {exc}")
            matches = [
                a for a in accounts if a.label == account_label or account_label in a.label
            ]
            if not matches:
                return ToolResult(
                    success=False,
                    error=f"account_not_found: 没有名称匹配 {account_label!r} 的账号",
                )
            if len(matches) > 1:
                candidates = ", ".join(f"{a.label}({a.domain})" for a in matches)
                return ToolResult(
                    success=False,
                    error=f"account_ambiguous: 匹配到多个账号：{candidates}；请传 domain 或 account_id 消歧",
                )
            account_id = matches[0].id

        try:
            session = _resolve_session(browser_id or None)
        except BrowserCDPError as exc:
            return _error(exc)
        result = browser_account_service.switch_account(
            account_id, browser_id=session.browser_id, owner=_current_owner()
        )
        if not result.ok:
            return ToolResult(success=False, error=result.message or "switch_failed")
        return ToolResult(success=True, content=result.to_dict())


def _wait_for_page_load(
    session: BrowserSession, target_id: str, timeout: float = 15.0
) -> None:
    """等待页面 readyState 变为 complete 或 interactive。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = cdp_command(
                session,
                "Runtime.evaluate",
                {"expression": "document.readyState", "returnByValue": True},
                target_id=target_id,
            )
            state = (result.get("result") or {}).get("value")
            if state in ("complete", "interactive"):
                return
        except BrowserCDPError:
            return
        time.sleep(0.3)


def _check_login_status(
    session: BrowserSession, target_id: str, target_host: str
) -> str:
    """检查登录状态。返回 'logged_in' / 'on_login_page' / 'loading'。"""
    from .credential_vault import looks_like_login_url

    try:
        # 注入/维护悬浮条并获取当前状态
        result = cdp_command(
            session,
            "Runtime.evaluate",
            {
                "expression": _LOGIN_BANNER_JS,
                "returnByValue": True,
            },
            target_id=target_id,
        )
        info = (result.get("result") or {}).get("value")
        if not isinstance(info, dict):
            return "loading"

        # 1. 用户主动点击了悬浮条上的"已完成登录，点击同步"
        if info.get("confirmed"):
            return "logged_in"

        current_url = str(info.get("url") or "")
        has_password = bool(info.get("hasPassword", False))

        # 2. 自动判定：当前 URL 离开了登录页且没有密码框
        if not looks_like_login_url(current_url) and not has_password:
            # 额外验证：有目标域的认证 cookie 才算真正登录
            # 排除 WAF/CDN/反爬虫 cookie（这些不代表登录状态）
            _WAF_COOKIE_NAMES = frozenset({
                # 阿里云 WAF
                "acw_tc", "acw_sc__v2", "acw_sc__v3", "aliyungf_tmd",
                # Cloudflare
                "cf_clearance", "cfduid", "__cfduid", "cf_clearance_2",
                # 腾讯云 WAF
                "tencent_waf_cookie", "twaf_tc",
                # 通用 CDN/WAF
                "cdn_sec_tc", "waf_cookie", "waf_tc", "rancher_id",
                # 防御性 cookie（非认证）
                "__jsl_clearance_s", "__jsluid_s", "sl-session",
            })
            try:
                cookies_result = cdp_command(session, "Network.getCookies", {})
                cookies = cookies_result.get("cookies") or []
                auth_cookie_count = 0
                for c in cookies:
                    if isinstance(c, dict):
                        cdomain = str(c.get("domain") or "").lower().lstrip(".")
                        cname = str(c.get("name") or "").lower()
                        # 跳过 WAF/CDN cookie
                        if cname in _WAF_COOKIE_NAMES:
                            continue
                        # 跳过以 __cf/ __ac_ 开头的 Cloudflare/Akamai cookie
                        if cname.startswith(("__cf", "__ac_", "_cfuvid")):
                            continue
                        if cdomain and (
                            target_host == cdomain or target_host.endswith("." + cdomain)
                        ):
                            auth_cookie_count += 1
                # 至少有 1 个非 WAF cookie 才算登录成功
                if auth_cookie_count > 0:
                    return "logged_in"
            except BrowserCDPError:
                pass
            return "loading"

        return "on_login_page"

    except (BrowserCDPError, json.JSONDecodeError, KeyError):
        return "loading"


__all__ = [
    "BROWSER_TOOL_NAMES",
    "BrowserCloseTool",
    "BrowserCookiesTool",
    "BrowserDownloadsTool",
    "BrowserInteractTool",
    "BrowserLaunchTool",
    "BrowserLoginTool",
    "BrowserNavigateTool",
    "BrowserScreenshotTool",
    "BrowserSnapshotTool",
    "BrowserTabsTool",
    "validate_url",
]

#: 与 domain/tool_names.py 的 BROWSER_TOOLS 保持一致（一致性由测试锁定）
BROWSER_TOOL_NAMES = (
    "browser_launch",
    "browser_navigate",
    "browser_snapshot",
    "browser_interact",
    "browser_screenshot",
    "browser_cookies",
    "browser_downloads",
    "browser_close",
    "browser_login",
    "browser_tabs",
)
