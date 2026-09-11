"""进程级 ring buffer,保存最近 N 次 LLM 调用的元数据与 body。

设计要点:
- 全局单例: backend 进程一个实例,所有 LLM 代理代码共享
- deque(maxlen=N) 自动 FIFO 淘汰
- append 是 CPython GIL 下原子操作,无锁
- 不持久化: 进程重启即丢,符合"出错时点一下"的语义
"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Deque, Dict, List, Optional

MAX_TRACE_RECORDS = 50


@dataclass(frozen=True)
class TraceRecord:
    """一次 LLM 调用的完整快照(用于诊断包导出)。

    字段不可变,append 后不允许修改;若需修改请新建 record。
    request/response body 用 bytes 存,避免序列化时再编码丢信息。
    """

    trace_id: str
    ts: datetime
    endpoint: str
    upstream_url: str
    upstream_method: str
    request_headers: Dict[str, str]
    request_body: bytes
    response_status: Optional[int]
    response_headers: Dict[str, str]
    response_body: bytes
    response_streamed: bool
    duration_ms: int
    error_class: Optional[str] = None


class _Recorder:
    """线程安全的 ring buffer。"""

    def __init__(self, maxlen: int = MAX_TRACE_RECORDS) -> None:
        self._buf: Deque[TraceRecord] = deque(maxlen=maxlen)
        self._lock = threading.Lock()  # snapshot 期间防止迭代时被改

    def append(self, record: TraceRecord) -> None:
        # deque.append 是 CPython GIL 下原子的,无需持锁
        self._buf.append(record)

    def snapshot(self) -> List[TraceRecord]:
        with self._lock:
            return list(self._buf)

    def count(self) -> int:
        return len(self._buf)

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()


# 全局单例,backend 进程共享一个实例
_global_recorder = _Recorder()


# 对外 API
class LlmTraceRecorder:
    """单例 facade,所有调用走 classmethod。"""

    @classmethod
    def append(cls, record: TraceRecord) -> None:
        _global_recorder.append(record)

    @classmethod
    def snapshot(cls) -> List[TraceRecord]:
        return _global_recorder.snapshot()

    @classmethod
    def count(cls) -> int:
        return _global_recorder.count()

    @classmethod
    def clear(cls) -> None:
        _global_recorder.clear()
