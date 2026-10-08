# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""产物数据仓储 — 追踪会话中 write_file / office_create 生成的文件"""

from __future__ import annotations

import contextlib
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from backend.data.database import Database, get_database

logger = logging.getLogger(__name__)

_ARTIFACT_LISTENERS: List[Callable[[Dict[str, Any]], None]] = []


def add_artifact_listener(
    fn: Callable[[Dict[str, Any]], None],
) -> Callable[[Dict[str, Any]], None]:
    """注册产物事件监听器；返回 fn 便于 remove_artifact_listener 配对。"""
    _ARTIFACT_LISTENERS.append(fn)
    return fn


def remove_artifact_listener(fn: Callable[[Dict[str, Any]], None]) -> None:
    """注销产物事件监听器（producer finally 必须配对调用，防闭包泄漏）。"""
    with contextlib.suppress(ValueError):
        _ARTIFACT_LISTENERS.remove(fn)


def _emit_artifact_event(event: Dict[str, Any]) -> None:
    for fn in list(_ARTIFACT_LISTENERS):
        with contextlib.suppress(Exception):
            fn(event)


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
    workspace_path: Optional[str] = None
    format_spec: Optional[str] = None

    @classmethod
    def from_row(cls, row: Any) -> Artifact:
        keys = row.keys() if hasattr(row, "keys") else ()
        return cls(
            id=row["id"],
            session_id=row["session_id"],
            path=row["path"],
            name=row["name"],
            kind=row["kind"],
            size=row["size"] or 0,
            created_at=row["created_at"],
            tool_call_id=row["tool_call_id"],
            workspace_path=row["workspace_path"] if "workspace_path" in keys else None,
            format_spec=row["format_spec"] if "format_spec" in keys else None,
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
            "workspace_path": self.workspace_path,
            "format_spec": self.format_spec,
        }


def record_artifact(
    session_id: str,
    path: str,
    name: str,
    kind: str,
    size: int,
    tool_call_id: Optional[str] = None,
    workspace_path: Optional[str] = None,
    format_spec: Optional[str] = None,
) -> str:
    """记录一个新产物,返回 artifact id。落库成功后广播 artifact_created 事件（S7）。"""
    artifact_id = f"art_{uuid.uuid4().hex[:12]}"
    created_at = int(time.time() * 1000)
    db = get_database()
    conn = db.get_connection()
    conn.execute(
        """
        INSERT INTO artifacts (
            id, session_id, tool_call_id, path, name, kind, size,
            created_at, workspace_path, format_spec
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            artifact_id,
            session_id,
            tool_call_id,
            path,
            name,
            kind,
            size,
            created_at,
            workspace_path,
            format_spec,
        ),
    )
    conn.commit()
    _emit_artifact_event(
        {
            "state": "artifact_created",
            "session_id": session_id,
            "artifact": {
                "id": artifact_id,
                "path": path,
                "name": name,
                "kind": kind,
                "size": size,
                "created_at": created_at,
                "workspace_path": workspace_path,
                "format_spec": format_spec,
            },
        }
    )
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


_EXT_KIND_MAP = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".mdx": "markdown",
    ".py": "code",
    ".js": "code",
    ".ts": "code",
    ".tsx": "code",
    ".jsx": "code",
    ".rs": "code",
    ".go": "code",
    ".java": "code",
    ".c": "code",
    ".cpp": "code",
    ".h": "code",
    ".hpp": "code",
    ".cs": "code",
    ".rb": "code",
    ".php": "code",
    ".swift": "code",
    ".kt": "code",
    ".sh": "code",
    ".bash": "code",
    ".zsh": "code",
    ".ps1": "code",
    ".sql": "code",
    ".html": "code",
    ".css": "code",
    ".scss": "code",
    ".yaml": "code",
    ".yml": "code",
    ".toml": "code",
    ".ini": "code",
    ".xml": "code",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".webp": "image",
    ".svg": "image",
    ".bmp": "image",
    ".csv": "csv",
    ".tsv": "csv",
    ".json": "json",
    ".pdf": "pdf",
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".pptx": "pptx",
}


def classify_artifact(file_path: str) -> str:
    """根据扩展名推断产物类型"""
    ext = Path(file_path).suffix.lower()
    return _EXT_KIND_MAP.get(ext, "text")


class ArtifactRepository:
    """产物数据访问层"""

    def __init__(self, db: Database):
        self.db = db

    def record_artifact(
        self,
        *,
        session_id: str,
        path: str,
        name: str,
        kind: str,
        size: int = 0,
        tool_call_id: Optional[str] = None,
        workspace_path: Optional[str] = None,
        format_spec: Optional[str] = None,
    ) -> Dict[str, Any]:
        """写入或更新产物记录(按 session_id + path 去重,保留最新元数据)"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        now = int(time.time())

        cursor.execute(
            "SELECT id FROM artifacts WHERE session_id = ? AND path = ?",
            (session_id, path),
        )
        existing = cursor.fetchone()
        if existing:
            artifact_id = existing["id"]
            cursor.execute(
                """
                UPDATE artifacts
                SET size = ?, tool_call_id = ?, created_at = ?,
                    workspace_path = COALESCE(?, workspace_path),
                    format_spec = COALESCE(?, format_spec)
                WHERE id = ?
                """,
                (size, tool_call_id, now, workspace_path, format_spec, artifact_id),
            )
        else:
            artifact_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO artifacts (
                    id, session_id, tool_call_id, path, name, kind, size,
                    created_at, workspace_path, format_spec
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    session_id,
                    tool_call_id,
                    path,
                    name,
                    kind,
                    size,
                    now,
                    workspace_path,
                    format_spec,
                ),
            )
        conn.commit()
        return {
            "id": artifact_id,
            "session_id": session_id,
            "tool_call_id": tool_call_id,
            "path": path,
            "name": name,
            "kind": kind,
            "size": size,
            "created_at": now,
            "workspace_path": workspace_path,
            "format_spec": format_spec,
        }

    def list_by_session(self, session_id: str) -> List[Dict[str, Any]]:
        """按会话列出产物,最新的在前"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, session_id, tool_call_id, path, name, kind, size,
                   created_at, workspace_path, format_spec
            FROM artifacts
            WHERE session_id = ?
            ORDER BY created_at DESC
            """,
            (session_id,),
        )
        rows = cursor.fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_artifact(self, artifact_id: str) -> Optional[Dict[str, Any]]:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, session_id, tool_call_id, path, name, kind, size,
                   created_at, workspace_path, format_spec
            FROM artifacts
            WHERE id = ?
            """,
            (artifact_id,),
        )
        row = cursor.fetchone()
        return self._row_to_dict(row) if row else None

    def delete_by_session(self, session_id: str) -> int:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM artifacts WHERE session_id = ?", (session_id,))
        conn.commit()
        return cursor.rowcount

    @staticmethod
    def _row_to_dict(row: Any) -> Dict[str, Any]:
        keys = row.keys() if hasattr(row, "keys") else ()
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "tool_call_id": row["tool_call_id"],
            "path": row["path"],
            "name": row["name"],
            "kind": row["kind"],
            "size": row["size"] or 0,
            "created_at": row["created_at"],
            "workspace_path": row["workspace_path"] if "workspace_path" in keys else None,
            "format_spec": row["format_spec"] if "format_spec" in keys else None,
        }
