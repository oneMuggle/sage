"""项目资料仓储 (M3 项目上下文沉淀, 2026-09-15)。

"资料" = 用户显式添加的参考资料（Markdown 文本），注入 system prompt 供
上下文使用。设计约束：

- 按 (project_id, content_hash) 去重：同内容重复添加返回已有行；
- 三态 status: pending_index (待索引) / ready (已索引) / failed (失败)；
- source_message_id 可选，记录来源消息（save-answer 场景）；
- content 直接存 SQLite（单资料上限 64 KB，避免大文档拖慢查询）；
- get_active_materials_for_project 返回 ready 状态资料，按 created_at ASC
  排序（旧的先注入），供 project_context.py 拼接进 system prompt。
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from dataclasses import dataclass
from typing import List, Optional

from backend.data.database import get_database

logger = logging.getLogger(__name__)

#: 单资料内容上限 (字符数)。超出拒绝添加，避免大文档拖慢 SQLite 查询。
MAX_MATERIAL_CONTENT_CHARS = 64_000


class ProjectMaterialContentTooLargeError(ValueError):
    """资料内容超出上限。"""


@dataclass
class ProjectMaterial:
    """project_materials 表一行。"""

    id: str
    project_id: str
    source_message_id: Optional[str]
    content_hash: str
    content: str
    status: str  # "pending_index" | "ready" | "failed"
    wiki_page_path: Optional[str]
    error_message: Optional[str]
    created_at: int

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "source_message_id": self.source_message_id,
            "content_hash": self.content_hash,
            "content": self.content,
            "status": self.status,
            "wiki_page_path": self.wiki_page_path,
            "error_message": self.error_message,
            "created_at": self.created_at,
        }


def _row_to_material(row) -> ProjectMaterial:  # noqa: ANN001 — sqlite3.Row
    return ProjectMaterial(
        id=row["id"],
        project_id=row["project_id"],
        source_message_id=row["source_message_id"],
        content_hash=row["content_hash"],
        content=row["content"],
        status=row["status"],
        wiki_page_path=row["wiki_page_path"],
        error_message=row["error_message"],
        created_at=row["created_at"],
    )


def _compute_content_hash(content: str) -> str:
    """计算内容 SHA-256 哈希 (strip 后比较，避免空白差异)。"""
    return hashlib.sha256(content.strip().encode("utf-8", "replace")).hexdigest()


class ProjectMaterialRepository:
    """project_materials 表 CRUD + 状态管理。"""

    def __init__(self):
        self.db = get_database()

    def add(
        self,
        project_id: str,
        content: str,
        source_message_id: Optional[str] = None,
        now_ms: Optional[int] = None,
    ) -> ProjectMaterial:
        """添加资料，返回新建或已有行（按 project+hash 去重）。

        Raises:
            ProjectMaterialContentTooLargeError: 内容超出上限。
        """
        if len(content) > MAX_MATERIAL_CONTENT_CHARS:
            raise ProjectMaterialContentTooLargeError(
                f"Material content exceeds {MAX_MATERIAL_CONTENT_CHARS} chars"
            )

        content_hash = _compute_content_hash(content)
        ts = int(time.time() * 1000) if now_ms is None else now_ms
        conn = self.db.get_connection()

        # 幂等: 同 (project_id, content_hash) 返回已有行
        existing = conn.execute(
            "SELECT * FROM project_materials WHERE project_id = ? AND content_hash = ?",
            (project_id, content_hash),
        ).fetchone()
        if existing is not None:
            return _row_to_material(existing)

        material_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO project_materials
                (id, project_id, source_message_id, content_hash, content,
                 status, wiki_page_path, error_message, created_at)
            VALUES (?, ?, ?, ?, ?, 'pending_index', NULL, NULL, ?)
            """,
            (material_id, project_id, source_message_id, content_hash, content, ts),
        )
        conn.commit()

        row = conn.execute(
            "SELECT * FROM project_materials WHERE id = ?", (material_id,)
        ).fetchone()
        assert row is not None
        return _row_to_material(row)

    def list_by_project(
        self, project_id: str, limit: int = 100
    ) -> List[ProjectMaterial]:
        """按项目列出资料，按 created_at DESC（新的在前）。"""
        conn = self.db.get_connection()
        rows = conn.execute(
            """
            SELECT * FROM project_materials
            WHERE project_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (project_id, limit),
        ).fetchall()
        return [_row_to_material(row) for row in rows]

    def get(self, material_id: str) -> Optional[ProjectMaterial]:
        """按 id 获取资料，不存在返回 None。"""
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM project_materials WHERE id = ?", (material_id,)
        ).fetchone()
        return None if row is None else _row_to_material(row)

    def remove(self, material_id: str) -> bool:
        """删除资料，返回是否成功（不存在返回 False）。"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM project_materials WHERE id = ?", (material_id,))
        conn.commit()
        return cursor.rowcount > 0

    def mark_ready(
        self, material_id: str, wiki_page_path: Optional[str] = None
    ) -> bool:
        """标记索引完成，状态变 ready。不存在返回 False。"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE project_materials
            SET status = 'ready', wiki_page_path = ?, error_message = NULL
            WHERE id = ?
            """,
            (wiki_page_path, material_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    def mark_failed(self, material_id: str, error_message: str) -> bool:
        """标记索引失败，状态变 failed，记录错误信息。不存在返回 False。"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE project_materials
            SET status = 'failed', error_message = ?
            WHERE id = ?
            """,
            (error_message, material_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    def get_active_materials_for_project(
        self, project_id: str
    ) -> List[ProjectMaterial]:
        """返回 ready 状态资料，按 created_at ASC（旧的先注入），供上下文拼接。"""
        conn = self.db.get_connection()
        rows = conn.execute(
            """
            SELECT * FROM project_materials
            WHERE project_id = ? AND status = 'ready'
            ORDER BY created_at ASC, id ASC
            """,
            (project_id,),
        ).fetchall()
        return [_row_to_material(row) for row in rows]


__all__ = [
    "MAX_MATERIAL_CONTENT_CHARS",
    "ProjectMaterial",
    "ProjectMaterialContentTooLargeError",
    "ProjectMaterialRepository",
]
