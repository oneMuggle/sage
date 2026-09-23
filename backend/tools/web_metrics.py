# ruff: noqa: UP006, UP007, UP035, UP038, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Per-host 出网指标（Round 15 X2 延伸）：线程安全滚动记录，进程内存态。

- key = URL host（小写）；每域名 deque(maxlen=100)，全局域名 LRU 上限 200；
- 重启清零——定位为"诊断视角"而非审计；任何异常静默，指标永不影响主流程；
- ``snapshot()`` 供 GET /api/v1/web-access/metrics 读取（设置页健康视角），
  ``reset()`` 供诊断用清零。
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Dict
from urllib.parse import urlparse

#: 每个域名保留的最近记录条数
RECORDS_PER_HOST = 100

#: 全局域名上限（超出淘汰最久未更新的域名）
MAX_HOSTS = 200

_lock = threading.Lock()
_hosts: Dict[str, deque] = {}
_order: Dict[str, int] = {}
_seq = 0

# R24：渲染分支 Network 事件命中率（全局计数，诊断视角）——
# renders=成功渲染次数；channel_ok=渲染池事件通道就绪次数；
# event_status_hits=事件 Document 状态被采用（优先于 Navigation Timing）次数。
_render_events = {"renders": 0, "channel_ok": 0, "event_status_hits": 0}


def record_render_event(channel_ok: bool, tracked_hit: bool) -> None:
    """记录一次渲染的事件状态可用性（R24）；异常静默，永不影响主流程。"""
    try:
        with _lock:
            _render_events["renders"] += 1
            if channel_ok:
                _render_events["channel_ok"] += 1
            if tracked_hit:
                _render_events["event_status_hits"] += 1
    except Exception:  # noqa: BLE001 — 指标静默
        pass


def record(host: str, ok: bool, elapsed_ms: int, escalated: bool = False) -> None:
    """记录一次出网结果。``host`` 为空时忽略；其余异常静默。"""
    global _seq
    try:
        host = (host or "").strip().lower()
        if not host:
            return
        with _lock:
            dq = _hosts.get(host)
            if dq is None:
                if len(_hosts) >= MAX_HOSTS:
                    oldest = min(_order, key=_order.get)
                    _hosts.pop(oldest, None)
                    _order.pop(oldest, None)
                dq = deque(maxlen=RECORDS_PER_HOST)
                _hosts[host] = dq
            dq.append(
                {
                    "ok": bool(ok),
                    "escalated": bool(escalated),
                    "elapsed_ms": int(elapsed_ms),
                    "ts": time.time(),
                }
            )
            # LRU 序用进程内递增序号：Windows monotonic 精度不足时并列会导致
            # 淘汰目标不确定
            _seq += 1
            _order[host] = _seq
    except Exception:  # noqa: BLE001 — 指标静默
        pass


def snapshot() -> Dict[str, Dict[str, Any]]:
    """聚合快照：``{host: {ok, fail, escalated, avg_elapsed_ms}}``（按域名排序）
    外加 ``render_events``（R24 渲染事件命中率全局计数）。"""
    with _lock:
        items = sorted(_hosts.items())
        render_events = dict(_render_events)
    out: Dict[str, Dict[str, Any]] = {}
    for host, dq in items:
        records = list(dq)
        ok_n = sum(1 for r in records if r["ok"])
        esc_n = sum(1 for r in records if r.get("escalated"))
        elapsed = [r["elapsed_ms"] for r in records if r["ok"]]
        out[host] = {
            "ok": ok_n,
            "fail": len(records) - ok_n,
            "escalated": esc_n,
            "avg_elapsed_ms": int(sum(elapsed) / len(elapsed)) if elapsed else None,
        }
    out["render_events"] = render_events
    return out


def reset() -> None:
    with _lock:
        _hosts.clear()
        _order.clear()
        _render_events.update({"renders": 0, "channel_ok": 0, "event_status_hits": 0})


def host_from_url(url: str) -> str:
    return (urlparse(url or "").hostname or "").lower()
