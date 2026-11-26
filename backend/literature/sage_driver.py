"""把 Sage 工具桥（``sage.call``）适配成 ``BrowserDriver``。

在 ``execute_code`` 中用法::

    from backend.literature.sage_driver import SageToolDriver
    driver = SageToolDriver(sage.call)

不直接 import browser 工具，保持文献层与工具层解耦。
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, List, Optional

_MAX_SLEEP_S = 30.0


class SageToolDriver:
    def __init__(self, call: Callable[..., Any]):
        self._call = call
        self._url = ""
        self._title = ""
        self._browser_ready = False

    @staticmethod
    def _as_dict(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return {"text": value}
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        return {"value": value}

    def _tool(self, tool_name: str, **kwargs: Any) -> Any:
        return self._call(tool_name, **kwargs)

    def navigate(self, url: str, wait_for: str = "") -> str:
        args: Dict[str, Any] = {"url": url}
        if wait_for:
            args["wait_for"] = wait_for
        data = self._as_dict(self._tool("browser_navigate", **args))
        meta = self._as_dict(data.get("browser_meta") or {})
        self._url = str(data.get("url") or meta.get("url") or url)
        self._title = str(data.get("title") or meta.get("title") or "")
        self._browser_ready = True
        return self._url

    def fetch_text(self, url: str) -> Optional[str]:
        """快速通道：用 ``web_fetch`` 取正文（自带 cookie 域名自动推断）。

        登录墙 / 反爬 / 工具不可用时返回 ``None``，调用方回落到浏览器通道。
        """
        try:
            data = self._as_dict(self._tool("web_fetch", url=url, mode="text"))
        except Exception:  # noqa: BLE001 — 快路径任何失败都应回落到浏览器
            return None
        text = str(data.get("content") or "").strip()
        if not text:
            return None
        self._url = str(data.get("url") or url)
        self._title = str(data.get("title") or "")
        return text

    def snapshot(self) -> str:
        data = self._as_dict(
            self._tool("browser_snapshot", mode="full", max_nodes=250)
        )
        meta = self._as_dict(data.get("browser_meta") or {})
        self._url = str(data.get("url") or meta.get("url") or self._url)
        self._title = str(data.get("title") or meta.get("title") or self._title)
        return json.dumps(data, ensure_ascii=False)

    def _ensure_browser(self) -> None:
        """交互前确保浏览器已有页面。

        快路径（``fetch_text``）只走 HTTP，浏览器此时没有页面；
        若后续要点 DOM 元素（如 PDF 下载入口），先补一次导航。
        """
        if self._browser_ready or not self._url:
            return
        self._tool("browser_navigate", url=self._url)
        self._browser_ready = True

    def click(self, target: str) -> None:
        self._ensure_browser()
        self._tool("browser_interact", action="click", selector=target)

    def click_text(self, text: str) -> None:
        self._ensure_browser()
        self._tool("browser_interact", action="click", text=text)

    def type_text(self, selector: str, text: str, clear: bool = True) -> bool:
        self._ensure_browser()
        try:
            self._tool(
                "browser_interact",
                action="type",
                selector=selector,
                value=text,
                clear=clear,
            )
            return True
        except RuntimeError:
            return False

    def press_key(self, key: str) -> None:
        self._ensure_browser()
        self._tool("browser_interact", action="press", key=key)

    def sleep(self, seconds: float) -> None:
        time.sleep(max(0.0, min(float(seconds), _MAX_SLEEP_S)))

    def current_url(self) -> str:
        return self._url

    def current_title(self) -> str:
        return self._title

    def element_attr(self, selector: str, name: str = "href") -> str:
        """读取元素属性（如下载链接的完整 href，含站点签名参数）。"""
        self._ensure_browser()
        data = self._as_dict(
            self._tool(
                "browser_interact", action="attr", selector=selector, attr_name=name
            )
        )
        return str(data.get("info") or "")

    def tabs(self) -> List[Dict[str, Any]]:
        """列出当前浏览器会话的标签页（tab_id / url / title / active）。"""
        data = self._as_dict(self._tool("browser_tabs", action="list"))
        return [tab for tab in (data.get("tabs") or []) if isinstance(tab, dict)]

    def open_tab(self, url: str) -> str:
        """新开标签页并设为活动页，返回 tab_id（拿不到时为空串）。"""
        data = self._as_dict(self._tool("browser_tabs", action="create", url=url))
        self._browser_ready = True
        return str(data.get("tab_id") or "")

    def focus_tab(self, tab_id: str) -> None:
        if tab_id:
            self._tool("browser_tabs", action="switch", tab_id=tab_id)

    def close_tab(self, tab_id: str) -> None:
        if tab_id:
            self._tool("browser_tabs", action="close", tab_id=tab_id)

    def wait_download(self, timeout_s: float = 60) -> Optional[str]:
        data = self._as_dict(
            self._tool(
                "browser_downloads", wait_for_complete=True, timeout=timeout_s
            )
        )
        downloads: List[Dict[str, Any]] = list(data.get("downloads") or [])
        completed = [
            item
            for item in downloads
            if item.get("state") == "completed" and item.get("path")
        ]
        if not completed:
            return None
        completed.sort(key=lambda item: item.get("modified_at", 0), reverse=True)
        return str(completed[0]["path"])


__all__ = ["SageToolDriver"]
