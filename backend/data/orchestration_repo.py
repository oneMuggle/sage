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
import time
import uuid
from dataclasses import asdict, is_dataclass
from typing import Any

from backend.data.database import get_database
from backend.orchestration.models import (
    Lane,
    LaneHeartbeat,
    LaneStatus,
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
    if isinstance(obj, (list, tuple)):
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
        """Insert a new task."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO orchestration_tasks
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

        cursor.execute("SELECT * FROM orchestration_tasks WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        return self._row_to_task(row) if row else None

    def update(self, task: Task) -> bool:
        """Update an existing task."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE orchestration_tasks
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

        cursor.execute("DELETE FROM orchestration_tasks WHERE task_id = ?", (task_id,))
        conn.commit()
        return cursor.rowcount > 0

    def list(
        self,
        status: TaskStatus | None = None,
        team_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Task]:
        """List tasks with optional filters."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        query = "SELECT * FROM orchestration_tasks WHERE 1=1"
        params: list[Any] = []

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

    def get_ready_tasks(self, team_id: str | None = None) -> list[Task]:
        """
        Get tasks that are ready to execute.

        A task is ready when:
        - Status is CREATED
        - All blocked_by tasks are COMPLETED
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        query = """
            SELECT t.* FROM orchestration_tasks t
            WHERE t.status = 'created'
        """
        params: list[Any] = []

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


class LaneRepository:
    """SQLite-backed lane storage."""

    def __init__(self) -> None:
        self.db = get_database()

    def create(self, lane: Lane) -> Lane:
        """Insert a new lane."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO orchestration_lanes
            (lane_id, task_id, agent_id, status, created_at, worktree)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(lane.lane_id),
                str(lane.task_id) if lane.task_id is not None else None,
                str(lane.agent_id) if lane.agent_id is not None else None,
                lane.status.value,
                lane.created_at,
                lane.worktree,
            ),
        )
        conn.commit()
        return lane

    def get(self, lane_id: str) -> Lane | None:
        """Fetch a lane by ID."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM orchestration_lanes WHERE lane_id = ?", (lane_id,))
        row = cursor.fetchone()
        return self._row_to_lane(row) if row else None

    def update(self, lane: Lane) -> bool:
        """Update an existing lane."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE orchestration_lanes
            SET status = ?, agent_id = ?, started_at = ?, completed_at = ?,
                heartbeat = ?, error = ?
            WHERE lane_id = ?
            """,
            (
                lane.status.value,
                lane.agent_id,
                lane.started_at,
                lane.completed_at,
                json.dumps(lane.heartbeat.__dict__) if lane.heartbeat else None,
                lane.error,
                lane.lane_id,
            ),
        )
        conn.commit()
        return cursor.rowcount > 0

    def delete(self, lane_id: str) -> bool:
        """Delete a lane."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM orchestration_lanes WHERE lane_id = ?", (lane_id,))
        conn.commit()
        return cursor.rowcount > 0

    def list_by_task(self, task_id: str) -> list[Lane]:
        """List all lanes for a task."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM orchestration_lanes
            WHERE task_id = ?
            ORDER BY created_at ASC
            """,
            (task_id,),
        )
        return [self._row_to_lane(row) for row in cursor.fetchall()]

    def list_by_status(self, status: LaneStatus, limit: int = 100) -> list[Lane]:
        """List lanes by status."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM orchestration_lanes
            WHERE status = ?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (status.value, limit),
        )
        return [self._row_to_lane(row) for row in cursor.fetchall()]

    def list_by_agent(self, agent_id: str) -> list[Lane]:
        """List all lanes assigned to an agent."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM orchestration_lanes
            WHERE agent_id = ?
            ORDER BY created_at ASC
            """,
            (agent_id,),
        )
        return [self._row_to_lane(row) for row in cursor.fetchall()]

    def list_all(self) -> list[Lane]:
        """List all lanes."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM orchestration_lanes
            ORDER BY created_at ASC
            """
        )
        return [self._row_to_lane(row) for row in cursor.fetchall()]

    def update_heartbeat(self, lane_id: str, heartbeat: LaneHeartbeat) -> bool:
        """Update lane heartbeat."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE orchestration_lanes
            SET heartbeat = ?
            WHERE lane_id = ?
            """,
            (json.dumps(heartbeat.__dict__), lane_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    def _row_to_lane(self, row) -> Lane:
        """Convert a database row to a Lane object."""
        heartbeat_data = json.loads(row["heartbeat"]) if row["heartbeat"] else None
        heartbeat = LaneHeartbeat(**heartbeat_data) if heartbeat_data else None

        return Lane(
            lane_id=row["lane_id"],
            task_id=row["task_id"],
            agent_id=row["agent_id"],
            status=LaneStatus(row["status"]),
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            worktree=row["worktree"],
            heartbeat=heartbeat,
            error=row["error"],
        )


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
            INSERT INTO orchestration_teams
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

        cursor.execute("SELECT * FROM orchestration_teams WHERE team_id = ?", (team_id,))
        row = cursor.fetchone()
        return self._row_to_team(row) if row else None

    def update(self, team: Team) -> bool:
        """Update an existing team."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE orchestration_teams
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

        cursor.execute("DELETE FROM orchestration_teams WHERE team_id = ?", (team_id,))
        conn.commit()
        return cursor.rowcount > 0

    def list(self, status: TeamStatus | None = None, limit: int = 100) -> list[Team]:
        """List teams with optional status filter."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        query = "SELECT * FROM orchestration_teams"
        params: list[Any] = []

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


class LaneEventRepository:
    """SQLite-backed lane event storage."""

    def __init__(self) -> None:
        self.db = get_database()

    def append(
        self,
        event_type: str,
        lane_id: str,
        task_id: str,
        agent_id: str | None = None,
        provenance: str = "LiveLane",
        metadata: dict | None = None,
    ) -> str:
        """Record a lane event. Returns the event_id."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        event_id = f"evt-{uuid.uuid4().hex[:12]}"
        timestamp = int(time.time() * 1000)

        cursor.execute(
            """
            INSERT INTO orchestration_lane_events
            (event_id, event_type, lane_id, task_id, agent_id, timestamp, provenance, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                event_type,
                lane_id,
                task_id,
                agent_id,
                timestamp,
                provenance,
                json.dumps(metadata or {}),
            ),
        )
        conn.commit()
        return event_id

    def list_by_lane(self, lane_id: str, limit: int = 100, offset: int = 0) -> list[dict]:
        """List events for a lane, ordered by timestamp."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM orchestration_lane_events
            WHERE lane_id = ?
            ORDER BY timestamp ASC
            LIMIT ? OFFSET ?
            """,
            (lane_id, limit, offset),
        )
        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def list_by_task(self, task_id: str, limit: int = 100) -> list[dict]:
        """List events for a task (across all lanes)."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM orchestration_lane_events
            WHERE task_id = ?
            ORDER BY timestamp ASC
            LIMIT ?
            """,
            (task_id, limit),
        )
        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def _row_to_dict(self, row) -> dict:
        """Convert a database row to a dict."""
        return {
            "event_id": row["event_id"],
            "event_type": row["event_type"],
            "lane_id": row["lane_id"],
            "task_id": row["task_id"],
            "agent_id": row["agent_id"],
            "timestamp": row["timestamp"],
            "provenance": row["provenance"],
            "metadata": json.loads(row["metadata"]),
        }
