"""
闲时自主目标执行系统 — 数据持久化层

GoalRepository: 目标的 CRUD 操作
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from typing import List, Optional

from backend.data.database import get_database
from backend.domain.autonomous_goals import (
    Checkpoint,
    DegradationLevel,
    ExecutionBudget,
    ExecutionRound,
    Goal,
    GoalStatus,
    TimeWindow,
)

logger = logging.getLogger(__name__)


class GoalRepository:
    """SQLite-backed autonomous_goals CRUD"""

    def __init__(self) -> None:
        self.db = get_database()

    def create(self, goal: Goal) -> Goal:
        """创建新目标"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO autonomous_goals (
                    id, name, description, status, session_id,
                    time_window, budget, checkpoints, rounds,
                    current_round, created_at, started_at, completed_at,
                    total_tokens_used, completion_percentage,
                    degradation_level, last_error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    goal.id,
                    goal.name,
                    goal.description,
                    goal.status.value,
                    goal.session_id,
                    json.dumps(goal.time_window.to_dict()),
                    json.dumps(goal.budget.to_dict()),
                    json.dumps([c.to_dict() for c in goal.checkpoints]),
                    json.dumps([r.to_dict() for r in goal.rounds]),
                    goal.current_round,
                    goal.created_at.isoformat(),
                    goal.started_at.isoformat() if goal.started_at else None,
                    goal.completed_at.isoformat() if goal.completed_at else None,
                    goal.total_tokens_used,
                    goal.completion_percentage,
                    goal.degradation_level.value,
                    goal.last_error,
                ),
            )
            conn.commit()
            logger.info(f"Created goal: {goal.id}")
            return goal
        except sqlite3.IntegrityError as e:
            logger.error(f"Failed to create goal {goal.id}: {e}")
            raise

    def get(self, goal_id: str) -> Optional[Goal]:
        """获取目标详情"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM autonomous_goals WHERE id = ?", (goal_id,))
        row = cursor.fetchone()
        return self._row_to_goal(row) if row else None

    def list_all(
        self,
        status: Optional[GoalStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Goal]:
        """获取目标列表"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        if status:
            cursor.execute(
                """
                SELECT * FROM autonomous_goals
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (status.value, limit, offset),
            )
        else:
            cursor.execute(
                """
                SELECT * FROM autonomous_goals
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )

        return [self._row_to_goal(row) for row in cursor.fetchall()]

    def update(self, goal: Goal) -> Goal:
        """更新目标"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                UPDATE autonomous_goals
                SET
                    name = ?,
                    description = ?,
                    status = ?,
                    session_id = ?,
                    time_window = ?,
                    budget = ?,
                    checkpoints = ?,
                    rounds = ?,
                    current_round = ?,
                    started_at = ?,
                    completed_at = ?,
                    total_tokens_used = ?,
                    completion_percentage = ?,
                    degradation_level = ?,
                    last_error = ?
                WHERE id = ?
                """,
                (
                    goal.name,
                    goal.description,
                    goal.status.value,
                    goal.session_id,
                    json.dumps(goal.time_window.to_dict()),
                    json.dumps(goal.budget.to_dict()),
                    json.dumps([c.to_dict() for c in goal.checkpoints]),
                    json.dumps([r.to_dict() for r in goal.rounds]),
                    goal.current_round,
                    goal.started_at.isoformat() if goal.started_at else None,
                    goal.completed_at.isoformat() if goal.completed_at else None,
                    goal.total_tokens_used,
                    goal.completion_percentage,
                    goal.degradation_level.value,
                    goal.last_error,
                    goal.id,
                ),
            )
            conn.commit()
            logger.info(f"Updated goal: {goal.id}")
            return goal
        except Exception as e:
            logger.error(f"Failed to update goal {goal.id}: {e}")
            raise

    def delete(self, goal_id: str) -> bool:
        """删除目标"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("DELETE FROM autonomous_goals WHERE id = ?", (goal_id,))
            conn.commit()
            deleted = cursor.rowcount > 0
            if deleted:
                logger.info(f"Deleted goal: {goal_id}")
            return deleted
        except Exception as e:
            logger.error(f"Failed to delete goal {goal_id}: {e}")
            raise

    def _row_to_goal(self, row: sqlite3.Row) -> Goal:
        """将数据库行转换为 Goal 对象"""
        time_window_data = json.loads(row["time_window"]) if row["time_window"] else {}
        budget_data = json.loads(row["budget"]) if row["budget"] else {}
        checkpoints_data = json.loads(row["checkpoints"]) if row["checkpoints"] else []
        rounds_data = json.loads(row["rounds"]) if row["rounds"] else []

        return Goal(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            status=GoalStatus(row["status"]),
            session_id=row["session_id"],
            time_window=TimeWindow.from_dict(time_window_data),
            budget=ExecutionBudget.from_dict(budget_data),
            checkpoints=[Checkpoint.from_dict(c) for c in checkpoints_data],
            rounds=[ExecutionRound.from_dict(r) for r in rounds_data],
            current_round=row["current_round"],
            created_at=datetime.fromisoformat(row["created_at"]),
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            total_tokens_used=row["total_tokens_used"],
            completion_percentage=row["completion_percentage"],
            degradation_level=DegradationLevel(row["degradation_level"]),
            last_error=row["last_error"],
        )
