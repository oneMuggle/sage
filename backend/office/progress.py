"""office 长任务进度注册表 — P7 (2026-09-14, UI 优化循环)。

进程内 dict + 互斥锁。FastAPI sync handler 跑在 threadpool：生成/导出
POST 仍在执行时，并发的 GET /api/v1/office/progress/{task_id} 可以读到
同一注册表——前端用 uuid task_id 随请求携带并轮询，把阶段/百分比喂给
全局任务中心。

生命周期:
    with track(req.task_id, "生成 PPT") as prog:
        prog.report("生成文档", 30)
        ...
    # 退出即 finish（异常路径同样移除，前端轮询 404/active=False 即完成）

task_id 为 None（旧客户端 / 无追踪意图）时 track 直接 yield None 探针，
report() 全部 no-op —— 绝不因进度上报引入新的失败面。
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Dict, Generator, Optional

_lock = threading.Lock()
_progress: Dict[str, Dict] = {}


class _Reporter:
    """report() 的空安全句柄；task_id 为 None 时全部 no-op。"""

    def __init__(self, task_id: Optional[str]) -> None:
        self.task_id = task_id

    def report(self, stage: str, percent: int) -> None:
        if not self.task_id:
            return
        with _lock:
            entry = _progress.get(self.task_id)
            if entry is None:
                return
            entry["stage"] = stage
            # 百分比单调不回退，钳到 [0, 100]
            entry["percent"] = max(entry["percent"], 0, min(100, int(percent)))


@contextmanager
def track(task_id: Optional[str], title: str) -> Generator[_Reporter, None, None]:
    reporter = _Reporter(task_id)
    if task_id:
        with _lock:
            _progress[task_id] = {"title": title, "stage": "开始", "percent": 0}
    try:
        yield reporter
    finally:
        if task_id:
            with _lock:
                _progress.pop(task_id, None)


def snapshot(task_id: str) -> Optional[Dict]:
    """只读快照；任务不存在（未开始/已结束）返回 None。"""
    with _lock:
        entry = _progress.get(task_id)
        return dict(entry) if entry else None
