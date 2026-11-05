"""项目内文件引用 (P5, 2026-11-05 项目管理增强, 设计 §9)。

``file_references`` 把项目内虚拟路径 (``rel_path``) 映射到任意绝对目标
(``target_path``)。扫描器为发现的符号链接自动登记 ``kind='symlink'``
记录; 用户也可以手动创建 ``file`` / ``directory`` 引用。

v1 语义只读: 引用放行读取, 不放行写入 (见 ``backend/tools/base.py`` 第 3 层)。
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from backend.data.database import get_database

logger = logging.getLogger(__name__)

__all__ = [
    "FileReference",
    "FileReferenceConflictError",
    "FileReferenceNotFoundError",
    "FileReferenceRepository",
    "InvalidReferencePathError",
    "KIND_DIRECTORY",
    "KIND_FILE",
    "KIND_SYMLINK",
    "normalize_rel_path",
    "normalize_target_path",
]

KIND_FILE = "file"
KIND_DIRECTORY = "directory"
KIND_SYMLINK = "symlink"
_VALID_KINDS = (KIND_FILE, KIND_DIRECTORY, KIND_SYMLINK)

_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")


class InvalidReferencePathError(ValueError):
    """rel_path / target_path 形态非法 (越界、绝对 rel、NUL 等)。"""


class FileReferenceConflictError(ValueError):
    """同一项目内 rel_path 已被登记。"""


class FileReferenceNotFoundError(LookupError):
    """引用不存在。"""


def _now_ms() -> int:
    return int(time.time() * 1000)


def normalize_rel_path(raw: str) -> str:
    """把项目内相对路径规范为 POSIX 风格、无前导斜杠的形式。

    拒绝空串、绝对路径、Windows 盘符、``..`` 段与 NUL 字符。
    合法示例: ``data/cases``、``docs``。
    """
    if raw is None:
        raise InvalidReferencePathError("rel_path is required")
    text = str(raw).strip().replace("\\", "/")
    if not text:
        raise InvalidReferencePathError("rel_path is required")
    if "\x00" in text:
        raise InvalidReferencePathError("rel_path contains NUL byte")
    if text.startswith("/") or _DRIVE_RE.match(text):
        raise InvalidReferencePathError("rel_path must be project-relative")
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts:
        raise InvalidReferencePathError("rel_path is required")
    if any(part == ".." for part in parts):
        raise InvalidReferencePathError("rel_path must not contain '..'")
    return "/".join(parts)


def normalize_target_path(raw: str) -> str:
    """目标必须是绝对路径; 统一分隔符后做 normpath (保留盘符形态)。"""
    text = str(raw or "").strip()
    if not text:
        raise InvalidReferencePathError("target_path is required")
    if "\x00" in text:
        raise InvalidReferencePathError("target_path contains NUL byte")
    normalized = os.path.normpath(text.replace("\\", "/"))
    if not Path(normalized).is_absolute() and not _DRIVE_RE.match(normalized):
        raise InvalidReferencePathError("target_path must be absolute")
    return normalized


@dataclass
class FileReference:
    id: str
    project_id: str
    alias_name: str
    rel_path: str
    target_path: str
    kind: str
    created_at: int

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "alias_name": self.alias_name,
            "rel_path": self.rel_path,
            "target_path": self.target_path,
            "kind": self.kind,
            "created_at": self.created_at,
        }


class FileReferenceRepository:
    def __init__(self, db=None):
        self.db = db or get_database()

    @staticmethod
    def _row_to_reference(row) -> FileReference:
        return FileReference(
            id=row["id"],
            project_id=row["project_id"],
            alias_name=row["alias_name"],
            rel_path=row["rel_path"],
            target_path=row["target_path"],
            kind=row["kind"],
            created_at=row["created_at"],
        )

    def list_by_project(self, project_id: str) -> List[FileReference]:
        conn = self.db.get_connection()
        rows = conn.execute(
            "SELECT * FROM file_references WHERE project_id = ? ORDER BY rel_path",
            (project_id,),
        ).fetchall()
        return [self._row_to_reference(row) for row in rows]

    def get(self, reference_id: str) -> Optional[FileReference]:
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM file_references WHERE id = ?", (reference_id,)
        ).fetchone()
        return self._row_to_reference(row) if row is not None else None

    def find_by_rel_path(
        self, project_id: str, rel_path: str
    ) -> Optional[FileReference]:
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM file_references WHERE project_id = ? AND rel_path = ?",
            (project_id, rel_path),
        ).fetchone()
        return self._row_to_reference(row) if row is not None else None

    def create(
        self,
        project_id: str,
        rel_path: str,
        target_path: str,
        kind: str = KIND_FILE,
        alias_name: Optional[str] = None,
    ) -> FileReference:
        rel = normalize_rel_path(rel_path)
        target = normalize_target_path(target_path)
        if kind not in _VALID_KINDS:
            raise InvalidReferencePathError(f"unsupported reference kind: {kind}")
        alias = (alias_name or "").strip() or Path(rel).name or rel
        reference = FileReference(
            id=str(uuid.uuid4()),
            project_id=project_id,
            alias_name=alias[:200],
            rel_path=rel,
            target_path=target,
            kind=kind,
            created_at=_now_ms(),
        )
        conn = self.db.get_connection()
        try:
            conn.execute(
                "INSERT INTO file_references "
                "(id, project_id, alias_name, rel_path, target_path, kind, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    reference.id,
                    reference.project_id,
                    reference.alias_name,
                    reference.rel_path,
                    reference.target_path,
                    reference.kind,
                    reference.created_at,
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            raise FileReferenceConflictError(
                f"file reference already exists for rel_path: {rel}"
            ) from exc
        return reference

    def upsert_symlink(
        self,
        project_id: str,
        rel_path: str,
        target_path: str,
        alias_name: Optional[str] = None,
    ) -> FileReference:
        """扫描器专用幂等写入: 同 rel_path 已存在则只更新符号链接目标。

        用户手工创建的引用不会被扫描覆盖 (返回原记录)。永不删除记录。
        """
        rel = normalize_rel_path(rel_path)
        target = normalize_target_path(target_path)
        existing = self.find_by_rel_path(project_id, rel)
        if existing is not None:
            if existing.kind == KIND_SYMLINK and existing.target_path != target:
                conn = self.db.get_connection()
                conn.execute(
                    "UPDATE file_references SET target_path = ? WHERE id = ?",
                    (target, existing.id),
                )
                conn.commit()
                return self.get(existing.id) or existing
            return existing
        return self.create(
            project_id, rel, target, kind=KIND_SYMLINK, alias_name=alias_name
        )

    def delete(self, reference_id: str) -> bool:
        conn = self.db.get_connection()
        cursor = conn.execute(
            "DELETE FROM file_references WHERE id = ?", (reference_id,)
        )
        conn.commit()
        return cursor.rowcount > 0
