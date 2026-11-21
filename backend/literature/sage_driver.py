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

    def _tool(self, name: str, **kwargs: Any) -> Any:
        return self._call(name, **kwargs)

    def navigate(self, url: str, wait_for: str = "") -> str:
        args: Dict[str, Any] = {"url": url}
        if wait_for:
            args["wait_for"] = wait_for
        data = self._as_dict(self._tool("browser_navigate", **args))
        meta = self._as_dict(data.get("browser_meta") or {})
        self._url = str(data.get("url") or meta.get("url") or url)
        self._title = str(data.get("title") or meta.get("title") or "")
        return self._url

    def snapshot(self) -> str:
        data = self._as_dict(
            self._tool("browser_snapshot", mode="full", max_nodes=250)
        )
        meta = self._as_dict(data.get("browser_meta") or {})
        self._url = str(data.get("url") or meta.get("url") or self._url)
        self._title = str(data.get("title") or meta.get("title") or self._title)
        return json.dumps(data, ensure_ascii=False)

    def click(self, target: str) -> None:
        self._tool("browser_interact", action="click", selector=target)

    def click_text(self, text: str) -> None:
        self._tool("browser_interact", action="click", text=text)

    def type_text(self, selector: str, text: str, clear: bool = True) -> bool:
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
        self._tool("browser_interact", action="press", key=key)

    def sleep(self, seconds: float) -> None:
        time.sleep(max(0.0, min(float(seconds), _MAX_SLEEP_S)))

    def current_url(self) -> str:
        return self._url

    def current_title(self) -> str:
        return self._title

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
