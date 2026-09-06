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
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from backend.domain.risk import RiskClass

from .base import BaseTool, ToolResult, ToolSchema
from .browser_cdp import (
    BrowserCDPError,
    BrowserSession,
    cdp_command,
    get_browser_manager,
    launch_browser,
)
from .file_tool import _record_artifact_safely

logger = logging.getLogger(__name__)

#: 页面文本快照上限（字节，超出截断）
SNAPSHOT_TEXT_CAP = 30 * 1024

#: navigate 后等待 document.readyState=complete 的轮询窗口
_LOAD_SETTLE_SECONDS = 10.0
_LOAD_POLL_INTERVAL = 0.3

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


def _validate_action_args(action: str, selector: str, text: str, value: str) -> Optional[ToolResult]:
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


def _wait_page_settled(session: BrowserSession, target_id: Optional[str]) -> None:
    """navigate 后轮询 readyState，避免 LLM 拿到半加载页。"""
    deadline = time.monotonic() + _LOAD_SETTLE_SECONDS
    while time.monotonic() < deadline:
        try:
            state = _evaluate_json(session, "document.readyState", target_id)
        except BrowserCDPError:
            return  # 导航引发的上下文销毁 —— 交给后续调用自查
        if state in ("complete", "interactive"):
            return
        time.sleep(_LOAD_POLL_INTERVAL)


# ---------------------------------------------------------------------------
# 工具定义
# ---------------------------------------------------------------------------


class BrowserLaunchTool(BaseTool):
    """启动一个受控浏览器实例（独立临时 profile，不影响用户浏览器）。"""

    risk = RiskClass.EXEC
    is_blocking = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="browser_launch",
            description=(
                "启动一个受控浏览器实例（Chrome/Edge，独立临时配置目录）。"
                "返回 browser_id，后续 browser_* 工具用它与浏览器交互。"
                "headless 默认 true（无窗口）；需要可视化调试时传 false。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "headless": {"type": "boolean", "description": "无头模式（默认 true）"},
                },
                "required": [],
            },
        )

    def execute(self, headless: bool = True, **kwargs: Any) -> ToolResult:
        if kwargs:
            return ToolResult(
                success=False,
                error=f"未知参数: {', '.join(sorted(kwargs))}（合法参数: headless）",
            )
        try:
            session = launch_browser(headless=bool(headless))
        except BrowserCDPError as exc:
            return _error(exc)
        return ToolResult(
            success=True,
            content={
                "browser_id": session.browser_id,
                "executable": session.executable,
                "headless": session.headless,
                "note": "用 browser_navigate 打开页面；browser_close 结束会话。",
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
                "被拒绝）。等待页面基本加载后返回标题与最终 URL。多实例时"
                "传 browser_id。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "目标 URL"},
                    "browser_id": {"type": "string", "description": "browser_launch 返回的 id（单实例可省略）"},
                    "new_tab": {"type": "boolean", "description": "在新标签页打开（默认 false，用当前页）"},
                },
                "required": ["url"],
            },
        )

    def execute(
        self, url: str = "", browser_id: str = "", new_tab: bool = False, **kwargs: Any
    ) -> ToolResult:
        if kwargs:
            return ToolResult(
                success=False,
                error=f"未知参数: {', '.join(sorted(kwargs))}（合法参数: url, browser_id, new_tab）",
            )
        scheme_error = validate_url(url)
        if scheme_error is not None:
            return ToolResult(success=False, error=scheme_error)
        try:
            session = _resolve_session(browser_id or None)
            if new_tab:
                created = cdp_command(
                    session, "Target.createTarget", {"url": url.strip()}
                ).get("targetId")
                if not created:
                    return ToolResult(success=False, error="新标签页创建失败")
                _wait_page_settled(session, created)
                info = _evaluate_json(
                    session,
                    "JSON.stringify({url:location.href,title:document.title})",
                    created,
                )
            else:
                result = cdp_command(session, "Page.navigate", {"url": url.strip()})
                if result.get("errorText"):
                    return ToolResult(success=False, error=f"导航失败: {result['errorText']}")
                _wait_page_settled(session, None)
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
                    "text": {"type": "string", "description": "按可见文本定位（click 用，selector 缺省时生效）"},
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
        from pathlib import Path as _Path

        if path:
            target = _Path(root) / path
        else:
            target = _Path(root) / f"browser_screenshot_{time.strftime('%Y%m%d-%H%M%S')}.png"
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
            return ToolResult(
                success=True, content={"closed": "target", "target_id": target_id}
            )

        from .browser_cdp import _terminate_session

        manager.remove(session.browser_id)
        _terminate_session(session)
        return ToolResult(
            success=True,
            content={"closed": "browser", "browser_id": session.browser_id},
        )


__all__ = [
    "BROWSER_TOOL_NAMES",
    "BrowserCloseTool",
    "BrowserInteractTool",
    "BrowserLaunchTool",
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
    "browser_close",
)
