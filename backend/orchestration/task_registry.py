"""
Task Registry - manages task lifecycle and dependency resolution.

Provides high-level operations for task management:
- Create tasks with dependencies
- Resolve ready tasks (dependencies satisfied)
- Track task state transitions
- Query tasks by status/team
"""

from __future__ import annotations

import uuid
from typing import Any

from backend.data.orchestration_repo import TaskRepository
from backend.orchestration.models import Task, TaskPacket, TaskStatus


class TaskRegistry:
    """
    Manages task lifecycle and dependency resolution.

    The registry coordinates between in-memory task state and persistent storage,
    providing atomic state transitions and dependency-aware queries.
    """

    def __init__(self, repo: TaskRepository | None = None) -> None:
        self.repo = repo or TaskRepository()

    def create_task(
        self,
        name: str | Task,
        description: str | None = None,
        blocked_by: list[str] | None = None,
        priority: int = 0,
        executor_type: str = "agent",
        parameters: dict[str, Any] | None = None,
        packet: TaskPacket | None = None,
        team_id: str | None = None,
        task_type: str = "general",
    ) -> Task:
        """
        Create a new task with optional dependencies.

        Can be called in two ways:
        1. create_task(task: Task) - pass a pre-constructed Task object
        2. create_task(name, description, ...) - construct from parameters

        Args:
            name: Task name or Task object
            description: Task description (ignored if name is Task)
            blocked_by: List of task IDs that must complete before this task can run
            priority: Higher = more important
            executor_type: "agent" / "tool" / "script"
            parameters: Task-specific parameters
            packet: Advanced configuration (recovery/escalation policies)
            team_id: Optional team association
            task_type: Task type (general/research/coding/analysis/testing)

        Returns:
            Created Task object
        """
        # Handle both signatures
        if isinstance(name, Task):
            task = name
        else:
            task_id = f"task-{uuid.uuid4().hex[:12]}"
            task = Task(
                task_id=task_id,
                name=name,
                description=description or "",
                task_type=task_type,
                priority=priority,
                executor_type=executor_type,
                parameters=parameters or {},
                packet=packet,
                blocked_by=blocked_by or [],
                team_id=team_id,
            )

        # Persist to database
        self.repo.create(task)

        # Update blocking relationships: add this task to the 'blocks' list of dependencies
        if task.blocked_by:
            self._update_blocking_relationships(task)

        return task

    def get_task(self, task_id: str) -> Task | None:
        """Fetch a task by ID."""
        return self.repo.get(task_id)

    def mark_running(self, task_id: str) -> bool:
        """Transition task to RUNNING state."""
        task = self.repo.get(task_id)
        if not task:
            return False

        try:
            task.mark_running()
            return self.repo.update(task)
        except ValueError:
            return False

    def mark_completed(self, task_id: str, result: Any = None) -> bool:
        """Transition task to COMPLETED state."""
        task = self.repo.get(task_id)
        if not task:
            return False

        try:
            task.mark_completed(result)
            return self.repo.update(task)
        except ValueError:
            return False

    def mark_failed(self, task_id: str, error: str | None = None) -> bool:
        """Transition task to FAILED state."""
        task = self.repo.get(task_id)
        if not task:
            return False

        try:
            task.mark_failed(error)
            return self.repo.update(task)
        except ValueError:
            return False

    def mark_blocked(self, task_id: str) -> bool:
        """Transition task to BLOCKED state."""
        task = self.repo.get(task_id)
        if not task:
            return False

        try:
            task.mark_blocked()
            return self.repo.update(task)
        except ValueError:
            return False

    def mark_stopped(self, task_id: str) -> bool:
        """Transition task to STOPPED state (cancelled)."""
        task = self.repo.get(task_id)
        if not task:
            return False

        try:
            task.mark_stopped()
            return self.repo.update(task)
        except ValueError:
            return False

    def get_ready_tasks(self, team_id: str | None = None) -> list[Task]:
        """
        Get tasks that are ready to execute.

        A task is ready when:
        - Status is CREATED
        - All blocked_by tasks are COMPLETED

        Args:
            team_id: Optional filter by team

        Returns:
            List of ready tasks, ordered by priority
        """
        return self.repo.get_ready_tasks(team_id)

    def list_tasks(
        self,
        status: TaskStatus | None = None,
        team_id: str | None = None,
        limit: int = 100,
    ) -> list[Task]:
        """List tasks with optional filters."""
        return self.repo.list(status=status, team_id=team_id, limit=limit)

    def delete_task(self, task_id: str) -> bool:
        """Delete a task."""
        return self.repo.delete(task_id)

    def _update_blocking_relationships(self, task: Task) -> None:
        """
        Update the 'blocks' field of dependency tasks.

        When task B is blocked_by task A, we add B to A's 'blocks' list.
        This creates a bidirectional relationship for efficient queries.
        """
        for dep_id in task.blocked_by:
            dep_task = self.repo.get(dep_id)
            if dep_task and task.task_id not in dep_task.blocks:
                dep_task.blocks.append(task.task_id)
                self.repo.update(dep_task)
