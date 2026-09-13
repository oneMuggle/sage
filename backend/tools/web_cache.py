# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""web_fetch 抓取缓存 —— 进程内 TTL + LRU（方案 Round 2 C1）。

设计要点：

- **纯内存、进程内**：不落盘 —— 无静态泄密面；后端进程退出即清空。
- **TTL 15 分钟 + LRU 50 条**：对齐主流工具（ZCode WebFetch 15min）；
  超限淘汰最久未用条目。
- **键含 mode**：text/links/tables 抽取产物结构不同，按 mode 分键，
  命中后仅按本次 max_length 重新裁剪正文。
- **调用方豁免**：`credential_domain` 请求（登录态时效）与 `mode=raw`
  （原始 HTML 体积大、重复价值低）由 web_fetch 侧决定不入/不读缓存。
- 线程安全：工具在 executor 线程执行，全部读写持锁。

py3.8 纪律：from __future__ import annotations + typing.*（win7 对齐）。
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Optional, Tuple

#: 缓存存活时长（秒）
CACHE_TTL_SECONDS = 15 * 60

#: 最大条目数（超出淘汰最久未用）
CACHE_MAX_ENTRIES = 50

_lock = threading.Lock()
_cache: OrderedDict[str, Tuple[float, Dict[str, Any]]] = OrderedDict()


def normalize_url(url: str) -> str:
    """缓存键用 URL 规范化：去空白、去 fragment（query 保留）。"""
    normalized = (url or "").strip()
    fragment_at = normalized.find("#")
    if fragment_at >= 0:
        normalized = normalized[:fragment_at]
    return normalized


def _key(url: str, mode: str) -> str:
    return normalize_url(url) + "\x00" + (mode or "")


def get(url: str, mode: str) -> Optional[Dict[str, Any]]:
    """取缓存；未命中/过期返回 ``None``。命中即刷新 LRU 位次。"""
    key = _key(url, mode)
    now = time.monotonic()
    with _lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        stored_at, payload = entry
        if now - stored_at > CACHE_TTL_SECONDS:
            del _cache[key]
            return None
        _cache.move_to_end(key)
        return dict(payload)


def put(url: str, mode: str, payload: Dict[str, Any]) -> None:
    """存缓存（浅拷贝防御；调用方后续修改不影响缓存内容）。"""
    key = _key(url, mode)
    now = time.monotonic()
    with _lock:
        _cache[key] = (now, dict(payload))
        _cache.move_to_end(key)
        while len(_cache) > CACHE_MAX_ENTRIES:
            _cache.popitem(last=False)


def clear() -> None:
    """清空缓存（测试钩子 / 设置变更钩子）。"""
    with _lock:
        _cache.clear()


def size() -> int:
    """当前条目数（测试/诊断用）。"""
    with _lock:
        return len(_cache)


__all__ = [
    "CACHE_MAX_ENTRIES",
    "CACHE_TTL_SECONDS",
    "clear",
    "get",
    "normalize_url",
    "put",
    "size",
]
