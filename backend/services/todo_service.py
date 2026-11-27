"""Todo service — business logic for personal task management"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from backend.services import (
    todo_export,
    todo_filters,
    todo_fts,
    todo_insights,
    todo_models,
    todo_order,
    todo_recurrence,
    todo_stats,
    todo_status,
    todo_tags,
)
from backend.services.todo_models import Todo, dump_reminder_offsets

logger = logging.getLogger(__name__)


def _to_local_naive_iso(value: str) -> str:
    """Normalize an ISO8601 string to naive local time.

    - Naive input: passed through unchanged.
    - Offset-aware input: converted to local time and the tzinfo is dropped.
    - ``...Z`` suffix: accepted (canonical ``Date.toISOString()`` output; py3.10
      ``datetime.fromisoformat`` does not parse it natively, so we rewrite it
      to ``+00:00`` first — this matches the project convention in
      ``backend/model_catalog/schemas.py:146``).
    """
    normalized = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt.isoformat()


# Columns ``update_todo`` is allowed to write. Used to build the SET clause, so
# it doubles as the SQL-identifier whitelist — no caller-supplied key ever
# reaches the query unvalidated.
# ``sort_order`` 刻意不在此列：手工次序只能由 ``POST /todos/{id}/move`` 改写，
# 走普通 PUT 会绕过同层合法性校验。
_UPDATABLE_FIELDS = frozenset(
    {
        "title",
        "description",
        "due_at",
        "priority",
        "project_tag",
        "status",
        "recurrence_rule",
        "parent_id",
        "tags",
        "reminder_offsets",
        "specialist_id",
    }
)


class TodoService:
    """Business logic for todo management"""

    def __init__(self, db):
        self.db = db

    def create_todo(
        self,
        title: str,
        description: Optional[str] = None,
        due_at: Optional[str] = None,
        priority: str = "medium",
        project_tag: Optional[str] = None,
        recurrence_rule: Optional[str] = None,
        parent_id: Optional[int] = None,
        tags: Optional[List[str]] = None,
        reminder_offsets: Optional[List[int]] = None,
        source_type: Optional[str] = None,
        source_ref: Optional[str] = None,
        specialist_id: Optional[str] = None,
    ) -> Todo:
        """Create a new todo and return the persisted row.

        ``parent_id`` 将新行挂到父待办下（最多两级）：父行必须存在且本身是顶层。
        ``tags`` 为多标签（去重、上限 10 个、单标签 ≤32 字符）。
        """
        now = datetime.now().isoformat()
        is_recurring = 1 if recurrence_rule else 0

        if parent_id is not None:
            parent = self.get_todo(parent_id)
            if parent is None:
                raise ValueError(f"parent todo {parent_id} not found")
            if parent.parent_id is not None:
                raise ValueError("subtask depth exceeds 2 levels")

        # Auto-link project
        project_id = self._auto_link_project(project_tag) if project_tag else None

        # Normalize due_at: naive pass-through, tz-aware → naive local
        if due_at is not None:
            due_at = _to_local_naive_iso(due_at)

        conn = self.db.get_connection()
        # 新待办追加到所在层末尾（手工次序；P1 拖拽排序）。
        sort_order = todo_order.next_sort_order(conn, parent_id)
        cursor = conn.execute(
            """INSERT INTO todos
               (title, description, due_at, priority, project_tag, project_id,
                tags, reminder_offsets, source_type, source_ref, specialist_id,
                is_recurring, recurrence_rule, parent_id, sort_order,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, description, due_at, priority, project_tag, project_id,
             todo_tags.dump_tags(tags), dump_reminder_offsets(reminder_offsets),
             source_type, source_ref, specialist_id, is_recurring,
             recurrence_rule, parent_id, sort_order, now, now)
        )
        todo_id = cursor.lastrowid
        conn.commit()

        created = self.get_todo(todo_id)
        if created is None:
            raise RuntimeError(f"todo {todo_id} vanished immediately after insert")
        todo_fts.upsert_todo_fts(
            self.db, created.id, created.title, created.description
        )
        return created

    def get_todo(self, todo_id: int) -> Optional[Todo]:
        """Get todo by ID, or None if it does not exist."""
        conn = self.db.get_connection()
        cursor = conn.execute(
            "SELECT * FROM todos WHERE id = ?", (todo_id,)
        )
        row = cursor.fetchone()

        if row is None:
            return None

        return self._row_to_todo(row)

    def list_todos(
        self,
        status: Optional[str] = None,
        project_tag: Optional[str] = None,
        priority: Optional[str] = None,
        include_completed: bool = False,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "due_at",
        sort_order: str = "asc",
        q: Optional[str] = None,
        tag: Optional[str] = None,
        view: Optional[str] = None,
        specialist_id: Optional[str] = None,
    ) -> List[Todo]:
        """List todos with optional filters.

        ``q`` 为全文搜索关键词（标题/描述），FTS5 优先、LIKE 降级。
        ``tag`` 为多标签精确过滤；``view`` 为智能视图（all/today/week/completed）。

        ``sort_by`` is a dict-key lookup into ``_SORT_EXPRS`` — no caller-
        supplied string reaches SQL as an identifier.  An unsupported key
        raises :class:`KeyError`; the router validates before this is
        reachable (see ``todo_router.py``).  ``sort_order`` collapses
        everything that is not ``"desc"`` to ``ASC`` — also validated by
        the router.

        Sorting happens **before** ``LIMIT``/``OFFSET``.
        """
        query = "SELECT * FROM todos WHERE 1=1"
        params: List[Any] = []

        query, params = todo_filters.apply_common_filters(
            query,
            params,
            status=status,
            project_tag=project_tag,
            priority=priority,
            include_completed=include_completed,
            tag=tag,
            view=view,
            specialist_id=specialist_id,
        )

        query, params = todo_fts.apply_search_filter(self.db, query, params, q)

        sort_expr = todo_filters.sort_expression(sort_by, sort_order)
        query += f" ORDER BY {sort_expr} LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        conn = self.db.get_connection()
        cursor = conn.execute(query, params)
        rows = cursor.fetchall()

        return [self._row_to_todo(row) for row in rows]

    def count_todos(
        self,
        status: Optional[str] = None,
        project_tag: Optional[str] = None,
        priority: Optional[str] = None,
        include_completed: bool = False,
        q: Optional[str] = None,
        tag: Optional[str] = None,
        view: Optional[str] = None,
        specialist_id: Optional[str] = None,
    ) -> int:
        """Count todos matching the same filters list_todos applies.

        Both share :meth:`_apply_common_filters` — if they ever diverged,
        ``total`` would stop being the match count and clients would render
        wrong pagination.
        """
        query = "SELECT COUNT(*) FROM todos WHERE 1=1"
        params: List[Any] = []

        query, params = todo_filters.apply_common_filters(
            query,
            params,
            status=status,
            project_tag=project_tag,
            priority=priority,
            include_completed=include_completed,
            tag=tag,
            view=view,
            specialist_id=specialist_id,
        )

        query, params = todo_fts.apply_search_filter(self.db, query, params, q)

        conn = self.db.get_connection()
        return int(conn.execute(query, params).fetchone()[0])

    def list_tags(self) -> List[Dict[str, Any]]:
        """聚合全部待办的多标签及使用次数（实现见 todo_tags）。"""
        return todo_tags.aggregate_from_db(self.db)

    def update_todo(self, todo_id: int, **fields) -> Optional[Todo]:
        """Update todo fields.

        * Key **absent** from ``fields``: column is untouched.
        * Key present with a non-``None`` value: column is set to that value.
        * Key present with an explicit ``None``: nullable column is cleared.
        * ``title`` cannot be cleared (``NOT NULL`` in the schema); explicit
          ``None`` raises :class:`ValueError` rather than an opaque SQL error.

        Returns ``None`` if ``todo_id`` does not exist.
        """
        updates = {k: v for k, v in fields.items() if k in _UPDATABLE_FIELDS}

        # ``title`` is NOT NULL in the schema — reject ``None`` explicitly so
        # callers see a clear Python-level error instead of a SQLite
        # ``IntegrityError`` from deep in the stack.
        if updates.get("title") is None and "title" in updates:
            raise ValueError("title is NOT NULL and cannot be cleared")

        # parent_id 变更校验：禁止自引用、只允许挂在顶层行下、有子任务的行
        # 不能变成子任务（否则形成三级层级）。显式 None 允许清除父子关系。
        parent_changed = False
        if "parent_id" in updates:
            new_parent_id = updates["parent_id"]
            if new_parent_id is not None:
                if new_parent_id == todo_id:
                    raise ValueError("a todo cannot be its own parent")
                parent = self.get_todo(new_parent_id)
                if parent is None:
                    raise ValueError(f"parent todo {new_parent_id} not found")
                if parent.parent_id is not None:
                    raise ValueError("subtask depth exceeds 2 levels")
                conn = self.db.get_connection()
                has_children = conn.execute(
                    "SELECT 1 FROM todos WHERE parent_id = ? LIMIT 1", (todo_id,)
                ).fetchone()
                if has_children is not None:
                    raise ValueError("a todo with subtasks cannot become a subtask")
            # 换父级（含显式置空回到顶层）要重算手工次序 ——
            # ``sort_order`` 是「同层内」的相对值，跨层没有意义。
            current = self.get_todo(todo_id)
            if current is not None and current.parent_id != new_parent_id:
                parent_changed = True

        if not updates:
            return self.get_todo(todo_id)

        # 换父级 → 重算手工次序。``sort_order`` 是「同层内」的相对值，
        # 跨层沿用旧值会让新层出现空洞或与既有行撞值，所以落到新层末尾。
        # （调用方不能直接写这一列 —— 它不在 ``_UPDATABLE_FIELDS`` 里。）
        if parent_changed:
            updates["sort_order"] = todo_order.next_sort_order(
                self.db.get_connection(),
                updates["parent_id"],
                exclude_id=todo_id,
            )

        # Auto-link / clear project when project_tag changed (None clears both)
        if "project_tag" in updates:
            project_tag = updates["project_tag"]
            updates["project_id"] = (
                self._auto_link_project(project_tag) if project_tag else None
            )

        # 多标签：清洗后序列化；显式 None / 空列表都清空为 NULL。
        if "tags" in updates:
            updates["tags"] = todo_tags.dump_tags(updates["tags"])

        # 自定义提醒档位：清洗后序列化；任何改动都清空已触发书签。
        if "reminder_offsets" in updates:
            updates["reminder_offsets"] = dump_reminder_offsets(
                updates["reminder_offsets"]
            )
        if (
            "reminder_offsets" in updates
            or "due_at" in updates
            or "status" in updates
        ):
            updates["reminder_fired_offsets"] = None

        # Normalize due_at: naive pass-through, tz-aware → naive local
        if updates.get("due_at") is not None:
            updates["due_at"] = _to_local_naive_iso(updates["due_at"])

        # 状态变更同步 completed_at：完成态打戳，其余态（含重开一条已完成的
        # 待办）清空。该列不在 ``_UPDATABLE_FIELDS`` 里 —— 调用方不能直接写
        # 它，``todo_status`` 是唯一入口。
        todo_status.apply_completion_stamp(updates, datetime.now())

        # A new due_at or status redefines this todo's reminder schedule, so
        # both latches reset — otherwise a rescheduled or reopened todo would
        # never remind again. The keys below are literal Python strings, not
        # caller input.
        if "due_at" in updates or "status" in updates:
            updates["reminder_24h_fired"] = 0
            updates["reminder_1h_fired"] = 0

        updates["updated_at"] = datetime.now().isoformat()

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [todo_id]

        conn = self.db.get_connection()
        conn.execute(
            f"UPDATE todos SET {set_clause} WHERE id = ?", values
        )
        conn.commit()

        updated = self.get_todo(todo_id)
        if updated is not None and ("title" in updates or "description" in updates):
            todo_fts.upsert_todo_fts(
                self.db, updated.id, updated.title, updated.description
            )
        return updated

    def move_todo(
        self,
        todo_id: int,
        position: str,
        reference_id: Optional[int] = None,
        target_parent_id: Any = todo_order.INHERIT,
    ) -> Optional[Dict[str, Any]]:
        """移动待办：同层排序 / 拖拽成子任务（P1 拖拽排序与嵌套）。

        ``position`` 为 ``before`` / ``after``，相对 ``reference_id`` 落位；
        ``reference_id`` 为 ``None`` 时追加到目标层末尾。
        ``target_parent_id`` 省略（``todo_order.INHERIT``）时目标层跟随参照待办
        所在层，参照也没给时落到顶层末尾；显式给 ``None`` 表示强制回顶层。

        返回 ``{"todo": Todo, "affected": int}``；待办不存在时返回 ``None``。
        非法移动（层级超限 / 自我嵌套 / 参照物不同层）抛 :class:`ValueError`；
        合法性校验全部前置，抛错时数据库没被动过。
        """
        conn = self.db.get_connection()
        if conn.execute(
            "SELECT 1 FROM todos WHERE id = ?", (todo_id,)
        ).fetchone() is None:
            return None
        affected, _ = todo_order.move(
            conn,
            todo_id,
            position,
            reference_id=reference_id,
            target_parent_id=target_parent_id,
            now=datetime.now().isoformat(),
        )
        conn.commit()
        todo = self.get_todo(todo_id)
        if todo is None:  # pragma: no cover - 移动后行被并发删除（极端竞态）
            raise RuntimeError(f"todo {todo_id} vanished immediately after move")
        return {"todo": todo, "affected": affected}

    def delete_todo(self, todo_id: int) -> bool:
        """Delete todo by ID. Returns True if a row was removed."""
        conn = self.db.get_connection()
        cursor = conn.execute(
            "DELETE FROM todos WHERE id = ?", (todo_id,)
        )
        deleted = cursor.rowcount > 0
        conn.commit()
        if deleted:
            todo_fts.delete_todo_fts(self.db, todo_id)
        return deleted

    # --- state changes ---

    def complete_todo(self, todo_id: int) -> Optional[Todo]:
        """Mark a todo as completed.

        Sets ``status='completed'`` and stamps ``completed_at`` and
        ``updated_at`` to the current local time. Returns the refreshed
        :class:`Todo`, or ``None`` if ``todo_id`` does not exist (mirrors
        :meth:`update_todo` semantics).

        循环待办（``recurrence_rule`` 为 5 字段 cron）在完成时自动创建下一
        实例；cron 非法不影响本次完成（fail-open，仅告警）。
        """
        existing = self.get_todo(todo_id)
        if existing is None:
            return None

        now = datetime.now()
        now_iso = now.isoformat()
        conn = self.db.get_connection()
        conn.execute(
            "UPDATE todos SET status = 'completed', completed_at = ?, "
            "updated_at = ? WHERE id = ?",
            (now_iso, now_iso, todo_id),
        )
        conn.commit()
        todo_recurrence.spawn_next_recurrence(self.create_todo, existing, now)
        return self.get_todo(todo_id)

    def cancel_todo(self, todo_id: int) -> bool:
        """Mark a todo as cancelled. Returns True if a row was updated."""
        now = datetime.now().isoformat()
        conn = self.db.get_connection()
        cursor = conn.execute(
            "UPDATE todos SET status = 'cancelled', updated_at = ? "
            "WHERE id = ?",
            (now, todo_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    # --- urgency ---

    @staticmethod
    def _compute_urgency(due_at_str: Optional[str], priority: str,
                         now: datetime) -> str:
        """Return the effective_urgency value for a single todo row.

        Rules:
        - ``due_at`` NULL → ``"normal"``.
        - ``hours_until_due < 1`` → ``"critical"``.
        - ``hours_until_due < 24`` → ``"urgent"``.
        - else → ``"normal"``.
        - Upgrade: ``priority == "high"`` and ``hours_until_due < 24`` →
          ``"critical"``.
        """
        if not due_at_str:
            return "normal"

        due_at = datetime.fromisoformat(due_at_str)
        hours_until_due = (due_at - now).total_seconds() / 3600

        if hours_until_due < 1:
            urgency = "critical"
        elif hours_until_due < 24:
            urgency = "urgent"
        else:
            urgency = "normal"

        if priority == "high" and hours_until_due < 24:
            urgency = "critical"

        return urgency

    def refresh_effective_urgency(self) -> int:
        """Recalculate ``effective_urgency`` for all pending/in_progress todos.

        Returns the number of rows updated.
        """
        now = datetime.now()
        now_iso = now.isoformat()

        conn = self.db.get_connection()
        cursor = conn.execute(
            "SELECT id, due_at, priority FROM todos "
            "WHERE status IN ('pending', 'in_progress')"
        )
        rows = cursor.fetchall()

        for row in rows:
            urgency = self._compute_urgency(row["due_at"], row["priority"], now)
            conn.execute(
                "UPDATE todos SET effective_urgency = ?, updated_at = ? "
                "WHERE id = ?",
                (urgency, now_iso, row["id"]),
            )

        conn.commit()
        return len(rows)

    # --- query helpers ---

    def get_due_soon_todos(self, within_seconds: int) -> List[Todo]:
        """Pending/in_progress todos due within ``within_seconds`` from now.

        Past-due items are excluded — those belong to :meth:`get_overdue_todos`.
        """
        now = datetime.now()
        cutoff = now + timedelta(seconds=within_seconds)

        conn = self.db.get_connection()
        cursor = conn.execute(
            "SELECT * FROM todos "
            "WHERE status IN ('pending', 'in_progress') "
            "AND due_at IS NOT NULL "
            "AND due_at > ? AND due_at <= ? "
            "ORDER BY due_at ASC",
            (now.isoformat(), cutoff.isoformat()),
        )
        rows = cursor.fetchall()

        return [self._row_to_todo(row) for row in rows]

    def get_overdue_todos(self) -> List[Todo]:
        """Pending/in_progress todos past their due_at."""
        now = datetime.now().isoformat()

        conn = self.db.get_connection()
        cursor = conn.execute(
            "SELECT * FROM todos "
            "WHERE status IN ('pending', 'in_progress') "
            "AND due_at IS NOT NULL AND due_at < ? "
            "ORDER BY due_at ASC",
            (now,),
        )
        rows = cursor.fetchall()

        return [self._row_to_todo(row) for row in rows]

    # --- reminder bookkeeping ---
    #
    # The ``reminder_*_fired`` columns are one-shot latches: a reminder is
    # sent at most once per todo per horizon. ``TodoReminderScheduler``
    # owns the *when*; this service owns the *columns*. Writes here do
    # **not** bump ``updated_at`` — they are bookkeeping, not content
    # changes.

    def get_unfired_24h_reminders(self) -> List[Todo]:
        """Pending/in_progress todos due within 24 h whose 24 h latch is 0."""
        now = datetime.now()
        cutoff = now + timedelta(hours=24)
        conn = self.db.get_connection()
        cursor = conn.execute(
            "SELECT * FROM todos "
            "WHERE status IN ('pending', 'in_progress') "
            "AND due_at IS NOT NULL "
            "AND due_at > ? AND due_at <= ? "
            "AND reminder_24h_fired = 0 "
            "ORDER BY due_at ASC",
            (now.isoformat(), cutoff.isoformat()),
        )
        return [self._row_to_todo(r) for r in cursor.fetchall()]

    def mark_24h_fired(self, todo_id: int) -> None:
        """Latch the 24 h reminder. Does not bump ``updated_at``."""
        conn = self.db.get_connection()
        conn.execute(
            "UPDATE todos SET reminder_24h_fired = 1 WHERE id = ?",
            (todo_id,),
        )
        conn.commit()

    def get_unfired_1h_reminders(self) -> List[Todo]:
        """Pending/in_progress todos due within 1 h whose 1 h latch is 0."""
        now = datetime.now()
        cutoff = now + timedelta(hours=1)
        conn = self.db.get_connection()
        cursor = conn.execute(
            "SELECT * FROM todos "
            "WHERE status IN ('pending', 'in_progress') "
            "AND due_at IS NOT NULL "
            "AND due_at > ? AND due_at <= ? "
            "AND reminder_1h_fired = 0 "
            "ORDER BY due_at ASC",
            (now.isoformat(), cutoff.isoformat()),
        )
        return [self._row_to_todo(r) for r in cursor.fetchall()]

    def mark_1h_fired(self, todo_id: int) -> None:
        """Latch the 1 h reminder. Does not bump ``updated_at``."""
        conn = self.db.get_connection()
        conn.execute(
            "UPDATE todos SET reminder_1h_fired = 1 WHERE id = ?",
            (todo_id,),
        )
        conn.commit()

    # --- custom reminder offsets (阶段 1b) ---

    def get_custom_reminder_candidates(self) -> List[Todo]:
        """未完成、未到期且配置了自定义提醒档位的待办。"""
        now_iso = datetime.now().isoformat()
        conn = self.db.get_connection()
        rows = conn.execute(
            "SELECT * FROM todos "
            "WHERE status IN ('pending', 'in_progress') "
            "AND due_at IS NOT NULL AND due_at > ? "
            "AND reminder_offsets IS NOT NULL "
            "ORDER BY due_at ASC",
            (now_iso,),
        ).fetchall()
        return [self._row_to_todo(r) for r in rows]

    def get_fired_reminder_offsets(self, todo_id: int) -> List[int]:
        """该待办已触发的自定义提醒档位（分钟）。"""
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT reminder_fired_offsets FROM todos WHERE id = ?", (todo_id,)
        ).fetchone()
        if row is None or not row[0]:
            return []
        try:
            parsed = json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            return []
        return [int(v) for v in parsed] if isinstance(parsed, list) else []

    def mark_custom_reminder_fired(self, todo_id: int, offset: int) -> None:
        """记录某档位已触发（不碰 updated_at —— 书签不是内容变更）。"""
        fired = self.get_fired_reminder_offsets(todo_id)
        if offset in fired:
            return
        fired.append(offset)
        conn = self.db.get_connection()
        conn.execute(
            "UPDATE todos SET reminder_fired_offsets = ? WHERE id = ?",
            (json.dumps(fired), todo_id),
        )
        conn.commit()

    # --- snooze（阶段 3） ---

    def snooze_todo(self, todo_id: int, minutes: int) -> Optional[Todo]:
        """推迟提醒（实现见 todo_insights.snooze_todo）。"""
        return todo_insights.snooze_todo(self, todo_id, minutes)

    def get_startup_summary(self) -> dict:
        """启动摘要（逾期/今日/未来 7 天/高优先级/计数）。口径见 todo_stats。"""
        return todo_stats.startup_summary(self.db, self._row_to_todo)

    def completion_heatmap(self, days: int = 91) -> Dict[str, Any]:
        """完成热力图（按日聚合，见 todo_stats.completion_heatmap）。"""
        return todo_stats.completion_heatmap(self.db, days)

    def get_most_snoozed(self, limit: int = 5) -> List[Todo]:
        """被推迟次数最多的未完成待办（实现见 todo_insights.most_snoozed）。"""
        return todo_insights.most_snoozed(self.db, self._row_to_todo, limit)

    def get_todo_stats(self) -> dict:
        """统计端点（总数/状态分布/优先级分布/逾期/今日到期/今日完成）。"""
        return todo_stats.todo_stats(self.db)

    # --- batch operations ---

    def create_many(self, items: List[Dict[str, Any]]) -> List[Todo]:
        """批量创建（对话提炼确认后使用）。单条失败中断并抛出，交由调用方处理。"""
        return [self.create_todo(**item) for item in items]

    def complete_many(self, ids: List[int]) -> Dict[str, Any]:
        """批量完成。返回 ``{completed, missing}``；缺失 id 不影响其余行。"""
        completed = 0
        missing: List[int] = []
        for todo_id in ids:
            if self.complete_todo(todo_id) is None:
                missing.append(todo_id)
            else:
                completed += 1
        return {"completed": completed, "missing": missing}

    def delete_many(self, ids: List[int]) -> int:
        """批量删除，返回实际删除行数。"""
        deleted = 0
        for todo_id in ids:
            if self.delete_todo(todo_id):
                deleted += 1
        return deleted

    # --- export ---

    def export_todos(self, include_completed: bool, fmt: str) -> Dict[str, str]:
        """导出为 JSON / Markdown。返回 ``{filename, format, content}``。"""
        todos = self.list_todos(
            status="all" if include_completed else None,
            include_completed=include_completed,
            limit=1000000,
            sort_by="due_at",
            sort_order="asc",
        )
        return todo_export.build_export(todos, fmt)

    def _auto_link_project(self, project_tag: str) -> Optional[str]:
        """Auto-link project_tag to a ``projects`` row, returning its TEXT id."""
        if not project_tag:
            return None

        conn = self.db.get_connection()

        # Exact match first
        cursor = conn.execute(
            "SELECT id FROM projects WHERE name = ? LIMIT 1",
            (project_tag,)
        )
        row = cursor.fetchone()

        if row:
            return row["id"]

        # Fuzzy match (LIKE)
        cursor = conn.execute(
            "SELECT id FROM projects WHERE name LIKE ? LIMIT 1",
            (f"%{project_tag}%",)
        )
        row = cursor.fetchone()

        return row["id"] if row else None

    def _row_to_todo(self, row) -> Todo:
        """Convert a ``todos`` row to a Todo model.

        映射逻辑搬到 ``backend.services.todo_models.row_to_todo``；这里保留
        这个方法是因为它作为回调被传给 ``todo_stats`` / ``todo_insights``。
        """
        return todo_models.row_to_todo(row)


# ---------- process-wide singleton ----------

_global_service: Optional[TodoService] = None


def get_todo_service() -> Optional[TodoService]:
    """Return the process-wide TodoService if it has been initialised."""
    return _global_service


def init_todo_service(db: Any) -> TodoService:
    """Initialise the global service. Must be called once during app startup."""
    global _global_service
    _global_service = TodoService(db)
    return _global_service
