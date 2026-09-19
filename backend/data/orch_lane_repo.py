"""``OrchLaneRepository`` / ``OrchLaneEventRepository`` — lane 持久化（new namespace）。

双轨合并 Phase 1 (P0, 2026-09-19)：本模块是 ``orchestration_repo.py`` 中
``LaneRepository`` / ``LaneEventRepository`` 的新命名空间替代品，字段与语义
完全一致，仅表名从 ``orchestration_lanes`` / ``orchestration_lane_events``
改为 ``orch_lanes`` / ``orch_lane_events``。

方法签名与老版逐一对齐，调用方（``LaneRegistry`` / ``EventRecorder``）只需
替换 import 即可切换，无需改调用点。老表数据由 ``database.py`` 的 init_db
迁移块（INSERT OR IGNORE）复制到新表；此后本 repo 单写新表，老表转为历史
存档，Phase 5 统一清理。

与 ``orch_task_repo.py`` 同模式（``self.db = get_database()``）。
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, is_dataclass
from typing import Any, List, Optional

from backend.data.database import get_database
from backend.orchestration.models import Lane, LaneHeartbeat, LaneStatus


def _to_jsonable(obj: Any) -> Any:
    """Recursively convert dataclass instances to plain dicts for JSON encoding.

    与 ``orchestration_repo._to_jsonable`` 同实现 —— 此处独立一份避免两个
    命名空间互相 import（Phase 5 清理老 repo 后本函数即为唯一实现）。
    """
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):  # noqa: UP038 — py3.8 运行期兼容（win7 cherry-pick）
        return [_to_jsonable(v) for v in obj]
    return obj


class OrchLaneRepository:
    """SQLite-backed orch_lanes storage（与老 LaneRepository 同接口）。"""

    def __init__(self) -> None:
        self.db = get_database()

    def create(self, lane: Lane) -> Lane:
        """Insert or replace a lane (idempotent upsert).

        与老版同语义：``INSERT OR REPLACE`` 让确定性 ID（如
        ``lane-review-{run_id}``）可安全重复调用。注意 REPLACE 会重置未提及
        的列为默认/NULL（老版既有行为，保持一致）。
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT OR REPLACE INTO orch_lanes
            (lane_id, task_id, agent_id, status, created_at, worktree,
             permission_preset, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(lane.lane_id),
                str(lane.task_id) if lane.task_id is not None else None,
                str(lane.agent_id) if lane.agent_id is not None else None,
                lane.status.value,
                lane.created_at,
                lane.worktree,
                lane.permission_preset,
                json.dumps(_to_jsonable(lane.metadata or {})),
            ),
        )
        conn.commit()
        return lane

    def get(self, lane_id: str) -> Optional[Lane]:
        """Fetch a lane by ID."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM orch_lanes WHERE lane_id = ?", (lane_id,))
        row = cursor.fetchone()
        return self._row_to_lane(row) if row else None

    def update(self, lane: Lane) -> bool:
        """Update an existing lane."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE orch_lanes
            SET status = ?, agent_id = ?, started_at = ?, completed_at = ?,
                heartbeat = ?, error = ?, permission_preset = ?, metadata = ?
            WHERE lane_id = ?
            """,
            (
                lane.status.value,
                lane.agent_id,
                lane.started_at,
                lane.completed_at,
                json.dumps(lane.heartbeat.__dict__) if lane.heartbeat else None,
                lane.error,
                lane.permission_preset,
                json.dumps(_to_jsonable(lane.metadata or {})),
                lane.lane_id,
            ),
        )
        conn.commit()
        return cursor.rowcount > 0

    def delete(self, lane_id: str) -> bool:
        """Delete a lane."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM orch_lanes WHERE lane_id = ?", (lane_id,))
        conn.commit()
        return cursor.rowcount > 0

    def list_by_task(self, task_id: str) -> List[Lane]:
        """List all lanes for a task."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM orch_lanes
            WHERE task_id = ?
            ORDER BY created_at ASC
            """,
            (task_id,),
        )
        return [self._row_to_lane(row) for row in cursor.fetchall()]

    def list_by_status(self, status: LaneStatus, limit: int = 100) -> List[Lane]:
        """List lanes by status."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM orch_lanes
            WHERE status = ?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (status.value, limit),
        )
        return [self._row_to_lane(row) for row in cursor.fetchall()]

    def list_by_agent(self, agent_id: str) -> List[Lane]:
        """List all lanes assigned to an agent."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM orch_lanes
            WHERE agent_id = ?
            ORDER BY created_at ASC
            """,
            (agent_id,),
        )
        return [self._row_to_lane(row) for row in cursor.fetchall()]

    def list_all(self) -> List[Lane]:
        """List all lanes."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM orch_lanes ORDER BY created_at ASC")
        return [self._row_to_lane(row) for row in cursor.fetchall()]

    def update_heartbeat(self, lane_id: str, heartbeat: LaneHeartbeat) -> bool:
        """Update lane heartbeat."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "UPDATE orch_lanes SET heartbeat = ? WHERE lane_id = ?",
            (json.dumps(heartbeat.__dict__), lane_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    def _row_to_lane(self, row: Any) -> Lane:
        """Convert a database row to a Lane object."""
        heartbeat_data = json.loads(row["heartbeat"]) if row["heartbeat"] else None
        heartbeat = LaneHeartbeat(**heartbeat_data) if heartbeat_data else None

        metadata: dict = {}
        try:
            metadata = json.loads(row["metadata"]) if row["metadata"] else {}
        except (json.JSONDecodeError, TypeError):
            metadata = {}

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
            permission_preset=row["permission_preset"] or "implement",
            metadata=metadata if isinstance(metadata, dict) else {},
        )


class OrchLaneEventRepository:
    """SQLite-backed orch_lane_events storage（与老 LaneEventRepository 同接口）。"""

    def __init__(self) -> None:
        self.db = get_database()

    def append(
        self,
        event_type: str,
        lane_id: str,
        task_id: str,
        agent_id: Optional[str] = None,
        provenance: str = "LiveLane",
        metadata: Optional[dict] = None,
    ) -> str:
        """Record a lane event. Returns the event_id."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        event_id = f"evt-{uuid.uuid4().hex[:12]}"
        timestamp = int(time.time() * 1000)

        cursor.execute(
            """
            INSERT INTO orch_lane_events
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

    def list_by_lane(
        self, lane_id: str, limit: int = 100, offset: int = 0
    ) -> List[dict]:
        """List events for a lane, ordered by timestamp."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM orch_lane_events
            WHERE lane_id = ?
            ORDER BY timestamp ASC
            LIMIT ? OFFSET ?
            """,
            (lane_id, limit, offset),
        )
        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def list_by_task(self, task_id: str, limit: int = 100) -> List[dict]:
        """List events for a task (across all lanes)."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM orch_lane_events
            WHERE task_id = ?
            ORDER BY timestamp ASC
            LIMIT ?
            """,
            (task_id, limit),
        )
        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def _row_to_dict(self, row: Any) -> dict:
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


__all__ = ["OrchLaneRepository", "OrchLaneEventRepository"]
