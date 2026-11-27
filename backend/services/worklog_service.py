"""工作日志服务（P2）—— 「当天做了什么」的持久化与状态流转。

与 :mod:`backend.services.todo_service` 并列的另一条轨：todos 记「要做的事」，
work_logs 记「已经做了什么」。日报/周报（P3）从这两张表双源聚合。

**状态机**（报告统计只认 ``confirmed``）::

    pending ──confirm──▶ confirmed
       │                    │
       └────dismiss────▶ dismissed ◀────dismiss────┘

``pending`` 是「待确认候选」—— 对话 LLM 抽取的产物，抽取可能误记，所以人工
确认前**绝不进报告**。``confirm`` / ``dismiss`` 都是「置为某状态」的语义，
允许从任意状态迁移（用户可以撤回一条已确认的记录）。

**时间窗约定**：``created_at`` 存本地 ISO8601 字符串（``2026-11-27T14:32:05.123456``），
所以日期边界可以直接用字符串比较 —— ``from`` 含当天整日（``>= 当天 00:00``），
``to`` 含当天整日（``< 次日 00:00``，开区间上界）。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from backend.services.worklog_models import (
    WORKLOG_KINDS,
    WORKLOG_SOURCE_TYPES,
    WORKLOG_STATUSES,
    WorkLog,
    row_to_worklog,
)

# 可通过 ``update_worklog`` 修改的列白名单。
#
# **不含** ``status`` —— 状态迁移只走 ``confirm_worklog`` / ``dismiss_worklog``
# 两个显式端点，避免「编辑正文」意外把一条已忽略的记录改成已确认。
# **不含** ``created_at`` / ``updated_at`` —— 后者由服务自己维护。
_UPDATABLE_FIELDS = frozenset(
    {
        "session_id",
        "content",
        "kind",
        "progress_text",
        "blocker",
        "todo_id",
        "project_id",
        "project_tag",
        "source_type",
        "source_ref",
    }
)

#: 单页最大条数 —— 防止前端忘传 limit 时把整表拉出来。
MAX_PAGE_SIZE = 200

#: 默认单页条数。
DEFAULT_PAGE_SIZE = 50


class WorklogService:
    """工作日志的持久化与状态流转。

    与 ``TodoService`` 一样直接持有一个 ``Database``，每次操作现取连接、
    用完 commit —— 不跨调用持有游标。
    """

    def __init__(self, db: Any) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat()

    @staticmethod
    def _parse_day(value: str) -> datetime:
        """把 ``YYYY-MM-DD``（或更长）解析成当天 00:00 的 ``datetime``。"""
        text = str(value).strip()
        if len(text) < 10:
            raise ValueError(f"invalid date: {value!r} (expected YYYY-MM-DD)")
        try:
            # 日期边界刻意用 naive datetime：``created_at`` 存的是本地 ISO8601
            # （无时区），按本地日历日切窗才与用户直觉一致。
            return datetime.strptime(text[:10], "%Y-%m-%d")  # noqa: DTZ007
        except ValueError as exc:
            raise ValueError(
                f"invalid date: {value!r} (expected YYYY-MM-DD)"
            ) from exc

    @classmethod
    def _day_lower_bound(cls, value: str) -> str:
        """``from`` 的下界 —— 当天 00:00:00（含）。"""
        return cls._parse_day(value).isoformat()

    @classmethod
    def _day_upper_bound(cls, value: str) -> str:
        """``to`` 的开区间上界 —— 次日 00:00:00（不含当天 24 点）。"""
        return (cls._parse_day(value) + timedelta(days=1)).isoformat()

    @staticmethod
    def _validate_enum(name: str, value: str, allowed: Tuple[str, ...]) -> str:
        if value not in allowed:
            raise ValueError(
                f"invalid {name}: {value!r} (expected one of {', '.join(allowed)})"
            )
        return value

    def _assert_todo_exists(self, conn: Any, todo_id: Optional[int]) -> None:
        """外键存在性前置校验 —— 本库 ``PRAGMA foreign_keys=ON``。"""
        if todo_id is None:
            return
        row = conn.execute("SELECT id FROM todos WHERE id = ?", (todo_id,)).fetchone()
        if row is None:
            raise ValueError(f"todo {todo_id} not found")

    def _assert_project_exists(self, conn: Any, project_id: Optional[str]) -> None:
        """外键存在性前置校验 —— 本库 ``PRAGMA foreign_keys=ON``。"""
        if not project_id:
            return
        row = conn.execute(
            "SELECT id FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"project {project_id} not found")

    def _build_filters(
        self,
        *,
        status: Optional[str] = None,
        kind: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        todo_id: Optional[int] = None,
        project_tag: Optional[str] = None,
        session_id: Optional[str] = None,
        confirmed_only: bool = False,
    ) -> Tuple[str, List[Any]]:
        """拼 WHERE 子句与参数。

        ``confirmed_only=True`` 是报告侧的关键开关：只统计已确认的正式记录，
        待确认候选绝不进统计。
        """
        clauses: List[str] = []
        params: List[Any] = []
        if confirmed_only:
            clauses.append("status = 'confirmed'")
        elif status:
            clauses.append("status = ?")
            params.append(self._validate_enum("status", status, WORKLOG_STATUSES))
        if kind:
            clauses.append("kind = ?")
            params.append(self._validate_enum("kind", kind, WORKLOG_KINDS))
        if date_from:
            clauses.append("created_at >= ?")
            params.append(self._day_lower_bound(date_from))
        if date_to:
            clauses.append("created_at < ?")
            params.append(self._day_upper_bound(date_to))
        if todo_id is not None:
            clauses.append("todo_id = ?")
            params.append(todo_id)
        if project_tag:
            clauses.append("project_tag = ?")
            params.append(project_tag)
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        return where, params

    # ------------------------------------------------------------------
    # 写操作
    # ------------------------------------------------------------------

    def create_worklog(
        self,
        content: str,
        kind: str = "progress",
        *,
        session_id: Optional[str] = None,
        progress_text: Optional[str] = None,
        blocker: Optional[str] = None,
        todo_id: Optional[int] = None,
        project_id: Optional[str] = None,
        project_tag: Optional[str] = None,
        source_type: str = "manual",
        source_ref: Optional[str] = None,
        status: str = "pending",
    ) -> WorkLog:
        """新增一条工作日志。

        默认 ``status='pending'`` —— **即便调用方明确知道这条是确定的**
        （手动录入、agent 工具），也先落 ``pending``，由用户在收件箱里确认。
        这是「LLM 抽取可能误记」这条原则的落点：抽取路径与手动路径共用同
        一套确认流程，报告只统计 ``confirmed``。
        """
        text = (content or "").strip()
        if not text:
            raise ValueError("content must not be empty")
        self._validate_enum("kind", kind, WORKLOG_KINDS)
        self._validate_enum("status", status, WORKLOG_STATUSES)
        self._validate_enum("source_type", source_type, WORKLOG_SOURCE_TYPES)

        conn = self.db.get_connection()
        self._assert_todo_exists(conn, todo_id)
        self._assert_project_exists(conn, project_id)

        now = self._now()
        cursor = conn.execute(
            """
            INSERT INTO work_logs (
                session_id, content, kind, progress_text, blocker,
                todo_id, project_id, project_tag,
                source_type, source_ref, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                text,
                kind,
                progress_text,
                blocker,
                todo_id,
                project_id,
                project_tag,
                source_type,
                source_ref,
                status,
                now,
                now,
            ),
        )
        conn.commit()
        return self.get_worklog(int(cursor.lastrowid))

    def update_worklog(self, worklog_id: int, **fields: Any) -> Optional[WorkLog]:
        """更新一条工作日志。

        **键缺席 = 不动该列**，显式传 ``None`` = 清空（与 ``TodoService
        .update_todo`` 同款语义）。白名单外的键静默忽略；``kind`` /
        ``source_type`` 传了非法值会抛 ``ValueError``。
        """
        updates = {k: v for k, v in fields.items() if k in _UPDATABLE_FIELDS}
        if not updates:
            return self.get_worklog(worklog_id)
        if "content" in updates:
            text = (updates["content"] or "").strip()
            if not text:
                raise ValueError("content must not be empty")
            updates["content"] = text
        if "kind" in updates:
            self._validate_enum("kind", updates["kind"], WORKLOG_KINDS)
        if "source_type" in updates:
            self._validate_enum("source_type", updates["source_type"], WORKLOG_SOURCE_TYPES)

        conn = self.db.get_connection()
        if self.get_worklog(worklog_id) is None:
            return None
        self._assert_todo_exists(conn, updates.get("todo_id"))
        self._assert_project_exists(conn, updates.get("project_id"))

        assignments = ", ".join(f"{key} = ?" for key in updates)
        params = list(updates.values())
        params.append(self._now())
        params.append(worklog_id)
        conn.execute(
            f"UPDATE work_logs SET {assignments}, updated_at = ? WHERE id = ?",
            params,
        )
        conn.commit()
        return self.get_worklog(worklog_id)

    def delete_worklog(self, worklog_id: int) -> bool:
        """永久删除一条工作日志。返回是否真的删掉了东西。"""
        conn = self.db.get_connection()
        cursor = conn.execute("DELETE FROM work_logs WHERE id = ?", (worklog_id,))
        conn.commit()
        return cursor.rowcount > 0

    def _set_status(self, worklog_id: int, status: str) -> Optional[WorkLog]:
        conn = self.db.get_connection()
        cursor = conn.execute(
            "UPDATE work_logs SET status = ?, updated_at = ? WHERE id = ?",
            (status, self._now(), worklog_id),
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None
        return self.get_worklog(worklog_id)

    def confirm_worklog(self, worklog_id: int) -> Optional[WorkLog]:
        """``pending`` → ``confirmed``（已确认，进报告统计）。"""
        return self._set_status(worklog_id, "confirmed")

    def dismiss_worklog(self, worklog_id: int) -> Optional[WorkLog]:
        """``pending`` → ``dismissed``（已忽略，不进报告统计）。"""
        return self._set_status(worklog_id, "dismissed")

    # ------------------------------------------------------------------
    # 读操作
    # ------------------------------------------------------------------

    def get_worklog(self, worklog_id: int) -> Optional[WorkLog]:
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM work_logs WHERE id = ?", (worklog_id,)
        ).fetchone()
        if row is None:
            return None
        return row_to_worklog(row)

    def list_worklogs(
        self,
        *,
        status: Optional[str] = None,
        kind: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        todo_id: Optional[int] = None,
        project_tag: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> List[WorkLog]:
        """按时间倒序列出工作日志（最新在前）。

        ``date_from`` / ``date_to`` 含边界当天整日。
        """
        where, params = self._build_filters(
            status=status,
            kind=kind,
            date_from=date_from,
            date_to=date_to,
            todo_id=todo_id,
            project_tag=project_tag,
            session_id=session_id,
        )
        page = max(1, min(int(limit), MAX_PAGE_SIZE))
        offset = max(0, int(offset))
        conn = self.db.get_connection()
        rows = conn.execute(
            f"SELECT * FROM work_logs{where} "
            "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            params + [page, offset],
        ).fetchall()
        return [row_to_worklog(row) for row in rows]

    def count_worklogs(
        self,
        *,
        status: Optional[str] = None,
        kind: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        todo_id: Optional[int] = None,
        project_tag: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> int:
        """同一组筛选条件下的总条数（分页用）。"""
        where, params = self._build_filters(
            status=status,
            kind=kind,
            date_from=date_from,
            date_to=date_to,
            todo_id=todo_id,
            project_tag=project_tag,
            session_id=session_id,
        )
        conn = self.db.get_connection()
        row = conn.execute(
            f"SELECT COUNT(*) AS total FROM work_logs{where}", params
        ).fetchone()
        return int(row["total"]) if row else 0

    def list_pending(self, limit: int = DEFAULT_PAGE_SIZE) -> List[WorkLog]:
        """待确认收件箱 —— ``status='pending'`` 的候选，按时间倒序。"""
        return self.list_worklogs(status="pending", limit=limit)

    def summarize(
        self,
        *,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        todo_id: Optional[int] = None,
        project_tag: Optional[str] = None,
    ) -> Dict[str, Any]:
        """时间窗内的统计快照（**只统计已确认**的记录）。

        返回 ``{"total": int, "by_kind": {...}, "sessions": int}``。
        报告侧（P3）直接吃这份快照 —— 待确认候选不在其中。
        """
        where, params = self._build_filters(
            date_from=date_from,
            date_to=date_to,
            todo_id=todo_id,
            project_tag=project_tag,
            confirmed_only=True,
        )
        conn = self.db.get_connection()
        rows = conn.execute(
            f"SELECT kind, COUNT(*) AS total FROM work_logs{where} GROUP BY kind",
            params,
        ).fetchall()
        by_kind = {kind: 0 for kind in WORKLOG_KINDS}
        for row in rows:
            by_kind[row["kind"]] = int(row["total"])
        session_row = conn.execute(
            f"SELECT COUNT(DISTINCT session_id) AS total FROM work_logs{where}",
            params,
        ).fetchone()
        sessions = int(session_row["total"]) if session_row else 0
        return {
            "total": sum(by_kind.values()),
            "by_kind": by_kind,
            "sessions": sessions,
        }


# ----------------------------------------------------------------------
# 模块级单例（与 todo_service 同款：装配根注入，工具层按需取用）
# ----------------------------------------------------------------------

_global_service: Optional[WorklogService] = None


def get_worklog_service() -> Optional[WorklogService]:
    """Return the process-wide worklog service, if initialised."""
    return _global_service


def init_worklog_service(db: Any) -> WorklogService:
    """Initialise (and register) the process-wide worklog service."""
    global _global_service
    _global_service = WorklogService(db)
    return _global_service
