"""后台 shell 注册表的 SQLite 持久化（2026-11-06 Phase 2）。

只持久化「重新附着所需的最小元数据」：pid / pgid / 输出文件路径与身份 /
读取偏移。shell 内部状态（cwd、环境变量）不恢复 —— 重启恢复的是同一个
仍在运行的进程句柄，而不是重放命令。

POSIX-only 语义：pgid 校验依赖 ``os.getpgid``；Windows 上 registry 不会
接入本 store（get_registry 按平台决定）。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

TABLE = "bash_sessions"


@dataclass(frozen=True)
class StoredSessionRecord:
    shell_id: str
    pid: int
    pgid: int
    command: str
    stdout_path: str
    stderr_path: str
    stdout_identity: Optional[Tuple[int, int]]
    stderr_identity: Optional[Tuple[int, int]]
    stdout_offset: int
    stderr_offset: int
    started_at: int


def _identity_to_json(identity: Optional[Tuple[int, int]]) -> Optional[str]:
    if identity is None:
        return None
    return json.dumps([int(identity[0]), int(identity[1])])


def _identity_from_json(raw: Any) -> Optional[Tuple[int, int]]:
    if not raw:
        return None
    try:
        dev, ino = json.loads(raw)
        return (int(dev), int(ino))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


class BashSessionStore:
    """``bash_sessions`` 表的仓储（线程安全）。"""

    def __init__(self, db: Any) -> None:
        self.db = db
        self._lock = threading.Lock()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        conn = self.db.get_connection()
        with self._lock:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {TABLE} (
                    shell_id TEXT PRIMARY KEY,
                    pid INTEGER NOT NULL,
                    pgid INTEGER NOT NULL,
                    command TEXT NOT NULL,
                    stdout_path TEXT NOT NULL,
                    stderr_path TEXT NOT NULL,
                    stdout_identity TEXT,
                    stderr_identity TEXT,
                    stdout_offset INTEGER NOT NULL DEFAULT 0,
                    stderr_offset INTEGER NOT NULL DEFAULT 0,
                    started_at INTEGER NOT NULL
                )
                """
            )
            conn.commit()

    def persist(self, session: Any) -> None:
        """写入 / 覆盖一条 shell 记录。"""
        process = session.process
        pid = int(getattr(process, "pid", 0) or 0)
        pgid = int(getattr(session, "process_group_id", 0) or 0)
        conn = self.db.get_connection()
        with self._lock:
            conn.execute(
                f"""
                INSERT OR REPLACE INTO {TABLE}
                    (shell_id, pid, pgid, command, stdout_path, stderr_path,
                     stdout_identity, stderr_identity, stdout_offset,
                     stderr_offset, started_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.shell_id,
                    pid,
                    pgid,
                    session.command,
                    session.stdout_path,
                    session.stderr_path,
                    _identity_to_json(session.stdout_identity),
                    _identity_to_json(session.stderr_identity),
                    int(session.stdout_offset),
                    int(session.stderr_offset),
                    int(time.time()),
                ),
            )
            conn.commit()

    def remove(self, shell_id: str) -> None:
        conn = self.db.get_connection()
        with self._lock:
            conn.execute(f"DELETE FROM {TABLE} WHERE shell_id = ?", (shell_id,))
            conn.commit()

    def update_offsets(
        self, shell_id: str, stdout_offset: int, stderr_offset: int
    ) -> None:
        conn = self.db.get_connection()
        with self._lock:
            conn.execute(
                f"UPDATE {TABLE} SET stdout_offset = ?, stderr_offset = ? "
                "WHERE shell_id = ?",
                (int(stdout_offset), int(stderr_offset), shell_id),
            )
            conn.commit()

    def list_all(self) -> List[StoredSessionRecord]:
        conn = self.db.get_connection()
        with self._lock:
            rows = conn.execute(
                f"""
                SELECT shell_id, pid, pgid, command, stdout_path, stderr_path,
                       stdout_identity, stderr_identity, stdout_offset,
                       stderr_offset, started_at
                FROM {TABLE}
                """
            ).fetchall()
        return [
            StoredSessionRecord(
                shell_id=str(row[0]),
                pid=int(row[1]),
                pgid=int(row[2]),
                command=str(row[3]),
                stdout_path=str(row[4]),
                stderr_path=str(row[5]),
                stdout_identity=_identity_from_json(row[6]),
                stderr_identity=_identity_from_json(row[7]),
                stdout_offset=int(row[8]),
                stderr_offset=int(row[9]),
                started_at=int(row[10]),
            )
            for row in rows
        ]


_global_store: Optional[BashSessionStore] = None


def get_bash_session_store() -> BashSessionStore:
    """进程级单例（延迟创建；首次调用才触碰数据库）。"""
    global _global_store
    if _global_store is None:
        from backend.data.database import get_database

        _global_store = BashSessionStore(get_database())
    return _global_store


__all__ = [
    "BashSessionStore",
    "StoredSessionRecord",
    "get_bash_session_store",
]
