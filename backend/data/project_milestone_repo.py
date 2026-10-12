"""项目里程碑仓储（项目类型分类系统，2026-09-24）。

里程碑用于追踪项目关键节点和到期日。按项目类型有不同的阶段枚举：
- coding: planning → development → testing → deployment → maintenance
- research: proposal → data_collection → analysis → writing → submission → revision
- business: initiation → planning → execution → monitoring → closure
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import List, Optional

from backend.data.database import get_database

logger = logging.getLogger(__name__)


@dataclass
class ProjectMilestone:
    """project_milestones 表一行。"""

    id: str
    project_id: str
    title: str
    description: Optional[str] = None
    stage: Optional[str] = None
    due_date: Optional[str] = None  # YYYY-MM-DD 格式
    completed_at: Optional[int] = None
    status: str = "pending"  # pending | in_progress | completed | blocked
    sort_order: int = 0
    created_at: int = 0
    parent_id: Optional[str] = None
    estimated_days: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "title": self.title,
            "description": self.description,
            "stage": self.stage,
            "due_date": self.due_date,
            "completed_at": self.completed_at,
            "status": self.status,
            "sort_order": self.sort_order,
            "created_at": self.created_at,
            "parent_id": self.parent_id,
            "estimated_days": self.estimated_days,
        }


def _row_to_milestone(row) -> ProjectMilestone:  # noqa: ANN001 — sqlite3.Row
    return ProjectMilestone(
        id=row["id"],
        project_id=row["project_id"],
        title=row["title"],
        description=row["description"],
        stage=row["stage"],
        due_date=row["due_date"],
        completed_at=row["completed_at"],
        status=row["status"],
        sort_order=row["sort_order"],
        created_at=row["created_at"],
        parent_id=row["parent_id"],
        estimated_days=row["estimated_days"],
    )


def _now_ms(now_ms: Optional[int] = None) -> int:
    return int(time.time() * 1000) if now_ms is None else now_ms


#: 各类型项目的阶段枚举。
PROJECT_STAGE_ENUM = {
    "coding": ["planning", "development", "testing", "deployment", "maintenance"],
    "research": ["proposal", "data_collection", "analysis", "writing", "submission", "revision"],
    "business": ["initiation", "planning", "execution", "monitoring", "closure"],
    "personal": None,  # 个人项目无阶段概念
}

#: 里程碑状态枚举。
MILESTONE_STATUS = ["pending", "in_progress", "completed", "blocked"]


class ProjectMilestoneRepository:
    """project_milestones 表 CRUD。"""

    def __init__(self) -> None:
        self.db = get_database()

    def create(
        self,
        project_id: str,
        title: str,
        description: Optional[str] = None,
        stage: Optional[str] = None,
        due_date: Optional[str] = None,
        sort_order: int = 0,
        now_ms: Optional[int] = None,
        parent_id: Optional[str] = None,
        estimated_days: Optional[float] = None,
    ) -> ProjectMilestone:
        """创建一个里程碑。

        Args:
            project_id: 项目 ID
            title: 里程碑标题
            description: 详细描述（可选）
            stage: 所属阶段（按项目类型有不同枚举）
            due_date: 到期日（YYYY-MM-DD 格式，可选）
            sort_order: 排序序号
            parent_id: 父里程碑 ID（可选，用于层级结构）
            estimated_days: AI 估算工时天数（可选）
        """
        ts = _now_ms(now_ms)
        conn = self.db.get_connection()
        cursor = conn.cursor()
        milestone_id = str(uuid.uuid4())
        cursor.execute(
            """
            INSERT INTO project_milestones
                (id, project_id, title, description, stage, due_date,
                 status, sort_order, created_at, parent_id, estimated_days)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
            """,
            (milestone_id, project_id, title, description, stage, due_date,
             sort_order, ts, parent_id, estimated_days),
        )
        conn.commit()
        return ProjectMilestone(
            id=milestone_id,
            project_id=project_id,
            title=title,
            description=description,
            stage=stage,
            due_date=due_date,
            completed_at=None,
            status="pending",
            sort_order=sort_order,
            created_at=ts,
            parent_id=parent_id,
            estimated_days=estimated_days,
        )

    def get(self, milestone_id: str) -> Optional[ProjectMilestone]:
        """按 ID 获取里程碑。"""
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM project_milestones WHERE id = ?", (milestone_id,)
        ).fetchone()
        return None if row is None else _row_to_milestone(row)

    def list_by_project(
        self, project_id: str, status: Optional[str] = None
    ) -> List[ProjectMilestone]:
        """列出项目的所有里程碑（按 sort_order 升序）。

        Args:
            project_id: 项目 ID
            status: 可选，按状态过滤
        """
        conn = self.db.get_connection()
        query = "SELECT * FROM project_milestones WHERE project_id = ?"
        params: list = [project_id]
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY sort_order ASC, created_at ASC"
        rows = conn.execute(query, params).fetchall()
        return [_row_to_milestone(row) for row in rows]

    def update(
        self,
        milestone_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        stage: Optional[str] = None,
        due_date: Optional[str] = None,
        status: Optional[str] = None,
        sort_order: Optional[int] = None,
    ) -> bool:
        """更新里程碑字段（仅更新非 None 参数）。不存在返回 False。

        如果 status 更新为 'completed'，自动设置 completed_at。
        如果 status 从 'completed' 改为其他，清除 completed_at。
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()
        updates = []
        params: list = []

        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        if stage is not None:
            updates.append("stage = ?")
            params.append(stage)
        if due_date is not None:
            updates.append("due_date = ?")
            params.append(due_date)
        if sort_order is not None:
            updates.append("sort_order = ?")
            params.append(sort_order)

        # 处理状态变更和 completed_at
        if status is not None:
            if status not in MILESTONE_STATUS:
                raise ValueError(f"Invalid status: {status}. Must be one of {MILESTONE_STATUS}")
            updates.append("status = ?")
            params.append(status)
            if status == "completed":
                updates.append("completed_at = ?")
                params.append(_now_ms())
            else:
                # 检查当前是否为 completed，如果是则清除 completed_at
                current = self.get(milestone_id)
                if current and current.status == "completed" and status != "completed":
                    updates.append("completed_at = NULL")

        if not updates:
            return self.get(milestone_id) is not None

        params.append(milestone_id)
        cursor.execute(
            f"UPDATE project_milestones SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
        return cursor.rowcount > 0

    def mark_completed(self, milestone_id: str, now_ms: Optional[int] = None) -> bool:
        """标记里程碑为已完成。"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE project_milestones SET status = 'completed', completed_at = ? WHERE id = ?",
            (_now_ms(now_ms), milestone_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    def delete(self, milestone_id: str) -> bool:
        """删除里程碑。不存在返回 False。"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM project_milestones WHERE id = ?", (milestone_id,)
        )
        conn.commit()
        return cursor.rowcount > 0

    def delete_by_project(self, project_id: str) -> int:
        """删除项目的所有里程碑，返回删除数量。"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM project_milestones WHERE project_id = ?", (project_id,)
        )
        conn.commit()
        return cursor.rowcount

    def count_by_status(self, project_id: str) -> dict:
        """按状态统计里程碑数量。

        Returns:
            {"pending": 3, "in_progress": 1, "completed": 5, "blocked": 0}
        """
        conn = self.db.get_connection()
        rows = conn.execute(
            """
            SELECT status, COUNT(*) as cnt
            FROM project_milestones
            WHERE project_id = ?
            GROUP BY status
            """,
            (project_id,),
        ).fetchall()
        result = {s: 0 for s in MILESTONE_STATUS}
        for row in rows:
            result[row["status"]] = row["cnt"]
        return result

    def create_batch(
        self,
        project_id: str,
        items: List[dict],
        now_ms: Optional[int] = None,
    ) -> List[ProjectMilestone]:
        """批量创建里程碑（AI 任务分解用）。

        每个 item dict 支持的键（与 create() 参数对齐）：
            title (str, 必填), description, stage, due_date,
            sort_order, parent_id, estimated_days

        parent_id 引用同批次内其他 item 时，使用 item 的临时 ``_ref``
        键（字符串标识符），create_batch 内部映射为真实 UUID。

        Returns:
            创建的 ProjectMilestone 列表（含真实 id）。
        """
        ts = _now_ms(now_ms)
        conn = self.db.get_connection()
        cursor = conn.cursor()
        created: List[ProjectMilestone] = []
        ref_map: dict = {}  # _ref → real uuid

        # Pass 1: 分配 UUID，建立 ref 映射
        for item in items:
            mid = str(uuid.uuid4())
            ref = item.get("_ref")
            if ref:
                ref_map[ref] = mid

        # Pass 2: 插入，解析 parent_id 引用
        for idx, item in enumerate(items):
            mid = ref_map.get(item["_ref"]) if item.get("_ref") else str(uuid.uuid4())
            raw_parent = item.get("parent_id")
            resolved_parent = ref_map.get(raw_parent) if raw_parent else None

            cursor.execute(
                """
                INSERT INTO project_milestones
                    (id, project_id, title, description, stage, due_date,
                     status, sort_order, created_at, parent_id, estimated_days)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
                """,
                (
                    mid,
                    project_id,
                    item["title"],
                    item.get("description"),
                    item.get("stage"),
                    item.get("due_date"),
                    item.get("sort_order", idx),
                    ts,
                    resolved_parent,
                    item.get("estimated_days"),
                ),
            )
            created.append(ProjectMilestone(
                id=mid,
                project_id=project_id,
                title=item["title"],
                description=item.get("description"),
                stage=item.get("stage"),
                due_date=item.get("due_date"),
                completed_at=None,
                status="pending",
                sort_order=item.get("sort_order", idx),
                created_at=ts,
                parent_id=resolved_parent,
                estimated_days=item.get("estimated_days"),
            ))

        conn.commit()
        return created

    def get_tree(self, project_id: str) -> List[dict]:
        """获取项目的里程碑树（嵌套结构）。

        Returns:
            顶层里程碑列表，每个里程碑含 ``children`` 键嵌套子里程碑。
            格式: [{"id": ..., "title": ..., "children": [...]}]
        """
        all_ms = self.list_by_project(project_id)
        by_parent: dict = {}
        roots: List[ProjectMilestone] = []
        for ms in all_ms:
            if ms.parent_id is None:
                roots.append(ms)
            else:
                by_parent.setdefault(ms.parent_id, []).append(ms)

        def _nest(ms: ProjectMilestone) -> dict:
            d = ms.to_dict()
            d["children"] = [
                _nest(child) for child in by_parent.get(ms.id, [])
            ]
            return d

        return [_nest(r) for r in roots]


__all__ = [
    "MILESTONE_STATUS",
    "PROJECT_STAGE_ENUM",
    "ProjectMilestone",
    "ProjectMilestoneRepository",
]
