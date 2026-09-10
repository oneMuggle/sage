"""嵌入编码队列 (T2, P10)

语义嵌入 (Onnx) 的单条推理 ~10-50ms, 若在事件循环上同步执行会阻塞
save 路径与并发请求。本模块提供单 worker 线程的后台队列: 记忆写入
路径把 ``vector_store.add`` 任务入队后立即返回, 编码+落库在 worker
线程完成。

语义:
- best-effort: 任务失败只记日志, 不重试不持久化 (与向量写入本身的
  best-effort 定位一致; Hash 路径仍为同步写入, 写入即见)。
- 惰性启动: 首次 enqueue 才创建 worker 线程; 进程退出时 daemon 线程
  随进程终止 (丢失尾部的未编码任务可接受 —— 下次检索无该条, 不影响
  已有数据)。
- 队列上限: 有界队列 (默认 1000), 满时丢弃最旧任务并告警, 防止
  写入风暴下无限膨胀。
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_MAX_QUEUE_SIZE = 1000
_SENTINEL = object()

_queue: queue.Queue = queue.Queue(maxsize=_MAX_QUEUE_SIZE)
_worker: Optional[threading.Thread] = None  # py38: Optional[Thread]
_lock = threading.Lock()
_dropped = 0


def _drain() -> None:
    """worker 主循环: 逐任务执行, 异常吞掉只记日志。"""
    while True:
        task = _queue.get()
        try:
            if task is _SENTINEL:
                return
            func, args, kwargs = task
            try:
                func(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 — best-effort 编码
                logger.warning(f"embedding queue: task failed: {exc}")
        finally:
            _queue.task_done()


def _ensure_worker() -> None:
    global _worker
    with _lock:
        if _worker is not None and _worker.is_alive():
            return
        _worker = threading.Thread(target=_drain, name="sage-embedding-queue", daemon=True)
        _worker.start()


def enqueue(func: Callable[..., Any], *args: Any, **kwargs: Any) -> bool:
    """入队一个编码任务, 立即返回。

    Returns:
        True = 已入队; False = 队列满被丢弃 (已告警)。
    """
    _ensure_worker()
    try:
        _queue.put_nowait((func, args, kwargs))
        return True
    except queue.Full:
        global _dropped
        _dropped += 1
        if _dropped == 1 or _dropped % 100 == 0:
            logger.warning(
                f"embedding queue: full, dropped total {_dropped} tasks "
                "(记忆仍已写入主表, 仅向量检索暂缺该条)"
            )
        return False


def pending_count() -> int:
    """队列中待处理任务数 (测试/诊断用)。"""
    return _queue.qsize()


def reset_for_tests() -> None:
    """测试专用: 清空队列 (不停已有 worker —— daemon 线程无害)。"""
    global _worker
    with _lock:
        while not _queue.empty():
            try:
                _queue.get_nowait()
            except queue.Empty:
                break
        _worker = None
