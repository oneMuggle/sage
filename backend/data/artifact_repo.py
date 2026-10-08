# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""产物数据仓储 — 追踪会话中 write_file / office_create 生成的文件"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.data.database import Database

logger = logging.getLogger(__name__)


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
    # F11 (对标增强第四轮批次 D): PDF 独立分类以启用 data_url 内嵌预览
    ".pdf": "pdf",
    # C-2 (对标增强第五轮批次 C): Office 三件套独立分类，后端读内容时转 HTML 供前端内嵌预览
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
