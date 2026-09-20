"""Hook 执行历史记录 (Phase 6)。

保留最近 7 天 / 最多 1000 条记录 (先到先清)。供设置页诊断面板与
``GET /api/v1/hooks/history`` 端点使用。

字段设计要点:
- ``hook_id`` 是可读标识 (builtin_id / command 截断 / handler / URL), 供 UI 展示;
- ``duration_ms`` 是端到端耗时, 便于识别慢钩子;
- ``stdout_snippet`` / ``stderr_snippet`` 截断到 1KB, 避免膨胀 SQLite。
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from backend.data.database import _SQLITE_LOCK, Database

logger = logging.getLogger(__name__)

SNIPPET_CAP = 1024
MAX_RECORDS = 1000
RETENTION_DAYS = 7


@dataclass
class HookExecutionRecord:
    """单次钩子执行记录。"""

    id: str
    occurred_at: str  # ISO8601
    hook_id: str
    hook_type: str  # "shell" | "python" | "http"
    event: str
    tool_name: str = ""
    decision: str = "allow"
    duration_ms: float = 0.0
    reason: Optional[str] = None
    stdout_snippet: Optional[str] = None
    stderr_snippet: Optional[str] = None
    hook_config_snapshot: Dict[str, Any] = field(default_factory=dict)


def make_record(
    *,
    hook_type: str,
    event: str,
    tool_name: str,
    builtin_id: str = "",
    command: str = "",
    handler: str = "",
    url: str = "",
    decision: str,
    duration_ms: float,
    reason: Optional[str] = None,
    stdout_snippet: Optional[str] = None,
    stderr_snippet: Optional[str] = None,
    hook_config_snapshot: Optional[Dict[str, Any]] = None,
) -> HookExecutionRecord:
    """生成一条可读标识 (hook_id) 与 ISO 时间戳都完备的记录。"""
    if builtin_id:
        hook_id = builtin_id
    elif url:
        hook_id = url
    elif handler:
        hook_id = handler
    else:
        hook_id = command[:64] + ("…" if len(command) > 64 else "")
    return HookExecutionRecord(
        id=str(uuid.uuid4()),
        occurred_at=datetime.now(timezone.utc).isoformat(),  # noqa: UP017 — py3.10 不支持 datetime.UTC
        hook_id=hook_id,
        hook_type=hook_type,
        event=event,
        tool_name=tool_name or "",
        decision=decision,
        duration_ms=duration_ms,
        reason=reason[:512] if reason else None,
        stdout_snippet=(
            stdout_snippet[:SNIPPET_CAP]
            if stdout_snippet and len(stdout_snippet) > SNIPPET_CAP
            else stdout_snippet
        ),
        stderr_snippet=(
            stderr_snippet[:SNIPPET_CAP]
            if stderr_snippet and len(stderr_snippet) > SNIPPET_CAP
            else stderr_snippet
        ),
        hook_config_snapshot=hook_config_snapshot or {},
    )


class HookHistoryRepository:
    """hook_executions 仓储。

    默认单例: ``get_history_repo()`` 返回绑定全局 ``Database`` 的实例。
    """

    def __init__(self, db: Database) -> None:
        self.db = db
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with _SQLITE_LOCK:
            conn = self.db.get_connection()
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS hook_executions (
                    id TEXT PRIMARY KEY,
                    occurred_at TEXT NOT NULL,
                    hook_id TEXT NOT NULL,
                    hook_type TEXT NOT NULL,
                    event TEXT NOT NULL,
                    tool_name TEXT NOT NULL DEFAULT '',
                    decision TEXT NOT NULL,
                    duration_ms REAL NOT NULL DEFAULT 0,
                    reason TEXT,
                    stdout_snippet TEXT,
                    stderr_snippet TEXT,
                    hook_config_snapshot TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_hook_executions_occurred "
                "ON hook_executions(occurred_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_hook_executions_hook_event "
                "ON hook_executions(hook_id, event)"
            )
            conn.commit()

    def save(self, record: HookExecutionRecord) -> None:
        with _SQLITE_LOCK:
            conn = self.db.get_connection()
            conn.execute(
                """
                INSERT INTO hook_executions
                (id, occurred_at, hook_id, hook_type, event, tool_name,
                 decision, duration_ms, reason, stdout_snippet, stderr_snippet,
                 hook_config_snapshot)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.occurred_at,
                    record.hook_id,
                    record.hook_type,
                    record.event,
                    record.tool_name,
                    record.decision,
                    record.duration_ms,
                    record.reason,
                    record.stdout_snippet,
                    record.stderr_snippet,
                    json.dumps(record.hook_config_snapshot, ensure_ascii=False),
                ),
            )
            conn.commit()
        # 异步修剪 —— 失败不影响主流程
        try:
            self._prune()
        except Exception as exc:  # pragma: no cover — 防御性
            logger.debug("hooks: history prune failed: %s", exc)

    def list_records(
        self,
        limit: int = 50,
        hook_id: Optional[str] = None,
        event: Optional[str] = None,
        since: Optional[str] = None,
    ) -> List[HookExecutionRecord]:
        conditions = []
        params: List[Any] = []
        if hook_id:
            conditions.append("hook_id = ?")
            params.append(hook_id)
        if event:
            conditions.append("event = ?")
            params.append(event)
        if since:
            conditions.append("occurred_at >= ?")
            params.append(since)
        where = " AND ".join(conditions)
        where_clause = f"WHERE {where}" if where else ""
        params.append(max(1, min(limit, MAX_RECORDS)))

        with _SQLITE_LOCK:
            conn = self.db.get_connection()
            rows = conn.execute(
                f"""
                SELECT id, occurred_at, hook_id, hook_type, event, tool_name,
                       decision, duration_ms, reason, stdout_snippet,
                       stderr_snippet, hook_config_snapshot
                FROM hook_executions
                {where_clause}
                ORDER BY occurred_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()

        records: List[HookExecutionRecord] = []
        for row in rows:
            try:
                snapshot = json.loads(row[11] or "{}")
            except Exception:
                snapshot = {}
            if not isinstance(snapshot, dict):
                snapshot = {}
            records.append(
                HookExecutionRecord(
                    id=row[0],
                    occurred_at=row[1],
                    hook_id=row[2],
                    hook_type=row[3],
                    event=row[4],
                    tool_name=row[5],
                    decision=row[6],
                    duration_ms=row[7],
                    reason=row[8],
                    stdout_snippet=row[9],
                    stderr_snippet=row[10],
                    hook_config_snapshot=snapshot,
                )
            )
        return records

    def clear(self) -> int:
        """清空历史, 返回删除的行数。"""
        with _SQLITE_LOCK:
            conn = self.db.get_connection()
            cur = conn.execute("DELETE FROM hook_executions")
            conn.commit()
            return cur.rowcount or 0

    def _prune(self) -> None:
        """按时间上限 + 行数上限修剪旧记录。"""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)  # noqa: UP017 — py3.10 不支持 datetime.UTC
        ).isoformat()
        with _SQLITE_LOCK:
            conn = self.db.get_connection()
            conn.execute("DELETE FROM hook_executions WHERE occurred_at < ?", (cutoff,))
            conn.execute(
                """
                DELETE FROM hook_executions
                WHERE id NOT IN (
                    SELECT id FROM hook_executions
                    ORDER BY occurred_at DESC
                    LIMIT ?
                )
                """,
                (MAX_RECORDS,),
            )
            conn.commit()


_repo: Optional[HookHistoryRepository] = None


def get_history_repo() -> HookHistoryRepository:
    """返回绑定全局 Database 的仓储单例。"""
    global _repo
    if _repo is None:
        _repo = HookHistoryRepository(Database())
    return _repo


def reset_history_repo() -> None:
    """重置仓储单例 (测试用)。"""
    global _repo
    _repo = None
