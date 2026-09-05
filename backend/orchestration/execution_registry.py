"""In-process handles for cooperative orchestration cancellation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class ExecutionHandle:
    """Runtime controls for one lane execution."""

    task: asyncio.Task
    interrupt_event: asyncio.Event


class ExecutionRegistry:
    """Track live lane tasks without persisting asyncio objects in SQLite."""

    def __init__(self) -> None:
        self._handles: Dict[str, ExecutionHandle] = {}

    def register(
        self,
        lane_id: str,
        task: asyncio.Task,
        interrupt_event: asyncio.Event,
    ) -> None:
        self._handles[lane_id] = ExecutionHandle(task, interrupt_event)

    def cancel(self, lane_id: str) -> bool:
        """Request cooperative cancellation; never hard-cancel the worker."""
        handle = self._handles.get(lane_id)
        if handle is None:
            return False
        handle.interrupt_event.set()
        return True

    def unregister(self, lane_id: str, task: Optional[asyncio.Task] = None) -> None:
        """Remove a handle, preserving a newer registration if one exists."""
        handle = self._handles.get(lane_id)
        if handle is not None and (task is None or handle.task is task):
            self._handles.pop(lane_id, None)

    def get(self, lane_id: str) -> Optional[ExecutionHandle]:
        return self._handles.get(lane_id)


execution_registry = ExecutionRegistry()
