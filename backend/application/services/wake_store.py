"""WakeStore —— A4 Suspend-Resume 的唤醒记录持久化（SQLite）。

与 OpenWorker ``selfwake.py`` 的 JSON 文件存储不同，Sage 后端已有统一的
SQLite 基础设施（``backend.data.database.Database``，WAL + busy_timeout），
wake 记录直接落在 ``sage.db`` 的 ``wakes`` 表中：

- 进程崩溃 / 重启后挂起的会话仍可被恢复（重启即 catch-up）；
- 与 sessions / messages 同库，未来可做外键级联清理。

线程安全：SQLite 连接 ``check_same_thread=False`` + WAL，写路径用
``threading.Lock`` 串行化（APScheduler 后台线程与 asyncio 事件循环可能
并发访问）。

schema 由本 store 自建（``ensure_schema`` 幂等），不侵入
``Database.init_db`` —— 让该特性可从 backend 整体中独立拆卸。
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Callable, List, Optional

from backend.data.database import Database, get_database
from backend.domain.wake import Wake, WakeKind, WakeState, utc_now_iso

logger = logging.getLogger(__name__)

# 到期扫描上限：单次 tick 最多消费的 wake 数，防止病态堆积饿死其他 tick 工作。
DUE_SCAN_LIMIT = 200


def _row_to_wake(row) -> Wake:
    """sqlite3.Row → Wake 领域对象。"""
    return Wake(
        id=row["id"],
        session_id=row["session_id"],
        kind=WakeKind(row["kind"]),
        state=WakeState(row["state"]),
        fire_at=row["fire_at"],
        job_id=row["job_id"],
        event_key=row["event_key"],
        note=row["note"] or "",
        created_at=row["created_at"],
        fired_at=row["fired_at"],
    )


class WakeStore:
    """``wakes`` 表的仓储（add / due 扫描 / 状态迁移）。"""

    def __init__(self, db: Optional[Database] = None) -> None:
        self.db = db or get_database()
        self._lock = threading.Lock()
        self._ensure_schema()

    # ------------------------------------------------------------------ #
    # schema
    # ------------------------------------------------------------------ #

    def _ensure_schema(self) -> None:
        """幂等建表 + 索引。state/kind 用 CHECK 约束锁定枚举值域。"""
        conn = self.db.get_connection()
        with self._lock:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS wakes (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK (kind IN ('timer', 'completion', 'event')),
                    state TEXT NOT NULL DEFAULT 'pending'
                        CHECK (state IN ('pending', 'due', 'fired')),
                    fire_at TEXT,
                    job_id TEXT,
                    event_key TEXT,
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    fired_at TEXT
                )
                """
            )
            # 到期扫描主索引：(state, fire_at) 覆盖 timer 分支
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_wakes_state_fire_at "
                "ON wakes (state, fire_at)"
            )
            # completion / event 信号反查
            conn.execute("CREATE INDEX IF NOT EXISTS idx_wakes_job_id ON wakes (job_id)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_wakes_event_key ON wakes (event_key)"
            )
            conn.commit()

    # ------------------------------------------------------------------ #
    # 写入
    # ------------------------------------------------------------------ #

    def add_wake(self, wake: Wake) -> Wake:
        """持久化一条 wake 记录，返回原对象（便于链式使用）。

        Raises:
            ValueError: 同 id 重复写入。
        """
        conn = self.db.get_connection()
        with self._lock:
            try:
                conn.execute(
                    """
                    INSERT INTO wakes
                        (id, session_id, kind, state, fire_at, job_id, event_key,
                         note, created_at, fired_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        wake.id,
                        wake.session_id,
                        wake.kind.value,
                        wake.state.value,
                        wake.fire_at,
                        wake.job_id,
                        wake.event_key,
                        wake.note,
                        wake.created_at,
                        wake.fired_at,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"wake id already exists: {wake.id}") from exc
            conn.commit()
        return wake

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #

    def get_wake(self, wake_id: str) -> Optional[Wake]:
        row = (
            self.db.get_connection()
            .execute("SELECT * FROM wakes WHERE id = ?", (wake_id,))
            .fetchone()
        )
        return _row_to_wake(row) if row else None

    def get_due_wakes(
        self, now: Optional[datetime] = None, limit: int = DUE_SCAN_LIMIT
    ) -> List[Wake]:
        """所有到期待消费的 wake。

        到期判定：

        - TIMER：``fire_at <= now`` 且 state 为 pending / due；
        - COMPLETION / EVENT：state 已被外部信号标记为 due。

        ``fire_at`` 统一为 UTC ISO-8601（``+00:00`` 后缀），同格式字符串
        的字典序即时序，可直接在 SQL 中比较。
        """
        now = now or datetime.now(timezone.utc)  # noqa: UP017
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)  # noqa: UP017
        now_iso = now.astimezone(timezone.utc).isoformat()  # noqa: UP017
        rows = (
            self.db.get_connection()
            .execute(
                """
                SELECT * FROM wakes
                WHERE state IN ('pending', 'due')
                  AND (
                    (kind = 'timer' AND fire_at IS NOT NULL AND fire_at <= ?)
                    OR (kind IN ('completion', 'event') AND state = 'due')
                  )
                ORDER BY COALESCE(fire_at, created_at) ASC
                LIMIT ?
                """,
                (now_iso, limit),
            )
            .fetchall()
        )
        return [_row_to_wake(row) for row in rows]

    def pending(self, session_id: Optional[str] = None) -> List[Wake]:
        """所有未消费（pending / due）的 wake，可选按会话过滤。"""
        conn = self.db.get_connection()
        if session_id is None:
            rows = conn.execute(
                "SELECT * FROM wakes WHERE state IN ('pending', 'due') "
                "ORDER BY created_at ASC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM wakes WHERE state IN ('pending', 'due') "
                "AND session_id = ? ORDER BY created_at ASC",
                (session_id,),
            ).fetchall()
        return [_row_to_wake(row) for row in rows]

    # ------------------------------------------------------------------ #
    # 状态迁移
    # ------------------------------------------------------------------ #

    def mark_fired(self, wake_id: str) -> bool:
        """把 wake 标记为 FIRED（终态）。返回是否确实发生了迁移。

        幂等：对已 fired / 不存在的 id 返回 False 而不抛错。
        """
        return self._transition(
            wake_id,
            WakeState.FIRED,
            lambda conn, wid: conn.execute(
                "UPDATE wakes SET state = 'fired', fired_at = ? "
                "WHERE id = ? AND state IN ('pending', 'due')",
                (utc_now_iso(), wid),
            ),
        )

    def complete_job(self, job_id: str) -> List[Wake]:
        """后台任务退出：把它关联的 COMPLETION wakes 标记为 DUE。返回迁移的记录。"""
        return self._mark_due_by(
            "kind = 'completion' AND job_id = ? AND state = 'pending'", (job_id,)
        )

    def fire_event(self, event_key: str) -> List[Wake]:
        """命名事件触发：把它关联的 EVENT wakes 标记为 DUE。返回迁移的记录。"""
        return self._mark_due_by(
            "kind = 'event' AND event_key = ? AND state = 'pending'", (event_key,)
        )

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #

    def _transition(
        self, wake_id: str, target: WakeState, apply_update: Callable
    ) -> bool:
        """通用状态迁移：CAS 式 UPDATE（WHERE 带旧状态），返回是否命中。"""
        conn = self.db.get_connection()
        with self._lock:
            cursor = apply_update(conn, wake_id)
            conn.commit()
        changed = cursor.rowcount > 0
        if changed:
            logger.debug("wake %s → %s", wake_id, target.value)
        return changed

    def _mark_due_by(self, where: str, params: tuple) -> List[Wake]:
        """按条件把 PENDING wakes 批量迁移到 DUE，返回被迁移的记录快照。"""
        conn = self.db.get_connection()
        with self._lock:
            # where 为内部常量片段（kind/state 条件），params 承载全部动态值
            affected = conn.execute(
                f"SELECT * FROM wakes WHERE {where}", params
            ).fetchall()
            if affected:
                conn.execute(f"UPDATE wakes SET state = 'due' WHERE {where}", params)
                conn.commit()
        wakes = [_row_to_wake(row) for row in affected]
        for wake in wakes:
            logger.info(
                "wake %s (session %s) marked due", wake.id, wake.session_id
            )
        return wakes


# --------------------------------------------------------------------------- #
# 模块级单例（与 get_database / get_memory_manager 同款）
# --------------------------------------------------------------------------- #

_wake_store: Optional[WakeStore] = None


def get_wake_store() -> WakeStore:
    """进程级 WakeStore 单例（绑定全局 Database）。"""
    global _wake_store
    if _wake_store is None:
        _wake_store = WakeStore()
    return _wake_store


def reset_wake_store() -> None:
    """丢弃单例（测试用：conftest 每个用例重建临时数据库后必须调用）。"""
    global _wake_store
    _wake_store = None
