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
from contextvars import ContextVar
from typing import Dict, Generator

_lock = threading.Lock()
_progress: Dict[str, Dict] = {}

# P12: ContextVar 关联的当前任务 —— 路由层 track() 设置，service 层
# report_current() 上报。sync handler 跑在 threadpool，同线程调用栈内
# 自动传播；未设置（chat 工具等直接调用）时全部 no-op。
_current_task_id: ContextVar[str | None] = ContextVar(
    "office_progress_task_id", default=None
)


def report_current(stage: str, percent: int) -> None:
    """service 层进度上报：写入 ContextVar 关联的当前任务（未设置时 no-op）。"""
    task_id = _current_task_id.get()
    if not task_id:
        return
    report(task_id, stage, percent)


def report(task_id: str, stage: str, percent: int) -> None:
    """按显式 task_id 上报进度（路由层/测试用）。"""
    with _lock:
        entry = _progress.get(task_id)
        if entry is None:
            return
        entry["stage"] = stage
        # 百分比单调不回退，钳到 [0, 100]
        entry["percent"] = max(entry["percent"], 0, min(100, int(percent)))


class _Reporter:
    """report() 的空安全句柄；task_id 为 None 时全部 no-op。"""

    def __init__(self, task_id: str | None) -> None:
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
def track(task_id: str | None, title: str) -> Generator[_Reporter, None, None]:
    reporter = _Reporter(task_id)
    token = None
    if task_id:
        with _lock:
            _progress[task_id] = {"title": title, "stage": "开始", "percent": 0}
        # P12: 绑定 ContextVar，service 层 report_current() 经此上报
        token = _current_task_id.set(task_id)
    try:
        yield reporter
    finally:
        if token is not None:
            _current_task_id.reset(token)
        if task_id:
            with _lock:
                _progress.pop(task_id, None)


def snapshot(task_id: str) -> Dict | None:
    """只读快照；任务不存在（未开始/已结束）返回 None。"""
    with _lock:
        entry = _progress.get(task_id)
        return dict(entry) if entry else None
