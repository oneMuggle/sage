"""对标 S3（2026-09-13）：会话级"自动放行"审计台账。

竞品对标 §2.3 —— 权限三档一键切换后，用户需要看到"本会话已自动批准 N 次"
并能回看清单（PHILOSOPHY「透明可控」落地）。权限执行器（``PermissionEnforcer``）
的 allow 决策此前只留 debug 日志；本台账在 run_loop 分发前记录每一次
**未经用户确认即放行** 的工具调用（模式矩阵 / allow 规则命中），按会话
保存在进程内环形缓冲中。

- 用户手动批准的调用（needs_approval → approved）**不计入**：那是用户决定，
  不是"自动"。
- 只读工具（READ 能力）默认也记录，但带 ``capability`` 字段供前端分组/过滤；
  计数 API 默认只统计 WRITE / EXECUTE（真正有副作用的放行）。
- 进程内、重启即清；与 ``write_ledger`` 同一设计取向。
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from dataclasses import asdict, dataclass
from typing import Any, Deque, Dict, List, Optional

PER_SESSION_LIMIT = 200
SESSION_LIMIT = 64
SIDE_EFFECT_CAPABILITIES = ("write", "execute")


@dataclass(frozen=True)
class AutoApproval:
    seq: int
    session_id: str
    tool_name: str
    capability: str  # read / write / execute
    mode: str  # permission mode at decision time
    reason: str
    summary: str  # 参数摘要（命令 / 路径），已截断
    created_at: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def summarize_args(tool_name: str, args: Optional[Dict[str, Any]], limit: int = 160) -> str:
    """把工具参数压成一行可读摘要：优先 command / path / file_path / query。"""
    args = args or {}
    for key in ("command", "path", "file_path", "target", "query", "name", "url"):
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            text = " ".join(val.split())
            return text if len(text) <= limit else text[: limit - 1] + "…"
    if not args:
        return ""
    keys = ", ".join(sorted(str(k) for k in args)[:6])
    return f"args: {keys}"


class AutoApprovalLedger:
    def __init__(self, per_session_limit: int = PER_SESSION_LIMIT, session_limit: int = SESSION_LIMIT) -> None:
        self._per_session_limit = per_session_limit
        self._session_limit = session_limit
        self._buckets: OrderedDict[str, Deque[AutoApproval]] = OrderedDict()
        self._seq = 0
        self._lock = threading.Lock()

    def record(
        self,
        *,
        session_id: Optional[str],
        tool_name: str,
        capability: str,
        mode: str,
        reason: str,
        args: Optional[Dict[str, Any]] = None,
    ) -> Optional[AutoApproval]:
        if not session_id or not tool_name:
            return None
        with self._lock:
            self._seq += 1
            rec = AutoApproval(
                seq=self._seq,
                session_id=session_id,
                tool_name=tool_name,
                capability=str(capability or "write"),
                mode=str(mode or ""),
                reason=str(reason or "")[:200],
                summary=summarize_args(tool_name, args),
                created_at=time.time(),
            )
            bucket = self._buckets.get(session_id)
            if bucket is None:
                bucket = deque(maxlen=self._per_session_limit)
                self._buckets[session_id] = bucket
                while len(self._buckets) > self._session_limit:
                    self._buckets.popitem(last=False)
            else:
                self._buckets.move_to_end(session_id)
            bucket.append(rec)
            return rec

    def list(self, session_id: str, limit: int = 50, side_effect_only: bool = False) -> List[AutoApproval]:
        with self._lock:
            bucket = self._buckets.get(session_id)
            if not bucket:
                return []
            items = list(bucket)
        if side_effect_only:
            items = [i for i in items if i.capability in SIDE_EFFECT_CAPABILITIES]
        return items[-max(1, limit):]

    def count(self, session_id: str, side_effect_only: bool = True) -> int:
        with self._lock:
            bucket = self._buckets.get(session_id)
            if not bucket:
                return 0
            if not side_effect_only:
                return len(bucket)
            return sum(1 for i in bucket if i.capability in SIDE_EFFECT_CAPABILITIES)

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._buckets.pop(session_id, None)


_ledger: Optional[AutoApprovalLedger] = None
_ledger_lock = threading.Lock()


def get_auto_approval_ledger() -> AutoApprovalLedger:
    global _ledger
    if _ledger is None:
        with _ledger_lock:
            if _ledger is None:
                _ledger = AutoApprovalLedger()
    return _ledger


def reset_auto_approval_ledger() -> None:
    global _ledger
    with _ledger_lock:
        _ledger = None


__all__ = [
    "AutoApproval",
    "AutoApprovalLedger",
    "get_auto_approval_ledger",
    "reset_auto_approval_ledger",
    "summarize_args",
]
