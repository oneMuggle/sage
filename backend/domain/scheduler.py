"""Ports and business exceptions for scheduled-task tools."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol


class ScheduledTaskNotFoundError(KeyError):
    """Raised when a scheduled task ID does not exist."""


class ScheduledTaskValidationError(ValueError):
    """Raised when scheduled-task input or ownership validation fails."""


class SchedulerServicePort(Protocol):
    """Minimal scheduler contract consumed by the LLM tools."""

    def add_task(
        self,
        name: str,
        task_type: str,
        schedule: Dict[str, Any],
        session_id: str,
        content: str,
        enabled: bool = True,
    ) -> Any:
        ...

    def list_tasks(self) -> List[Any]:
        ...

    def delete_task(
        self,
        task_id: str,
        expected_session_id: Optional[str] = None,
    ) -> None:
        ...
