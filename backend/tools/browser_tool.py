"""浏览器自动化工具组（对标增强 G7，docs/plans §2.1）。

对标 ZCode browser-use / Codex 浏览器操作：LLM 可启动本机 Chrome/Edge、
导航、读页面、点击/输入/滚动、截图、关闭。底层经 CDP（见 browser_cdp /
browser_ws）—— 不经 Playwright（Win7 兼容 + 零新依赖）。

风险分级（与权限矩阵对齐）：

- ``browser_launch`` EXEC（启动子进程，INTERACTIVE 先审批）；
- ``browser_navigate`` EXTERNAL（拉取网络内容，最严门禁、逐次审批）；
- ``browser_snapshot`` / ``browser_screenshot`` READ；
- ``browser_interact`` / ``browser_close`` WRITE_LOCAL。

全部工具 ``is_blocking=True``：CDP 走阻塞 socket I/O，必须卸载到
executor 线程执行（同时规避在事件循环线程内做同步 socket 的死锁面）。
v1 面向 coder（executor 边界）；导航仅允许 http/https/about/data。
"""

from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from backend.domain.risk import RiskClass

from .base import BaseTool, ToolResult, ToolSchema
from .browser_cdp import (
    BrowserCDPError,
    BrowserSession,
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
from .file_tool import _record_artifact_safely
from .network_config import load_network_policy
from .web_render import wait_page_ready

logger = logging.getLogger(__name__)

#: 页面文本快照上限（字节，超出截断）
SNAPSHOT_TEXT_CAP = 30 * 1024

#: 允许的 URL scheme（file:// 可读本地文件 → 坚决拒绝；javascript: 注入面）
_ALLOWED_SCHEMES = frozenset({"http", "https", "about", "data"})

_VALID_ACTIONS = ("click", "type", "press", "scroll")


def _error(exc: BrowserCDPError) -> ToolResult:
    return ToolResult(success=False, error=str(exc))


def _resolve_session(browser_id: Optional[str]) -> BrowserSession:
    """统一入口：解析会话并把 BrowserCDPError 归一为带提示的错误。"""
    return get_browser_manager().require(browser_id)


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
        "const setter=Object.getOwnPropertyDescriptor(proto,'value').set;"
        f"setter.call(el,{json.dumps(value)});"
        "el.dispatchEvent(new Event('input',{bubbles:true}));"
        "el.dispatchEvent(new Event('change',{bubbles:true}));"
        f"return{{ok:true,info:'typed '+(el.value||el.textContent||'').length+' chars'+({json.dumps(' cleared-first' if clear else '')})}};"
        "})()"
    )


def _js_press(key: str) -> str:
    return (
        "(function(){"
        f"const k={json.dumps(key)};"
        "const el=document.activeElement||document.body;"
        "const opts={key:k,keyCode:(k==='Enter'?13:k==='Escape'?27:k==='Tab'?9:0),bubbles:true};"
        "el.dispatchEvent(new KeyboardEvent('keydown',opts));"
        "el.dispatchEvent(new KeyboardEvent('keyup',opts));"
        "return{ok:true,info:'pressed '+k};"
        "})()"
    )


def _js_scroll(amount: int) -> str:
    return (
        "(function(){"
        f"window.scrollBy(0,{int(amount)});"
        f"return{{ok:true,info:'scrolled to y='+window.scrollY}};"
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


def _validate_interact_args(
    kwargs: Dict[str, Any],
    action: str,
    selector: str,
    text: str,
    value: str,
    key: str,
) -> Optional[ToolResult]:
    """browser_interact 参数校验；返回拒绝结果或 None（放行）。"""
    if kwargs:
        return ToolResult(
            success=False,
            error=f"未知参数: {', '.join(sorted(kwargs))}",
        )
    if action not in _VALID_ACTIONS:
        return ToolResult(
            success=False,
            error=f"action 必须是 {', '.join(_VALID_ACTIONS)}",
        )
    if action in ("click", "type"):
        return _validate_action_args(action, selector, text, value)
    if action == "press" and not key:
        return ToolResult(success=False, error="press 需要 key")
    if action == "scroll":
        try:
            int(value)
        except (TypeError, ValueError):
            return ToolResult(success=False, error="scroll 的 value 必须是整数像素")
    return None


def _validate_action_args(
    action: str, selector: str, text: str, value: str
) -> Optional[ToolResult]:
    """click / type 两个依赖定位参数的 action 的专项校验。"""
    if action == "click":
        if not selector and not text:
            return ToolResult(success=False, error="click 需要 selector 或 text 之一")
        return None
    if not selector:
        return ToolResult(success=False, error="type 需要 selector")
    if not isinstance(value, str):
        return ToolResult(success=False, error="type 的 value 必须是字符串")
    return None
    return None


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
                "需要可视化调试或手动登录时传 false。"
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
                        "description": "持久 profile 名称（默认 default）",
                    },
                },
                "required": [],
            },
        )

    def execute(
        self,
        headless: bool = True,
        persistent: bool = False,
        profile_name: str = "default",
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
                profile_name=str(profile_name or "default"),
            )
        except BrowserCDPError as exc:
            return _error(exc)

        # 下载黑洞修复：把浏览器内触发的下载重定向到工作区（或数据目录），
        # 否则文件落在临时 profile 目录，browser_close 时一并被删。
        root = self._policy.workspace_root
        download_dir = Path(root) / "downloads" if root else browser_downloads_root()
        try:
            download_dir.mkdir(parents=True, exist_ok=True)
            cdp_command(
                session,
                "Browser.setDownloadBehavior",
                {"behavior": "allow", "downloadPath": str(download_dir)},
            )
        except BrowserCDPError as exc:
            logger.warning("setDownloadBehavior 失败（不影响启动）: %s", exc)

        # SN3：常驻事件通道跟踪下载（downloadWillBegin / downloadProgress）
        tracker = start_download_tracking(
            session.browser_id, session.port, session.ws_path, str(download_dir)
        )
        if not tracker.connected:
            logger.warning(
                "下载事件通道未建立（browser_downloads 将退化为目录列举）: %s", tracker.error
            )

        return ToolResult(
            success=True,
            content={
                "browser_id": session.browser_id,
                "executable": session.executable,
                "headless": session.headless,
                "persistent": session.persistent,
                "profile_dir": session.user_data_dir,
                "download_dir": str(download_dir),
                "download_tracking": bool(tracker.connected),
                "note": (
                    "用 browser_navigate 打开页面；browser_close 结束会话。"
                    + ("持久 profile 关闭后登录态保留。" if session.persistent else "")
                ),
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
        try:
            session = _resolve_session(browser_id or None)
            if new_tab:
                created = cdp_command(session, "Target.createTarget", {"url": url.strip()}).get(
                    "targetId"
                )
                if not created:
                    return ToolResult(success=False, error="新标签页创建失败")
                _wait_page_settled(session, created, wait_for)
                info = _evaluate_json(
                    session,
                    "JSON.stringify({url:location.href,title:document.title})",
                    created,
                )
            else:
                result = cdp_command(session, "Page.navigate", {"url": url.strip()})
                if result.get("errorText"):
                    return ToolResult(success=False, error=f"导航失败: {result['errorText']}")
                _wait_page_settled(session, None, wait_for)
                info = _evaluate_json(
                    session,
                    "JSON.stringify({url:location.href,title:document.title})",
                    None,
                )
            page = json.loads(info) if isinstance(info, str) else {}
        except BrowserCDPError as exc:
            return _error(exc)
        return ToolResult(
            success=True,
            content={"url": page.get("url", url), "title": page.get("title", "")},
        )


class BrowserSnapshotTool(BaseTool):
    """读取当前页面：URL / 标题 / 可见文本（截断）。"""

    risk = RiskClass.READ
    is_blocking = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="browser_snapshot",
            description=(
                "读取当前页面的 URL、标题与可见文本（上限 30KiB，超出标记"
                " truncated）。这是浏览器'看页面'的主入口。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "browser_id": {"type": "string", "description": "单实例可省略"},
                },
                "required": [],
            },
        )

    def execute(self, browser_id: str = "", **kwargs: Any) -> ToolResult:
        if kwargs:
            return ToolResult(
                success=False,
                error=f"未知参数: {', '.join(sorted(kwargs))}（合法参数: browser_id）",
            )
        try:
            session = _resolve_session(browser_id or None)
            expression = (
                "JSON.stringify({url:location.href,title:document.title,"
                f"text:(document.body&&document.body.innerText||'').slice(0,{SNAPSHOT_TEXT_CAP})}})"
            )
            info = _evaluate_json(session, expression, None)
        except BrowserCDPError as exc:
            return _error(exc)
        if not isinstance(info, str):
            return ToolResult(success=False, error="页面快照返回异常（非 JSON）")
        page = json.loads(info)
        text = page.get("text") or ""
        return ToolResult(
            success=True,
            content={
                "url": page.get("url", ""),
                "title": page.get("title", ""),
                "text": text,
                "truncated": len(text) >= SNAPSHOT_TEXT_CAP,
            },
        )


class BrowserInteractTool(BaseTool):
    """点击 / 输入 / 按键 / 滚动（selector 或可见文本定位）。"""

    risk = RiskClass.WRITE_LOCAL
    is_blocking = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="browser_interact",
            description=(
                "与当前页面交互。action=click：selector 或 text（可见文本"
                "精确匹配）；action=type：selector + value（React 兼容，可"
                " clear=true 先清空）；action=press：key（Enter/Escape/Tab…"
                "）；action=scroll：value 为像素（正下负上）。操作后建议 "
                "browser_snapshot 确认效果。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "click | type | press | scroll"},
                    "selector": {"type": "string", "description": "CSS 选择器（click/type 用）"},
                    "text": {
                        "type": "string",
                        "description": "按可见文本定位（click 用，selector 缺省时生效）",
                    },
                    "value": {"type": "string", "description": "type 的输入内容 / scroll 的像素"},
                    "key": {"type": "string", "description": "press 的键名"},
                    "clear": {"type": "boolean", "description": "type 前先清空（默认 false）"},
                    "browser_id": {"type": "string", "description": "单实例可省略"},
                },
                "required": ["action"],
            },
        )

    def execute(
        self,
        action: str = "",
        selector: str = "",
        text: str = "",
        value: str = "",
        key: str = "",
        clear: bool = False,
        browser_id: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        rejection = _validate_interact_args(kwargs, action, selector, text, value, key)
        if rejection is not None:
            return rejection

        if action == "click":
            expression = _js_click(selector=selector, text=text)
        elif action == "type":
            expression = _js_type(selector, value, bool(clear))
        elif action == "press":
            expression = _js_press(key)
        else:
            expression = _js_scroll(int(value))

        try:
            session = _resolve_session(browser_id or None)
            outcome = _evaluate_json(session, expression, None)
        except BrowserCDPError as exc:
            return _error(exc)
        if not isinstance(outcome, dict):
            return ToolResult(success=False, error="交互结果异常（非 JSON）")
        if not outcome.get("ok"):
            return ToolResult(
                success=False,
                error=f"交互未生效: {outcome.get('info', 'unknown')}（可用 browser_snapshot 查看页面结构）",
            )
        return ToolResult(success=True, content={"action": action, "info": outcome.get("info", "")})


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
                "文件路径，可用 read_file/预览面板查看。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "保存路径（相对工作区，可选）"},
                    "browser_id": {"type": "string", "description": "单实例可省略"},
                },
                "required": [],
            },
        )

    def execute(self, path: str = "", browser_id: str = "", **kwargs: Any) -> ToolResult:
        if kwargs:
            return ToolResult(
                success=False,
                error=f"未知参数: {', '.join(sorted(kwargs))}（合法参数: path, browser_id）",
            )
        # 工作区检查在前（纯本地、便宜）；会话解析在后（可能打 CDP）
        root = self._policy.workspace_root
        if not root:
            return ToolResult(success=False, error="browser_screenshot 需要绑定工作区（workspace）")

        if path:
            target = Path(root) / path
        else:
            target = Path(root) / f"browser_screenshot_{time.strftime('%Y%m%d-%H%M%S')}.png"
        blocked = self._enforce_workspace(str(target))
        if blocked is not None:
            return blocked

        try:
            session = _resolve_session(browser_id or None)
            result = cdp_command(session, "Page.captureScreenshot", {"format": "png"})
            png_bytes = base64.b64decode(result.get("data") or "")
        except BrowserCDPError as exc:
            return _error(exc)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(png_bytes)
        except OSError as exc:
            return ToolResult(success=False, error=f"截图写入失败: {exc}")
        try:
            _record_artifact_safely(str(target), len(png_bytes))
        except Exception:  # noqa: BLE001 — artifact 记录失败不影响截图
            logger.warning("browser_screenshot artifact 记录失败", exc_info=True)
        return ToolResult(
            success=True,
            content={"path": str(target.resolve()), "bytes": len(png_bytes)},
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

    def execute(self, browser_id: str = "", target_id: str = "", **kwargs: Any) -> ToolResult:
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
            try:
                cdp_command(session, "Target.closeTarget", {"targetId": target_id})
            except BrowserCDPError as exc:
                return _error(exc)
            return ToolResult(success=True, content={"closed": "target", "target_id": target_id})

        from .browser_cdp import _terminate_session

        manager.remove(session.browser_id)
        _terminate_session(session)
        return ToolResult(
            success=True,
            content={"closed": "browser", "browser_id": session.browser_id},
        )


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
        try:
            session = _resolve_session(browser_id or None)
        except BrowserCDPError as exc:
            return _error(exc)
        try:
            wait_seconds = float(timeout)
        except (TypeError, ValueError):
            return ToolResult(success=False, error="timeout 必须是数字")
        wait_seconds = max(0.0, min(wait_seconds, MAX_WAIT_TIMEOUT))

        tracker = get_download_tracker(session.browser_id)
        if tracker is None or not tracker.connected:
            root = self._policy.workspace_root
            download_dir = (
                tracker.download_dir
                if tracker is not None
                else str(Path(root) / "downloads" if root else browser_downloads_root())
            )
            items = list_download_dir(download_dir)
            if wait_for_complete and any(i["state"] == "inProgress" for i in items):
                deadline = time.monotonic() + wait_seconds
                while time.monotonic() < deadline:
                    time.sleep(0.5)
                    items = list_download_dir(download_dir)
                    if not any(i["state"] == "inProgress" for i in items):
                        break
            return ToolResult(
                success=True,
                content={
                    "browser_id": session.browser_id,
                    "download_dir": download_dir,
                    "tracking": False,
                    "downloads": items,
                    "note": (
                        "下载事件通道不可用"
                        + (f"（{tracker.error}）" if tracker is not None and tracker.error else "")
                        + "，以上为下载目录列举（.crdownload = 进行中）。"
                    ),
                },
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
        return ToolResult(success=True, content=content)


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
        from .credential_vault import save_credential

        by_domain: Dict[str, list] = {}
        now = time.time()
        for item in raw_cookies:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            cookie_domain = str(item.get("domain") or "").lower()
            if not cookie_domain:
                continue
            by_domain.setdefault(cookie_domain, []).append(item)
        saved = []
        for cookie_domain, cookies in sorted(by_domain.items()):
            save_credential(
                cookie_domain,
                cookies,
                source_profile=str(getattr(session, "profile_name", "") or ""),
            )
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
_LOGIN_BANNER_JS = """
(function() {
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


class BrowserLoginTool(BaseTool):
    """一键登录站点：打开可见浏览器 → 用户登录 → 自动保存 cookie。

    把 ``browser_launch`` + ``browser_navigate`` + 用户手动登录 +
    ``browser_cookies(action=export)`` 四步合为单一工具调用。用户无需理解
    cookie/导出等概念，只需在弹出的浏览器窗口完成登录即可。

    登录完成检测（轮询）：
    - 当前 URL 不再是登录页（``looks_like_login_url()`` 返回 False）
    - 页面没有密码输入框（``looks_like_login_html()`` 返回 False）
    - 浏览器有目标域的 cookie（``Network.getCookies`` 返回列表）

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
                },
                "required": ["url"],
            },
        )

    def execute(
        self,
        url: str = "",
        timeout_seconds: int = _LOGIN_DEFAULT_TIMEOUT,
        **kwargs: Any,
    ) -> ToolResult:
        if kwargs:
            return ToolResult(
                success=False,
                error=(
                    f"未知参数: {', '.join(sorted(kwargs))}"
                    "（合法参数: url, timeout_seconds）"
                ),
            )
        url = (url or "").strip()
        if not url:
            return ToolResult(success=False, error="url 不能为空")
        if not url.startswith(("http://", "https://")):
            return ToolResult(success=False, error="url 必须以 http:// 或 https:// 开头")

        # 提取目标域名用于后续 cookie 匹配
        parsed = urlsplit(url)
        target_host = (parsed.hostname or "").lower()
        if not target_host:
            return ToolResult(success=False, error="无法从 url 解析出域名")

        # 检查是否已有活跃的登录浏览器（避免重复启动）
        manager = get_browser_manager()
        existing = manager.get(_LOGIN_PROFILE_NAME)
        if existing is not None and existing.is_alive():
            # 复用已有浏览器，直接导航到目标 URL
            session = existing
            reuse = True
        else:
            # 启动新的可见持久浏览器
            try:
                session = launch_browser(
                    headless=False,
                    browser_id=_LOGIN_PROFILE_NAME,
                    persistent=True,
                    profile_name=_LOGIN_PROFILE_NAME,
                )
            except BrowserCDPError as exc:
                return ToolResult(
                    success=False,
                    error=f"browser_launch_failed: 无法启动浏览器（{exc}）",
                )
            reuse = False

        # 创建新标签页并导航到目标 URL
        target_id: Optional[str] = None
        try:
            created = cdp_command(session, "Target.createTarget", {"url": url})
            target_id = created.get("targetId")
            if not target_id:
                return ToolResult(success=False, error="导航失败：无法创建标签页")

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

            # 导出并保存 cookie
            saved_domains = self._export_cookies(session, target_host)

            if saved_domains:
                return ToolResult(
                    success=True,
                    content={
                        "saved_domains": saved_domains,
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
                    },
                )
            else:
                return ToolResult(
                    success=False,
                    error=(
                        "no_cookies_saved: 未找到可保存的 cookie。"
                        "请确认已经在浏览器窗口中完成登录。"
                    ),
                )

        except BrowserCDPError as exc:
            # 容错：若用户手动关闭了窗口/标签页，尝试检查是否已有保存的 cookies
            try:
                saved_domains = self._export_cookies(session, target_host)
                if saved_domains:
                    return ToolResult(
                        success=True,
                        content={
                            "saved_domains": saved_domains,
                            "note": (
                                f"登录窗口已关闭，检测并成功保存了 {target_host} 的登录态。"
                            ),
                            "instruction": (
                                f"请立即调用 web_fetch 工具访问 {url}，并将获取到的页面内容呈现给用户。"
                            ),
                            "browser_id": getattr(session, "browser_id", ""),
                            "reused": reuse,
                        },
                    )
            except Exception:
                pass
            return ToolResult(
                success=False,
                error=f"browser_error: {exc}",
            )
        finally:
            # 关闭标签页但保持浏览器运行（用户可能还要操作其他页面）
            if target_id:
                try:
                    cdp_command(session, "Target.closeTarget", {"targetId": target_id})
                except BrowserCDPError:
                    pass

    def _export_cookies(
        self, session: "BrowserSession", target_host: str
    ) -> list:
        """从浏览器获取 cookie 并按 domain 分组保存。返回已保存的 domain 列表。"""
        from .credential_vault import save_credential

        try:
            result = cdp_command(session, "Network.getCookies", {})
        except BrowserCDPError:
            return []

        raw_cookies = result.get("cookies") or []
        if not raw_cookies:
            return []

        # 按 domain 分组
        by_domain: Dict[str, list] = {}
        for item in raw_cookies:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            cookie_domain = str(item.get("domain") or "").lower()
            if not cookie_domain:
                continue
            by_domain.setdefault(cookie_domain, []).append(item)

        saved = []
        profile_name = getattr(session, "profile_name", "") or ""
        for cookie_domain, cookies in sorted(by_domain.items()):
            try:
                save_credential(
                    cookie_domain,
                    cookies,
                    source_profile=str(profile_name),
                )
                saved.append(cookie_domain)
            except Exception:
                # 单个 domain 保存失败不影响其他
                pass

        return saved


def _wait_for_page_load(
    session: "BrowserSession", target_id: str, timeout: float = 15.0
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
    session: "BrowserSession", target_id: str, target_host: str
) -> str:
    """检查登录状态。返回 'logged_in' / 'on_login_page' / 'loading'。"""
    from .credential_vault import looks_like_login_html, looks_like_login_url

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
            # 额外验证：有目标域 cookie 才算真正登录
            try:
                cookies_result = cdp_command(session, "Network.getCookies", {})
                cookies = cookies_result.get("cookies") or []
                for c in cookies:
                    if isinstance(c, dict):
                        cdomain = str(c.get("domain") or "").lower().lstrip(".")
                        if cdomain and (
                            target_host == cdomain or target_host.endswith("." + cdomain)
                        ):
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
)
