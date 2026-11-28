"""HTTP per-host 最小间隔限速器（spec §5.5）。

存在的理由：profile 的 ``rate_limit.min_interval_s`` 此前**只是渲染给模型看的
文本**，全仓没有执行点 —— 限速等于没有。本模块把它变成真实闸门。

两层下限：
- 通用层 ``DEFAULT_MIN_INTERVAL_S``（1 秒）—— 防止通用 HTTP 工具被用来打站点；
- 文献层 ``LITERATURE_FLOOR_S``（3 秒）—— profile 即使写 ``0`` 也不放行。

存储：进程内 per-host 时间戳表（线程安全）。运行目录内的累计次数由
``run_store.record_download`` 负责，与本模块互补。
"""

from __future__ import annotations

import threading
import time
from typing import Dict, Optional

#: 通用层默认最小间隔（秒）。
DEFAULT_MIN_INTERVAL_S = 1.0
#: 文献层的强制下限（秒）—— profile 写 0 也不放行。
LITERATURE_FLOOR_S = 3.0


class HttpRateLimiter:
    """per-host 最小间隔限速器。"""

    def __init__(
        self,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        floor_s: float = 0.0,
    ) -> None:
        """
        Args:
            min_interval_s: 上层声明的最小间隔（来自 profile ``rate_limit``）。
            floor_s: 强制下限；实际间隔 = ``max(min_interval_s, floor_s)``。
        """
        self._min_interval_s = max(0.0, float(min_interval_s))
        self._floor_s = max(0.0, float(floor_s))
        self._last_seen: Dict[str, float] = {}
        self._lock = threading.Lock()

    @property
    def effective_interval_s(self) -> float:
        """实际生效的最小间隔（秒）。"""
        return max(self._min_interval_s, self._floor_s)

    def reserve(self, host: str, now: Optional[float] = None) -> float:
        """为一次请求占位；返回需要等待的秒数（0 = 立即放行）。

        Args:
            host: 目标主机名。
            now: 当前时刻（``time.monotonic()`` 语义），测试可注入。
        """
        key = str(host or "").strip().lower()
        if not key:
            return 0.0
        current = time.monotonic() if now is None else float(now)
        interval = self.effective_interval_s
        with self._lock:
            previous = self._last_seen.get(key)
            self._last_seen[key] = current
        if previous is None or interval <= 0.0:
            return 0.0
        elapsed = current - previous
        if elapsed >= interval:
            return 0.0
        return interval - elapsed

    def reset(self) -> None:
        """清空所有 host 的时间戳（测试与运行目录切换时用）。"""
        with self._lock:
            self._last_seen.clear()


_DEFAULT_LIMITER: Optional[HttpRateLimiter] = None
_DEFAULT_LOCK = threading.Lock()


def get_default_limiter() -> HttpRateLimiter:
    """返回进程级默认限速器（通用下限，无文献层 floor）。"""
    global _DEFAULT_LIMITER
    if _DEFAULT_LIMITER is None:
        with _DEFAULT_LOCK:
            if _DEFAULT_LIMITER is None:
                _DEFAULT_LIMITER = HttpRateLimiter()
    return _DEFAULT_LIMITER


def reset_default_limiter() -> None:
    """重置进程级默认限速器（测试用）。"""
    global _DEFAULT_LIMITER
    with _DEFAULT_LOCK:
        _DEFAULT_LIMITER = None
