"""
Orchestration persistence layer.

Provides SQLite-backed repositories for the multi-agent coordination system:
- TaskRepository: Task CRUD and dependency queries
- LaneRepository: Lane lifecycle and heartbeat management
- TeamRepository: Team-task relationships
- LaneEventRepository: Lane event recording and querying

All repositories follow the same pattern as backend/data/session_repo.py.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any, List, Optional

from backend.data.database import get_database
from backend.data.orch_lane_repo import (
    OrchLaneEventRepository,
    OrchLaneRepository,
)
from backend.orchestration.models import (
    RecoveryPolicy,
    Task,
    TaskStatus,
    Team,
    TeamStatus,
)


def _to_jsonable(obj: Any) -> Any:
    """Recursively convert dataclass instances to plain dicts for JSON encoding."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_to_jsonable(v) for v in obj]
    return obj


# ============================================================================
# Task Repository
# ============================================================================


class TaskRepository:
    """SQLite-backed task storage."""

    def __init__(self) -> None:
        self.db = get_database()

    def create(self, task: Task) -> Task:
        """Insert or replace a task (idempotent upsert).

        Uses ``INSERT OR REPLACE`` so callers that generate deterministic IDs
        (e.g. the review step ``task-review-{run_id}``) are safe to invoke
        multiple times without hitting a UNIQUE constraint error.
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT OR REPLACE INTO orch_plan_tasks
            (task_id, name, description, status, priority, executor_type,
             parameters, packet, blocks, blocked_by, created_at, team_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task.task_id,
                task.name,
                task.description,
                task.status.value,
                task.priority,
                task.executor_type,
                json.dumps(task.parameters),
                json.dumps(_to_jsonable(task.packet)) if task.packet else None,
                json.dumps(task.blocks),
                json.dumps(task.blocked_by),
                task.created_at,
                task.team_id,
            ),
        )
        conn.commit()
        return task

    def get(self, task_id: str) -> Task | None:
        """Fetch a task by ID."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM orch_plan_tasks WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        return self._row_to_task(row) if row else None

    def update(self, task: Task) -> bool:
        """Update an existing task."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE orch_plan_tasks
            SET status = ?, priority = ?, parameters = ?, result = ?,
                started_at = ?, completed_at = ?, blocks = ?, blocked_by = ?,
                packet = ?
            WHERE task_id = ?
            """,
            (
                task.status.value,
                task.priority,
                json.dumps(task.parameters),
                json.dumps(task.result) if task.result is not None else None,
                task.started_at,
                task.completed_at,
                json.dumps(task.blocks),
                json.dumps(task.blocked_by),
                json.dumps(_to_jsonable(task.packet)) if task.packet else None,
                task.task_id,
            ),
        )
        conn.commit()
        return cursor.rowcount > 0

    def delete(self, task_id: str) -> bool:
        """Delete a task."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM orch_plan_tasks WHERE task_id = ?", (task_id,))
        conn.commit()
        return cursor.rowcount > 0

    def list(
        self,
        status: Optional[TaskStatus] = None,
        team_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Task]:
        """List tasks with optional filters."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        query = "SELECT * FROM orch_plan_tasks WHERE 1=1"
        params: List[Any] = []

        if status is not None:
            query += " AND status = ?"
            params.append(status.value)
        if team_id is not None:
            query += " AND team_id = ?"
            params.append(team_id)

        query += " ORDER BY priority DESC, created_at ASC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(query, params)
        return [self._row_to_task(row) for row in cursor.fetchall()]

    def get_ready_tasks(self, team_id: Optional[str] = None) -> List[Task]:
        """
        Get tasks that are ready to execute.

        A task is ready when:
        - Status is CREATED
        - All blocked_by tasks are COMPLETED
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        query = """
            SELECT t.* FROM orch_plan_tasks t
            WHERE t.status = 'created'
        """
        params: List[Any] = []

        if team_id is not None:
            query += " AND t.team_id = ?"
            params.append(team_id)

        cursor.execute(query, params)
        all_tasks = {row["task_id"]: row for row in cursor.fetchall()}

        ready = []
        for row in all_tasks.values():
            blocked_by = json.loads(row["blocked_by"])
            # Check if all dependencies are completed
            all_deps_completed = all(
                dep_id in all_tasks and all_tasks[dep_id]["status"] == TaskStatus.COMPLETED.value
                for dep_id in blocked_by
            )
            if all_deps_completed:
                ready.append(self._row_to_task(row))

        return ready

    def _row_to_task(self, row) -> Task:
        """Convert a database row to a Task object."""
        from backend.orchestration.models import EscalationPolicy, TaskPacket

        packet_data = json.loads(row["packet"]) if row["packet"] else None
        packet = None
        if packet_data:
            packet = TaskPacket(
                objective=packet_data.get("objective", ""),
                scope=packet_data.get("scope", []),
                acceptance_tests=packet_data.get("acceptance_tests", []),
                model=packet_data.get("model"),
                permission_profile=packet_data.get("permission_profile", "workspace-write"),
                timeout_secs=packet_data.get("timeout_secs", 600),
                recovery_policy=RecoveryPolicy(**packet_data.get("recovery_policy", {})),
                escalation_policy=EscalationPolicy(**packet_data.get("escalation_policy", {})),
            )

        return Task(
            task_id=row["task_id"],
            name=row["name"],
            description=row["description"],
            status=TaskStatus(row["status"]),
            priority=row["priority"],
            executor_type=row["executor_type"],
            parameters=json.loads(row["parameters"]),
            packet=packet,
            blocks=json.loads(row["blocks"]),
            blocked_by=json.loads(row["blocked_by"]),
            result=json.loads(row["result"]) if row["result"] else None,
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            team_id=row["team_id"],
        )


# ============================================================================
# Lane Repository
# ============================================================================


# ============================================================================
# Team Repository
# ============================================================================


class TeamRepository:
    """SQLite-backed team storage."""

    def __init__(self) -> None:
        self.db = get_database()

    def create(self, team: Team) -> Team:
        """Insert a new team."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO orch_plan_teams
            (team_id, name, task_ids, status, created_at, updated_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                team.team_id,
                team.name,
                json.dumps(team.task_ids),
                team.status.value,
                team.created_at,
                team.updated_at,
                json.dumps(team.metadata),
            ),
        )
        conn.commit()
        return team

    def get(self, team_id: str) -> Team | None:
        """Fetch a team by ID."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM orch_plan_teams WHERE team_id = ?", (team_id,))
        row = cursor.fetchone()
        return self._row_to_team(row) if row else None

    def update(self, team: Team) -> bool:
        """Update an existing team."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE orch_plan_teams
            SET task_ids = ?, status = ?, updated_at = ?, metadata = ?
            WHERE team_id = ?
            """,
            (
                json.dumps(team.task_ids),
                team.status.value,
                team.updated_at,
                json.dumps(team.metadata),
                team.team_id,
            ),
        )
        conn.commit()
        return cursor.rowcount > 0

    def delete(self, team_id: str) -> bool:
        """Delete a team."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM orch_plan_teams WHERE team_id = ?", (team_id,))
        conn.commit()
        return cursor.rowcount > 0

    def list(self, status: Optional[TeamStatus] = None, limit: int = 100) -> List[Team]:
        """List teams with optional status filter."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        query = "SELECT * FROM orch_plan_teams"
        params: List[Any] = []

        if status is not None:
            query += " WHERE status = ?"
            params.append(status.value)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        return [self._row_to_team(row) for row in cursor.fetchall()]

    def _row_to_team(self, row) -> Team:
        """Convert a database row to a Team object."""
        return Team(
            team_id=row["team_id"],
            name=row["name"],
            task_ids=json.loads(row["task_ids"]),
            status=TeamStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=json.loads(row["metadata"]),
        )


# ============================================================================
# Lane Event Repository
# ============================================================================


# ============================================================================
# 向后兼容别名（双轨合并 Phase 5，2026-09-19）
# ============================================================================
# LaneRepository / LaneEventRepository 的实现在 Phase 1 已迁到
# ``orch_lane_repo.py``（表 orchestration_lanes → orch_lanes）。此处保留旧类名
# 作为别名，让既有调用方（主要是测试）零改动切换到新表；新代码请直接用
# ``OrchLaneRepository`` / ``OrchLaneEventRepository``。
LaneRepository = OrchLaneRepository
LaneEventRepository = OrchLaneEventRepository

__all__ = [
    "LaneEventRepository",
    "LaneRepository",
    "TaskRepository",
    "TeamRepository",
]
