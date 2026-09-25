"""项目约束仓储（项目类型分类系统，2026-09-24）。

项目约束是结构化的 AI 行为指导规则，替代纯文本 instructions。按类别分类
（coding_style/security/testing 等），支持触发模式匹配（glob）和优先级排序。

约束在构建系统提示词时注入，影响 AI 在该项目中的行为。
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
class ProjectConstraint:
    """project_constraints 表一行。"""

    id: str
    project_id: str
    category: str
    content: str
    trigger_pattern: Optional[str] = None
    priority: int = 5
    enabled: bool = True
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "category": self.category,
            "content": self.content,
            "trigger_pattern": self.trigger_pattern,
            "priority": self.priority,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _row_to_constraint(row) -> ProjectConstraint:  # noqa: ANN001 — sqlite3.Row
    return ProjectConstraint(
        id=row["id"],
        project_id=row["project_id"],
        category=row["category"],
        content=row["content"],
        trigger_pattern=row["trigger_pattern"],
        priority=row["priority"],
        enabled=bool(row["enabled"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _now_ms(now_ms: Optional[int] = None) -> int:
    return int(time.time() * 1000) if now_ms is None else now_ms


#: 预设约束模板。键为模板名，值为约束列表。
CONSTRAINT_TEMPLATES = {
    "python_default": [
        {"category": "coding_style", "content": "使用双引号字符串", "trigger_pattern": "*.py", "priority": 5},
        {"category": "coding_style", "content": "函数不超过 50 行", "trigger_pattern": "*.py", "priority": 5},
        {"category": "testing", "content": "新功能必须有单元测试", "trigger_pattern": "always", "priority": 7},
    ],
    "security_basic": [
        {"category": "security", "content": "禁止硬编码密钥或密码", "trigger_pattern": "always", "priority": 9},
        {"category": "security", "content": "所有数据库查询使用参数化查询，防止 SQL 注入", "trigger_pattern": "always", "priority": 9},
        {"category": "security", "content": "用户输入必须验证和清理", "trigger_pattern": "always", "priority": 8},
    ],
    "academic_writing": [
        {"category": "academic_writing", "content": "使用 APA 引用格式", "trigger_pattern": "always", "priority": 5},
        {"category": "academic_writing", "content": "避免第一人称，使用被动语态", "trigger_pattern": "always", "priority": 5},
        {"category": "experiment_record", "content": "实验记录须包含日期、方法、结果、分析", "trigger_pattern": "always", "priority": 7},
    ],
    "document_format": [
        {"category": "document_format", "content": "标题使用宋体三号", "trigger_pattern": "*.docx", "priority": 5},
        {"category": "confidentiality", "content": "文档须标注保密等级", "trigger_pattern": "always", "priority": 6},
    ],
}


class ProjectConstraintRepository:
    """project_constraints 表 CRUD。"""

    def __init__(self) -> None:
        self.db = get_database()

    def create(
        self,
        project_id: str,
        category: str,
        content: str,
        trigger_pattern: Optional[str] = None,
        priority: int = 5,
        now_ms: Optional[int] = None,
    ) -> ProjectConstraint:
        """创建一条约束。"""
        ts = _now_ms(now_ms)
        conn = self.db.get_connection()
        cursor = conn.cursor()
        constraint_id = str(uuid.uuid4())
        cursor.execute(
            """
            INSERT INTO project_constraints
                (id, project_id, category, content, trigger_pattern, priority, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (constraint_id, project_id, category, content, trigger_pattern, priority, ts, ts),
        )
        conn.commit()
        return ProjectConstraint(
            id=constraint_id,
            project_id=project_id,
            category=category,
            content=content,
            trigger_pattern=trigger_pattern,
            priority=priority,
            enabled=True,
            created_at=ts,
            updated_at=ts,
        )

    def get(self, constraint_id: str) -> Optional[ProjectConstraint]:
        """按 ID 获取约束。"""
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM project_constraints WHERE id = ?", (constraint_id,)
        ).fetchone()
        return None if row is None else _row_to_constraint(row)

    def list_by_project(
        self, project_id: str, enabled_only: bool = False
    ) -> List[ProjectConstraint]:
        """列出项目的所有约束（按优先级降序）。"""
        conn = self.db.get_connection()
        query = "SELECT * FROM project_constraints WHERE project_id = ?"
        params: list = [project_id]
        if enabled_only:
            query += " AND enabled = 1"
        query += " ORDER BY priority DESC, created_at ASC"
        rows = conn.execute(query, params).fetchall()
        return [_row_to_constraint(row) for row in rows]

    def update(
        self,
        constraint_id: str,
        category: Optional[str] = None,
        content: Optional[str] = None,
        trigger_pattern: Optional[str] = None,
        priority: Optional[int] = None,
        enabled: Optional[bool] = None,
        now_ms: Optional[int] = None,
    ) -> bool:
        """更新约束字段（仅更新非 None 参数）。不存在返回 False。"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        updates = []
        params: list = []
        if category is not None:
            updates.append("category = ?")
            params.append(category)
        if content is not None:
            updates.append("content = ?")
            params.append(content)
        if trigger_pattern is not None:
            updates.append("trigger_pattern = ?")
            params.append(trigger_pattern)
        if priority is not None:
            updates.append("priority = ?")
            params.append(priority)
        if enabled is not None:
            updates.append("enabled = ?")
            params.append(int(enabled))
        if not updates:
            return self.get(constraint_id) is not None
        updates.append("updated_at = ?")
        params.append(_now_ms(now_ms))
        params.append(constraint_id)
        cursor.execute(
            f"UPDATE project_constraints SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
        return cursor.rowcount > 0

    def delete(self, constraint_id: str) -> bool:
        """删除约束。不存在返回 False。"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM project_constraints WHERE id = ?", (constraint_id,)
        )
        conn.commit()
        return cursor.rowcount > 0

    def delete_by_project(self, project_id: str) -> int:
        """删除项目的所有约束，返回删除数量。"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM project_constraints WHERE project_id = ?", (project_id,)
        )
        conn.commit()
        return cursor.rowcount

    def import_template(
        self, project_id: str, template_name: str, now_ms: Optional[int] = None
    ) -> List[ProjectConstraint]:
        """从预设模板导入约束到项目。

        Args:
            project_id: 项目 ID
            template_name: 模板名（见 CONSTRAINT_TEMPLATES）

        Returns:
            创建的约束列表

        Raises:
            ValueError: 模板名不存在
        """
        if template_name not in CONSTRAINT_TEMPLATES:
            raise ValueError(
                f"Unknown constraint template: {template_name}. "
                f"Available: {list(CONSTRAINT_TEMPLATES.keys())}"
            )
        template = CONSTRAINT_TEMPLATES[template_name]
        created = []
        for item in template:
            constraint = self.create(
                project_id=project_id,
                category=item["category"],
                content=item["content"],
                trigger_pattern=item.get("trigger_pattern"),
                priority=item.get("priority", 5),
                now_ms=now_ms,
            )
            created.append(constraint)
        return created

    def resolve_active(
        self, project_id: str, current_file: Optional[str] = None
    ) -> List[ProjectConstraint]:
        """解析当前上下文应激活的约束。

        根据 trigger_pattern 匹配当前文件路径：
        - trigger_pattern 为 None 或 "always" → 始终激活
        - 其他值 → 使用 fnmatch 匹配 current_file

        Args:
            project_id: 项目 ID
            current_file: 当前操作的文件路径（可选）

        Returns:
            激活的约束列表（按优先级降序）
        """
        import fnmatch

        all_enabled = self.list_by_project(project_id, enabled_only=True)
        active = []
        for c in all_enabled:
            if c.trigger_pattern is None or c.trigger_pattern == "always":
                active.append(c)
            elif current_file and fnmatch.fnmatch(current_file, c.trigger_pattern):
                active.append(c)
        return sorted(active, key=lambda c: c.priority, reverse=True)


__all__ = [
    "CONSTRAINT_TEMPLATES",
    "ProjectConstraint",
    "ProjectConstraintRepository",
]
