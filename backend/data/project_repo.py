"""项目注册表仓储（项目模块 P1, 2026-09-13）。

"项目" = 用户在侧边栏显式登记的工作目录。设计对标主流 AI 工具的项目
概念（Cursor 的 Recent Workspaces、Claude Code 的项目 → 会话归属）：

- 项目行独立于会话存在：登记过的目录即使还没有任何会话绑定也保留；
- 会话与目录的归属关系**不**落在 projects 表，复用
  ``session_workspace_bindings`` 的活跃绑定（revoked_at IS NULL 且
  workspace_path 与项目路径相等）——绑定已在 fork/变更面板/检查点等
  链路上验证过，避免第二份归属数据漂移；
- 路径统一经 ``validate_workspace`` 规范化为绝对路径后再入库，因此
  重复登记同一目录是幂等的（刷新 last_opened_at 而非新增行）。
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from backend.data.database import get_database
from backend.data.session_repo import Session, SessionRepository
from backend.office.errors import OfficePathError
from backend.office.session_workspace import bind_session_workspace
from backend.office.storage import validate_workspace

logger = logging.getLogger(__name__)

#: 侧边栏项目清单默认上限。超出的最旧项目仍在库里，只是不再下发。
DEFAULT_LIST_LIMIT = 50

#: 单个项目下会话列表上限（项目行展开/前端"最近会话"预取共用）。
PROJECT_SESSIONS_LIMIT = 20


class ProjectNotFoundError(LookupError):
    """项目 id 不在注册表中。"""


class ProjectPathMissingError(Exception):
    """项目目录在磁盘上已不存在（被移动/删除），打开被拒绝。"""


@dataclass
class Project:
    """projects 表一行。"""

    id: str
    path: str
    name: str
    created_at: int
    last_opened_at: int

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "path": self.path,
            "name": self.name,
            "created_at": self.created_at,
            "last_opened_at": self.last_opened_at,
        }


def _row_to_project(row) -> Project:  # noqa: ANN001 — sqlite3.Row
    return Project(
        id=row["id"],
        path=row["path"],
        name=row["name"],
        created_at=row["created_at"],
        last_opened_at=row["last_opened_at"],
    )


def _now_ms(now_ms: Optional[int]) -> int:
    return int(time.time() * 1000) if now_ms is None else now_ms


class ProjectRepository:
    """projects 表 CRUD + 会话归属聚合查询。"""

    def __init__(self):
        self.db = get_database()

    def register(self, path: str, now_ms: Optional[int] = None) -> Project:
        """登记（或重新打开）一个项目目录，返回规范化后的项目行。

        Raises:
            OfficePathError: 目录不存在 / 不是目录 / 含 ``..`` 段。
        """
        canonical = validate_workspace(Path(path))
        canonical_str = str(canonical)
        ts = _now_ms(now_ms)
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO projects (id, path, name, created_at, last_opened_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET last_opened_at = excluded.last_opened_at
            """,
            (str(uuid.uuid4()), canonical_str, canonical.name, ts, ts),
        )
        conn.commit()

        row = cursor.execute(
            "SELECT * FROM projects WHERE path = ?", (canonical_str,)
        ).fetchone()
        assert row is not None  # 刚写入
        return _row_to_project(row)

    def get(self, project_id: str) -> Optional[Project]:
        conn = self.db.get_connection()
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return None if row is None else _row_to_project(row)

    def list(self, limit: int = DEFAULT_LIST_LIMIT, offset: int = 0) -> List[Project]:
        conn = self.db.get_connection()
        rows = conn.execute(
            """
            SELECT * FROM projects
            ORDER BY last_opened_at DESC, created_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        return [_row_to_project(row) for row in rows]

    def touch(self, project_id: str, now_ms: Optional[int] = None) -> bool:
        """刷新最近打开时间（不存在返回 False）。"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE projects SET last_opened_at = ? WHERE id = ?",
            (_now_ms(now_ms), project_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    def remove(self, project_id: str) -> bool:
        """从清单移除项目。只删注册行，不动磁盘与任何会话/绑定。"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        conn.commit()
        return cursor.rowcount > 0

    def session_stats(self) -> Dict[str, Tuple[int, Optional[str]]]:
        """按目录聚合活跃绑定：path → (未归档会话数, 最近会话 id)。

        "归属" = ``session_workspace_bindings`` 活跃绑定（revoked_at IS
        NULL）join ``sessions``（is_archived = 0）。每会话至多一条活跃
        绑定，因此 COUNT 即会话数。
        """
        conn = self.db.get_connection()
        rows = conn.execute(
            """
            SELECT b.workspace_path AS path,
                   COUNT(s.id) AS session_count,
                   (
                       SELECT s2.id
                       FROM session_workspace_bindings b2
                       JOIN sessions s2 ON s2.id = b2.session_id AND s2.is_archived = 0
                       WHERE b2.workspace_path = b.workspace_path AND b2.revoked_at IS NULL
                       ORDER BY s2.updated_at DESC, s2.id DESC
                       LIMIT 1
                   ) AS last_session_id
            FROM session_workspace_bindings b
            JOIN sessions s ON s.id = b.session_id AND s.is_archived = 0
            WHERE b.revoked_at IS NULL
            GROUP BY b.workspace_path
            """
        ).fetchall()
        return {
            row["path"]: (int(row["session_count"]),
                          row["last_session_id"] if row["last_session_id"] is not None else None)
            for row in rows
        }

    def sessions_for_project(self, path: str, limit: int = PROJECT_SESSIONS_LIMIT) -> List[Session]:
        """列出归属某项目目录的未归档会话（最近更新优先）。"""
        conn = self.db.get_connection()
        rows = conn.execute(
            """
            SELECT s.* FROM sessions s
            JOIN session_workspace_bindings b ON b.session_id = s.id
            WHERE b.workspace_path = ? AND b.revoked_at IS NULL AND s.is_archived = 0
            ORDER BY s.updated_at DESC, s.id DESC
            LIMIT ?
            """,
            (path, limit),
        ).fetchall()
        return [Session.from_row(row) for row in rows]

    def search(self, query: str, limit: int = 10) -> List[Project]:
        """按名称/路径模糊搜索项目（P7 全局搜索接入，最近打开优先）。

        与 SessionRepository.search 同约定：LIKE 不转义 ``%``/``_``。
        """
        conn = self.db.get_connection()
        pattern = f"%{query}%"
        rows = conn.execute(
            """
            SELECT * FROM projects
            WHERE name LIKE ? OR path LIKE ?
            ORDER BY last_opened_at DESC, id DESC
            LIMIT ?
            """,
            (pattern, pattern, limit),
        ).fetchall()
        return [_row_to_project(row) for row in rows]


def open_project(
    project_id: str, now_ms: Optional[int] = None
) -> Tuple[Project, Session, bool]:
    """打开项目：返回 ``(项目, 会话, 是否新建了会话)``。

    语义对标主流工具"点击最近项目"：目录仍在磁盘上 → 刷新 last_opened_at，
    优先复用该项目最近活跃会话；一个都没有 → 新建会话并绑定到项目目录
    （标题取项目名，会话列表里即可辨识归属）。目录已消失 → 抛
    ``ProjectPathMissingError``，由路由层映射 410，让前端提示移除或重选。
    """
    repo = ProjectRepository()
    project = repo.get(project_id)
    if project is None:
        raise ProjectNotFoundError(f"Project '{project_id}' is not registered")

    try:
        validate_workspace(Path(project.path))
    except OfficePathError as exc:
        raise ProjectPathMissingError(
            f"Project directory is missing on disk: {project.path}"
        ) from exc

    repo.touch(project_id, now_ms)

    existing = repo.sessions_for_project(project.path, limit=1)
    if existing:
        return project, existing[0], False

    session = SessionRepository().create(title=project.name)
    bind_session_workspace(
        get_database().get_connection(), session.id, project.path, now_ms=now_ms
    )
    logger.info("project open: 新建会话 %s 绑定项目 %s", session.id, project.path)
    return project, session, True


def create_session_for_project(
    project_id: str, now_ms: Optional[int] = None
) -> Tuple[Project, Session]:
    """在项目下显式新建一个绑定会话（项目行 hover + 「新建会话」按钮）。

    与 ``open_project`` 的区别：不做「最近活跃会话复用」，永远新建。
    其余语义（目录缺失 → ProjectPathMissingError → 路由层 410、绑定
    工作区、刷新 last_opened_at）与 open_project 同口径。
    """
    repo = ProjectRepository()
    project = repo.get(project_id)
    if project is None:
        raise ProjectNotFoundError(f"Project '{project_id}' is not registered")

    try:
        validate_workspace(Path(project.path))
    except OfficePathError as exc:
        raise ProjectPathMissingError(
            f"Project directory is missing on disk: {project.path}"
        ) from exc

    repo.touch(project_id, now_ms)

    session = SessionRepository().create(title=project.name)
    bind_session_workspace(
        get_database().get_connection(), session.id, project.path, now_ms=now_ms
    )
    logger.info(
        "project create_session: 新建会话 %s 绑定项目 %s", session.id, project.path
    )
    return project, session


def register_quietly(path: str, now_ms: Optional[int] = None) -> Optional[Project]:
    """容错登记：失败记日志返回 None，绝不抛（供跨域写侧联动使用）。

    P6 桥接用——wiki open/create 成功后顺手把目录同步进侧栏项目清单；
    注册表写入失败不应影响 wiki 主流程。
    """
    try:
        return ProjectRepository().register(path, now_ms=now_ms)
    except Exception as exc:  # noqa: BLE001 — 跨域联动失败只降级
        logger.info("project register_quietly skipped for %s: %s", path, exc)
        return None


__all__ = [
    "DEFAULT_LIST_LIMIT",
    "PROJECT_SESSIONS_LIMIT",
    "Project",
    "ProjectNotFoundError",
    "ProjectPathMissingError",
    "ProjectRepository",
    "create_session_for_project",
    "open_project",
    "register_quietly",
]
