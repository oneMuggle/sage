"""
Team Registry - manages team-task relationships and status aggregation.

Provides high-level operations for team management:
- Create teams and associate tasks
- Track team status based on task completion
- Query teams by status
- Aggregate task progress
"""

from __future__ import annotations

import uuid
from typing import Any

from backend.data.orchestration_repo import TeamRepository
from backend.orchestration.models import Team, TeamStatus


class TeamRegistry:
    """
    Manages team lifecycle and task aggregation.

    Teams group related tasks into a workflow unit. Team status is derived
    from the completion status of its member tasks.
    """

    def __init__(self, repo: TeamRepository | None = None) -> None:
        self.repo = repo or TeamRepository()

    def create_team(
        self,
        name: str,
        metadata: dict[str, Any] | None = None,
    ) -> Team:
        """
        Create a new team.

        Args:
            name: Team name
            metadata: Optional metadata (trigger source, session, user intent)

        Returns:
            Created Team object
        """
        team_id = f"team-{uuid.uuid4().hex[:12]}"
        team = Team(
            team_id=team_id,
            name=name,
            metadata=metadata or {},
        )

        self.repo.create(team)
        return team

    def get_team(self, team_id: str) -> Team | None:
        """Fetch a team by ID."""
        return self.repo.get(team_id)

    def add_task(self, team_id: str, task_id: str) -> bool:
        """Add a task to a team."""
        team = self.repo.get(team_id)
        if not team:
            return False

        team.add_task(task_id)
        return self.repo.update(team)

    def remove_task(self, team_id: str, task_id: str) -> bool:
        """Remove a task from a team."""
        team = self.repo.get(team_id)
        if not team:
            return False

        team.remove_task(task_id)
        return self.repo.update(team)

    def update_team(self, team: Team) -> bool:
        """Update a team in the database."""
        return self.repo.update(team)

    def mark_running(self, team_id: str) -> bool:
        """Transition team to RUNNING state."""
        team = self.repo.get(team_id)
        if not team:
            return False

        try:
            team.mark_running()
            return self.repo.update(team)
        except ValueError:
            return False

    def mark_completed(self, team_id: str) -> bool:
        """Transition team to COMPLETED state."""
        team = self.repo.get(team_id)
        if not team:
            return False

        team.mark_completed()
        return self.repo.update(team)

    def mark_failed(self, team_id: str) -> bool:
        """Transition team to FAILED state."""
        team = self.repo.get(team_id)
        if not team:
            return False

        team.mark_failed()
        return self.repo.update(team)

    def mark_cancelled(self, team_id: str) -> bool:
        """Transition team to CANCELLED state."""
        team = self.repo.get(team_id)
        if not team:
            return False

        try:
            team.mark_cancelled()
            return self.repo.update(team)
        except ValueError:
            return False

    def list_teams(self, status: TeamStatus | None = None, limit: int = 100) -> list[Team]:
        """List teams with optional status filter."""
        return self.repo.list(status=status, limit=limit)

    def delete_team(self, team_id: str) -> bool:
        """Delete a team."""
        return self.repo.delete(team_id)

    def get_team_progress(self, team_id: str) -> dict[str, int]:
        """
        Get task progress breakdown for a team.

        Returns:
            Dict with counts: total, completed, failed, running, created, blocked
        """
        team = self.repo.get(team_id)
        if not team:
            return {"total": 0}

        # Import here to avoid circular dependency
        from backend.data.orchestration_repo import TaskRepository

        task_repo = TaskRepository()
        tasks = [task_repo.get(tid) for tid in team.task_ids]
        tasks = [t for t in tasks if t is not None]

        progress = {
            "total": len(tasks),
            "completed": 0,
            "failed": 0,
            "running": 0,
            "created": 0,
            "blocked": 0,
            "stopped": 0,
        }

        for task in tasks:
            status_key = task.status.value
            if status_key in progress:
                progress[status_key] += 1

        return progress

    def is_team_completed(self, team_id: str) -> bool:
        """Check if all tasks in a team are completed."""
        progress = self.get_team_progress(team_id)
        return progress["total"] > 0 and progress["completed"] == progress["total"]

    def has_team_failed(self, team_id: str) -> bool:
        """Check if any task in a team has failed."""
        progress = self.get_team_progress(team_id)
        return progress["failed"] > 0
