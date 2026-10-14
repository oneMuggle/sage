"""SQLite repository for design projects and artifacts."""

from __future__ import annotations

import contextlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backend.design.errors import DesignProjectNotFoundError
from backend.design.models import DesignArtifact, DesignProject

_PROJECT_COLUMNS = """
    id, name, kind, system_id, template_id, brief,
    status, created_at, updated_at
"""

_ARTIFACT_COLUMNS = """
    id, project_id, version, file_path, kind, title,
    export_formats, source_prompt, created_at
"""


def _project_from_row(row: tuple) -> DesignProject:
    """从 design_projects 行构造 DesignProject。"""
    return DesignProject(
        id=row[0], name=row[1], kind=row[2], system_id=row[3],
        template_id=row[4], brief=row[5], status=row[6],
        created_at=datetime.fromisoformat(row[7]),
        updated_at=datetime.fromisoformat(row[8]),
    )


class DesignRepo:
    """design_projects / design_artifacts 两张表的 CRUD。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create_project(
        self,
        id: str,
        name: str,
        kind: str,
        system_id: str,
        template_id: str,
        brief: str,
        created_at: datetime,
        updated_at: datetime,
        status: str = "draft",
    ) -> DesignProject:
        """插入设计项目并返回构造好的模型。"""
        self._conn.execute(
            f"""INSERT INTO design_projects ({_PROJECT_COLUMNS})
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (id, name, kind, system_id, template_id, brief, status,
             created_at.isoformat(), updated_at.isoformat()),
        )
        self._conn.commit()
        return DesignProject(
            id=id, name=name, kind=kind, system_id=system_id,
            template_id=template_id, brief=brief, status=status,
            created_at=created_at, updated_at=updated_at,
        )

    def get_project(self, project_id: str) -> DesignProject:
        """按 id 取项目，不存在抛 DesignProjectNotFoundError。"""
        cursor = self._conn.execute(
            f"SELECT {_PROJECT_COLUMNS} FROM design_projects WHERE id = ?",
            (project_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise DesignProjectNotFoundError(project_id)
        return _project_from_row(row)

    def list_projects(
        self, kind: Optional[str] = None, limit: int = 50,
    ) -> list[DesignProject]:
        """列出项目，按 updated_at 降序；kind 非空时按类型过滤。"""
        if kind:
            cursor = self._conn.execute(
                f"""SELECT {_PROJECT_COLUMNS}
                    FROM design_projects
                    WHERE kind = ?
                    ORDER BY updated_at DESC LIMIT ?""",
                (kind, limit),
            )
        else:
            cursor = self._conn.execute(
                f"""SELECT {_PROJECT_COLUMNS}
                    FROM design_projects
                    ORDER BY updated_at DESC LIMIT ?""",
                (limit,),
            )
        return [_project_from_row(r) for r in cursor.fetchall()]

    def update_project_status(self, project_id: str, status: str) -> None:
        """更新项目状态并顺手刷新 updated_at。"""
        now = datetime.now(timezone.utc).isoformat()  # noqa: UP017
        self._conn.execute(
            """UPDATE design_projects
               SET status = ?, updated_at = ?
               WHERE id = ?""",
            (status, now, project_id),
        )
        self._conn.commit()

    def delete_project(self, project_id: str) -> None:
        """删除项目。若 schema 含 ON DELETE CASCADE，关联 artifacts 自动清理。"""
        self._conn.execute(
            "DELETE FROM design_projects WHERE id = ?", (project_id,)
        )
        self._conn.commit()

    def create_artifact(
        self,
        id: str,
        project_id: str,
        version: int,
        html_content: str,
        title: str,
        file_path: str,
        kind: str,
        export_formats: list[str],
        source_prompt: str,
        created_at: datetime,
    ) -> DesignArtifact:
        """落库 artifact 元数据，并把 html_content 写入 file_path。

        H2: write the HTML file **before** the INSERT so that a write
        failure never leaves a ghost row in the database.  The INSERT +
        commit form a tight transaction window (H3) with no file I/O
        between them.
        """
        # Write file first (outside any transaction)
        p = Path(file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(html_content, encoding="utf-8")

        # Then DB insert + commit (tight window)
        self._conn.execute(
            f"""INSERT INTO design_artifacts ({_ARTIFACT_COLUMNS})
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (id, project_id, version, file_path, kind, title,
             json.dumps(export_formats), source_prompt,
             created_at.isoformat()),
        )
        self._conn.commit()
        return DesignArtifact(
            id=id, project_id=project_id, version=version,
            html_content=html_content, css_injected="", title=title,
            file_path=file_path, kind=kind,
            export_formats=export_formats,
            source_prompt=source_prompt, created_at=created_at,
        )

    def _load_artifact_row(self, row: tuple) -> DesignArtifact:
        """从 design_artifacts 行构造模型；HTML 内容从磁盘回读。"""
        html_content = ""
        with contextlib.suppress(FileNotFoundError):
            html_content = Path(row[3]).read_text(encoding="utf-8")
        return DesignArtifact(
            id=row[0], project_id=row[1], version=row[2],
            html_content=html_content, css_injected="", title=row[5],
            file_path=row[3], kind=row[4],
            export_formats=json.loads(row[6]),
            source_prompt=row[7],
            created_at=datetime.fromisoformat(row[8]),
        )

    def get_artifact(self, artifact_id: str) -> DesignArtifact:
        """按 id 取 artifact，不存在抛 DesignProjectNotFoundError。"""
        cursor = self._conn.execute(
            f"SELECT {_ARTIFACT_COLUMNS} FROM design_artifacts WHERE id = ?",
            (artifact_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise DesignProjectNotFoundError(f"Artifact {artifact_id}")
        return self._load_artifact_row(row)

    def list_artifacts(self, project_id: str) -> list[DesignArtifact]:
        """列出项目的全部 artifact，按 version 升序。"""
        cursor = self._conn.execute(
            f"""SELECT {_ARTIFACT_COLUMNS}
                FROM design_artifacts
                WHERE project_id = ?
                ORDER BY version ASC""",
            (project_id,),
        )
        return [self._load_artifact_row(r) for r in cursor.fetchall()]

    def get_latest_artifact(
        self, project_id: str,
    ) -> Optional[DesignArtifact]:
        """取版本号最大的 artifact；没有则返回 None。"""
        cursor = self._conn.execute(
            f"""SELECT {_ARTIFACT_COLUMNS}
                FROM design_artifacts
                WHERE project_id = ?
                ORDER BY version DESC LIMIT 1""",
            (project_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._load_artifact_row(row)
