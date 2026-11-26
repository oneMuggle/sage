"""进化任务运行状态注册表（进程内）。

手动触发（``POST /scheduled/evolution/{name}/run``）、cron 触发与启动补跑
都经 :class:`backend.services.scheduler.SchedulerService` 的同一执行包装，
把运行状态登记到这里；前端轮询 ``GET /scheduled/evolution/tasks`` 读取快照。

设计要点：

* **状态源单一**：``evolution_log`` 只在任务结束时写入，看不到中间态；
  本注册表补上 running + 阶段进度，是 UI 的唯一运行状态来源。
* **内存态**：进程重启时任务本身也随线程终止，不存在悬空 running；
  前端拿不到快照时回退到进化日志。
* **互斥**：``begin`` 对同一任务名在 running 期间返回 ``None``，
  手动触发因此幂等 attach，不会并发跑出两个实例。
* **线程安全**：APScheduler worker 线程、手动触发后台线程、FastAPI
  读线程并发访问，全部经 ``threading.Lock``。
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Dict, Optional

STATE_RUNNING = "running"
STATE_SUCCEEDED = "succeeded"
STATE_FAILED = "failed"
STATE_CANCELLED = "cancelled"

#: 进度回调签名：``(phase, phase_label, extra)``。
#: ``extra`` 为增量指标字典（如 llm_done / llm_total），由注册表合并进 progress。


def _now_ms() -> int:
    return int(time.time() * 1000)


def serialize_evolution_result(result: Any) -> Optional[Dict[str, Any]]:
    """把任务返回值归一化成可 JSON 序列化的字典。

    ``ConsolidationResult`` 是 int 子类，直接交给 FastAPI 会被序列化成裸
    数字，前端拿不到 promoted/decayed；int 型任务（修剪/摘要）补一个
    ``total``；dict 原样返回；其余标量包一层 ``value``。
    """
    if result is None:
        return None
    if hasattr(result, "as_dict"):
        data = result.as_dict()  # type: ignore[union-attr]
        return data if isinstance(data, dict) else {"value": data}
    if isinstance(result, bool):
        return {"value": result}
    if isinstance(result, int):
        return {"total": int(result)}
    if isinstance(result, dict):
        return result
    return {"value": result}


class EvolutionRunRegistry:
    """按任务名保存最近一次运行的快照（running / 终态）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: Dict[str, Dict[str, Any]] = {}

    def begin(self, name: str, trigger: str = "manual") -> Optional[str]:
        """登记一次运行；同任务已在 running 时返回 ``None``（互斥）。"""
        with self._lock:
            current = self._runs.get(name)
            if current is not None and current.get("state") == STATE_RUNNING:
                return None
            run_id = uuid.uuid4().hex
            self._runs[name] = {
                "run_id": run_id,
                "name": name,
                "state": STATE_RUNNING,
                "trigger": trigger,
                "phase": "start",
                "phase_label": "准备中",
                "progress": {},
                "started_at": _now_ms(),
                "finished_at": None,
                "duration_ms": None,
                "result": None,
                "error": None,
                "cancel_requested": False,
            }
            return run_id

    def update(
        self,
        name: str,
        run_id: str,
        phase: str,
        phase_label: str,
        progress: Optional[Dict[str, Any]] = None,
    ) -> None:
        """更新阶段进度；只认当前 run_id 且仍在 running 的上报。

        旧一轮任务的迟到上报（run_id 不匹配）会被丢弃，不会污染新一轮。
        """
        with self._lock:
            current = self._runs.get(name)
            if (
                current is None
                or current.get("run_id") != run_id
                or current.get("state") != STATE_RUNNING
            ):
                return
            current["phase"] = phase
            current["phase_label"] = phase_label
            if progress:
                merged = dict(current.get("progress") or {})
                merged.update(progress)
                current["progress"] = merged

    def request_cancel(self, name: str) -> bool:
        """请求取消当前运行；无 running 时返回 False（幂等）。

        只是置协作标志 —— 任务在自己的检查点（阶段边界 / LLM 组间）响应，
        单次进行中的 LLM 调用不会被强行中断。
        """
        with self._lock:
            current = self._runs.get(name)
            if current is None or current.get("state") != STATE_RUNNING:
                return False
            current["cancel_requested"] = True
            return True

    def is_cancel_requested(self, name: str, run_id: str) -> bool:
        """执行线程检查点：当前 run 是否已被请求取消。"""
        with self._lock:
            current = self._runs.get(name)
            return bool(
                current
                and current.get("run_id") == run_id
                and current.get("state") == STATE_RUNNING
                and current.get("cancel_requested")
            )

    def finish(
        self,
        name: str,
        run_id: str,
        result: Any = None,
        error: Optional[str] = None,
        cancelled: bool = False,
    ) -> None:
        """写终态；``cancelled`` 优先于 error；无异常视为 succeeded。"""
        with self._lock:
            current = self._runs.get(name)
            if current is None or current.get("run_id") != run_id:
                return
            now = _now_ms()
            started = int(current.get("started_at") or now)
            if cancelled:
                current["state"] = STATE_CANCELLED
                current["phase_label"] = "已取消"
            else:
                current["state"] = STATE_FAILED if error else STATE_SUCCEEDED
                current["phase_label"] = "失败" if error else "完成"
            current["finished_at"] = now
            current["duration_ms"] = max(0, now - started)
            current["result"] = serialize_evolution_result(result)
            current["error"] = None if cancelled else error
            current["phase"] = "done"

    def is_running(self, name: str) -> bool:
        with self._lock:
            current = self._runs.get(name)
            return current is not None and current.get("state") == STATE_RUNNING

    def snapshot(self, name: str) -> Optional[Dict[str, Any]]:
        """返回可安全交给 JSON 序列化的快照副本。"""
        with self._lock:
            current = self._runs.get(name)
            if current is None:
                return None
            snap = dict(current)
            snap["progress"] = dict(current.get("progress") or {})
            result = current.get("result")
            snap["result"] = dict(result) if isinstance(result, dict) else result
            return snap

    def snapshots(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            names = list(self._runs.keys())
        out: Dict[str, Dict[str, Any]] = {}
        for name in names:
            snap = self.snapshot(name)
            if snap is not None:
                out[name] = snap
        return out

    def reset(self) -> None:
        """测试用：清空全部状态。"""
        with self._lock:
            self._runs.clear()


_registry: Optional[EvolutionRunRegistry] = None
_registry_lock = threading.Lock()


def get_evolution_run_registry() -> EvolutionRunRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = EvolutionRunRegistry()
    return _registry
