"""
产物仓储层
负责追踪 AI 工具调用生成的文件产物 (artifacts 表 CRUD)
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from backend.data.database import get_database


@dataclass
class Artifact:
    """产物数据模型"""

    id: str
    session_id: str
    path: str
    name: str
    kind: str
    size: int
    created_at: int
    tool_call_id: Optional[str] = None

    @classmethod
    def from_row(cls, row) -> "Artifact":
        return cls(
            id=row["id"],
            session_id=row["session_id"],
            path=row["path"],
            name=row["name"],
            kind=row["kind"],
            size=row["size"] or 0,
            created_at=row["created_at"],
            tool_call_id=row["tool_call_id"],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "tool_call_id": self.tool_call_id,
            "path": self.path,
            "name": self.name,
            "kind": self.kind,
            "size": self.size,
            "created_at": self.created_at,
        }


def record_artifact(
    session_id: str,
    path: str,
    name: str,
    kind: str,
    size: int,
    tool_call_id: Optional[str] = None,
) -> str:
    """记录一个新产物,返回 artifact id。"""
    artifact_id = f"art_{uuid.uuid4().hex[:12]}"
    created_at = int(time.time() * 1000)
    db = get_database()
    conn = db.get_connection()
    conn.execute(
        """
        INSERT INTO artifacts
            (id, session_id, tool_call_id, path, name, kind, size, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (artifact_id, session_id, tool_call_id, path, name, kind, size, created_at),
    )
    conn.commit()
    return artifact_id


def list_artifacts(session_id: str) -> List[Artifact]:
    """列出指定 session 的所有产物,按 created_at 降序;同毫秒记录用 rowid 兜底防排序 flaky。"""
    db = get_database()
    conn = db.get_connection()
    cursor = conn.execute(
        "SELECT * FROM artifacts WHERE session_id = ? ORDER BY created_at DESC, rowid DESC",
        (session_id,),
    )
    return [Artifact.from_row(row) for row in cursor.fetchall()]


def get_artifact(artifact_id: str) -> Optional[Artifact]:
    """根据 id 查找产物,不存在返回 None。"""
    db = get_database()
    conn = db.get_connection()
    cursor = conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,))
    row = cursor.fetchone()
    return Artifact.from_row(row) if row else None
