"""SnapshotStore — Run/Task/Step 实时快照缓存。

每次事件 publish 时同步更新内存快照，REST snapshot 端点直接读内存，
无需查库。持久化只做兜底（进程重启后从 orch_events 表恢复）。

设计约束：
- 只写快照，不查历史（历史走 orch_events_repo.list_after）
- 线程安全由 asyncio.Lock 保护（单线程事件循环）
- producer_generation 防旧 worker 覆盖新状态
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from backend.domain.orch_events import RunEvent, RunSnapshot, TaskSummary


@dataclass
class _TaskSnapshot:
    """单 task 的运行时快照。"""

    task_id: str
    agent_id: str = ""
    goal: str = ""
    status: str = "pending"
    revision: int = 0
    current_step_id: Optional[str] = None
    waiting_reason: Optional[str] = None
    last_event_seq: int = 0
    producer_generation: int = 0
    started_at: Optional[int] = None
    finished_at: Optional[int] = None
    last_event_at: int = 0
    error: Optional[str] = None
    output_preview: Optional[str] = None


@dataclass
class _RunSnapshot:
    """单 run 的运行时快照。"""

    run_id: str
    status: str = "draft"
    revision: int = 0
    last_event_seq: int = 0
    owner_session_id: Optional[str] = None
    producer_generation: int = 0
    created_at: Optional[int] = None
    started_at: Optional[int] = None
    finished_at: Optional[int] = None
    last_event_at: int = 0
    final_summary: Optional[str] = None
    tasks: Dict[str, _TaskSnapshot] = field(default_factory=dict)


class SnapshotStore:
    """内存快照缓存，由 EventHub publish 链路驱动更新。"""

    def __init__(self) -> None:
        self._runs: Dict[str, _RunSnapshot] = {}
        self._lock = asyncio.Lock()

    async def apply_event(self, event: RunEvent) -> None:
        """根据事件类型更新对应快照。"""
        async with self._lock:
            run = self._runs.get(event.run_id)
            if run is None:
                run = _RunSnapshot(
                    run_id=event.run_id,
                    created_at=event.occurred_at,
                )
                self._runs[event.run_id] = run

            # 旧 worker 事件不覆盖新状态
            if event.producer_generation < run.producer_generation:
                return

            run.last_event_seq = max(run.last_event_seq, event.seq)
            run.last_event_at = max(run.last_event_at, event.occurred_at)
            etype = event.event_type

            if etype.startswith("run."):
                self._apply_run_event(run, event)
            elif etype.startswith("task.step."):
                self._apply_step_event(run, event)
            elif etype.startswith("task."):
                task_id = event.entity.get("task_id")
                task = run.tasks.get(task_id) if task_id else None
                if task is not None and event.producer_generation < task.producer_generation:
                    return
                self._apply_task_event(run, event)

    def _apply_run_event(self, run: _RunSnapshot, event: RunEvent) -> None:
        payload = event.payload
        if event.producer_generation > run.producer_generation:
            run.producer_generation = event.producer_generation
            run.revision += 1

        if event.event_type == "run.created":
            run.status = "draft"
        elif event.event_type == "run.started":
            run.status = "running"
            run.started_at = event.occurred_at
        elif event.event_type == "run.completed":
            run.status = "completed"
            run.finished_at = event.occurred_at
            run.final_summary = payload.get("final_summary")
        elif event.event_type == "run.failed":
            run.status = "failed"
            run.finished_at = event.occurred_at
            run.final_summary = payload.get("error")
        elif event.event_type == "run.cancelled":
            run.status = "cancelled"
            run.finished_at = event.occurred_at
        elif event.event_type == "run.paused":
            run.status = "paused"

    def _apply_task_event(self, run: _RunSnapshot, event: RunEvent) -> None:
        task_id = event.entity.get("task_id")
        if not task_id:
            return
        task = run.tasks.get(task_id)
        if task is None:
            task = _TaskSnapshot(
                task_id=task_id,
                agent_id=event.entity.get("agent_id", ""),
            )
            run.tasks[task_id] = task

        task.last_event_seq = max(task.last_event_seq, event.seq)
        task.last_event_at = max(task.last_event_at, event.occurred_at)
        task.producer_generation = max(task.producer_generation, event.producer_generation)
        task.revision += 1
        payload = event.payload

        if event.event_type in ("task.created", "task.planned"):
            task.status = "planned" if event.event_type == "task.planned" else "pending"
            task.agent_id = payload.get("agent_id", task.agent_id)
            task.goal = payload.get("goal", task.goal)
        elif event.event_type == "task.queued":
            task.status = "queued"
        elif event.event_type == "task.started":
            task.status = "running"
            task.started_at = event.occurred_at
        elif event.event_type in ("task.succeeded", "task.completed"):
            task.status = "succeeded" if event.event_type == "task.succeeded" else "completed"
            task.finished_at = event.occurred_at
            task.output_preview = payload.get("output_preview")
        elif event.event_type == "task.failed":
            task.status = "failed"
            task.finished_at = event.occurred_at
            task.error = payload.get("error")
        elif event.event_type == "task.cancelled":
            task.status = "cancelled"
            task.finished_at = event.occurred_at
        elif event.event_type == "task.retrying":
            task.status = "retrying"
        elif event.event_type in ("task.progress", "task.step.progress"):
            task.current_step_id = payload.get("step_id", task.current_step_id)
            task.output_preview = payload.get("output_preview", task.output_preview)
        elif event.event_type in ("task.waiting_input", "task.waiting_approval"):
            # py3.8 无 str.removeprefix（py3.9+）
            _prefix = "task."
            task.status = (
                event.event_type[len(_prefix):]
                if event.event_type.startswith(_prefix)
                else event.event_type
            )
            task.waiting_reason = payload.get("reason")

    def _apply_step_event(self, run: _RunSnapshot, event: RunEvent) -> None:
        task_id = event.entity.get("task_id")
        if not task_id:
            return
        task = run.tasks.get(task_id)
        if task is None:
            return
        task.last_event_seq = max(task.last_event_seq, event.seq)
        step_id = event.entity.get("step_id")
        if step_id:
            task.current_step_id = step_id

    def get_run_snapshot(self, run_id: str) -> Optional[RunSnapshot]:
        """返回 run 的当前快照（不可变视图）。"""
        run = self._runs.get(run_id)
        if run is None:
            return None
        # 按 status 聚合计数
        summary: Dict[str, int] = {"total": len(run.tasks)}
        for t in run.tasks.values():
            summary[t.status] = summary.get(t.status, 0) + 1
        return RunSnapshot(
            run_id=run.run_id,
            status=run.status,
            summary=summary,
            last_event_seq=run.last_event_seq,
            updated_at=run.last_event_at or run.started_at or run.created_at or 0,
            tasks=[
                TaskSummary(
                    task_id=t.task_id,
                    agent_id=t.agent_id or None,
                    status=t.status,
                    current_step_id=t.current_step_id,
                    output_preview=t.output_preview,
                    revision=t.revision,
                    error=t.error,
                )
                for t in run.tasks.values()
            ],
        )

    def list_run_ids(self) -> List[str]:
        return list(self._runs.keys())

    def get_task_revision(self, run_id: str, task_id: str) -> Optional[int]:
        """Return the current in-memory task revision for compatibility callers."""
        state = self.get_task_steering_state(run_id, task_id)
        return state[1] if state is not None else None

    @asynccontextmanager
    async def task_steering_context(self, run_id: str, task_id: str):
        """Hold the snapshot lock while validating and persisting a steer."""
        async with self._lock:
            yield self.get_task_steering_state(run_id, task_id)

    def get_task_producer_generation(self, run_id: str, task_id: str) -> int:
        """Return the task's current ``producer_generation`` (0 if unknown)."""
        run = self._runs.get(run_id)
        if run is None:
            return 0
        task = run.tasks.get(task_id)
        if task is None:
            return 0
        return task.producer_generation

    def get_task_steering_state(
        self, run_id: str, task_id: str
    ) -> Optional[Tuple[str, int]]:
        """Return task status and revision for a lock-protected steering check."""
        run = self._runs.get(run_id)
        if run is None:
            return None
        task = run.tasks.get(task_id)
        if task is None:
            return None
        return task.status, task.revision


__all__ = ["SnapshotStore"]
