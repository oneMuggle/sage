"""技能生命周期（curator）— active/stale/archived 三态分类 + 归档持久化。

设计要点（spec 2026-08-02-skill-curator-lifecycle）
----------------------------------------------------

- **读取时即时计算**：active/stale 是 ``last_used_at`` 与当前时间的纯函数比较，
  不落库、无后台 worker。archived 是用户显式软标记，持久化到 ``skill_lifecycle``
  表（重启不丢）。
- **best-effort**：DB 读写失败只 warning，绝不外抛 —— 策展状态是辅助数据，
  不得影响技能主流程（与 ``SkillUsageStore`` 同契约）。
- **六边形纯净**：不依赖 FastAPI，仅惰性 import ``backend.data.database``。
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional, Set

logger = logging.getLogger(__name__)

# active/stale 分界阈值（默认 30 天）。可通过环境变量覆盖。
DEFAULT_STALE_THRESHOLD_MS = 30 * 24 * 60 * 60 * 1000
STALE_THRESHOLD_ENV = "SAGE_SKILL_STALE_THRESHOLD_MS"


def get_stale_threshold_ms() -> int:
    """读取技能 stale 阈值；无效配置安全回退默认值。"""
    raw = os.environ.get(STALE_THRESHOLD_ENV)
    if raw is None:
        return DEFAULT_STALE_THRESHOLD_MS
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning("Invalid %s=%r; using default", STALE_THRESHOLD_ENV, raw)
        return DEFAULT_STALE_THRESHOLD_MS
    if value < 0:
        logger.warning("Invalid %s=%r; using default", STALE_THRESHOLD_ENV, raw)
        return DEFAULT_STALE_THRESHOLD_MS
    return value

# 生命周期三态
LIFECYCLE_ACTIVE = "active"
LIFECYCLE_STALE = "stale"
LIFECYCLE_ARCHIVED = "archived"


def _now_ms() -> int:
    """当前时间（ms epoch）。"""
    return int(time.time() * 1000)


def classify_lifecycle(
    last_used_at_ms: Optional[int],
    archived: bool,
    now_ms: int,
    stale_threshold_ms: int = DEFAULT_STALE_THRESHOLD_MS,
) -> str:
    """计算技能生命周期态（纯函数，``now_ms`` 由调用方注入便于测试）。

    优先级 ``archived > active/stale``：

    - ``archived=True`` → ``"archived"``
    - ``last_used_at_ms is None``（从未使用，usage 表无行）→ ``"stale"``
    - 距今 ``<= stale_threshold_ms`` → ``"active"``
    - 距今 ``> stale_threshold_ms`` → ``"stale"``
    """
    if archived:
        return LIFECYCLE_ARCHIVED
    if last_used_at_ms is None:
        return LIFECYCLE_STALE
    if (now_ms - last_used_at_ms) <= stale_threshold_ms:
        return LIFECYCLE_ACTIVE
    return LIFECYCLE_STALE


class SkillLifecycleStore:
    """技能策展状态存储（SQLite ``skill_lifecycle`` 表）。best-effort。

    Example:
        >>> store = get_lifecycle_store()
        >>> store.set_archived("travel", True)
        >>> store.is_archived("travel")
        True
        >>> store.get_archived_names()
        {"travel"}
    """

    def __init__(self, db=None) -> None:
        """初始化策展状态存储。

        Args:
            db: Database 实例；缺省用全局 ``get_database()``。
        """
        self.db = db

    def _conn(self):
        """惰性绑定全局 Database 并返回连接（仿 SkillUsageStore）。"""
        if self.db is None:
            from backend.data.database import get_database

            self.db = get_database()
        return self.db.get_connection()

    def set_archived(self, name: str, archived: bool) -> None:
        """UPSERT 归档状态（归档写 ``archived_at``，取消置 NULL）。best-effort。"""
        if not name:
            return
        try:
            conn = self._conn()
            archived_at = _now_ms() if archived else None
            conn.execute(
                "INSERT INTO skill_lifecycle (name, archived, archived_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET "
                "archived = excluded.archived, archived_at = excluded.archived_at",
                (name, 1 if archived else 0, archived_at),
            )
            conn.commit()
        except Exception as exc:  # noqa: BLE001 - best-effort 契约
            logger.warning(f"Skill lifecycle persist failed for {name!r}: {exc}")

    def get_archived_names(self) -> Set[str]:
        """所有已归档技能名集合（批量左连接用，一次查询）。best-effort，失败空集。"""
        try:
            rows = (
                self._conn()
                .execute("SELECT name FROM skill_lifecycle WHERE archived = 1")
                .fetchall()
            )
            return {row["name"] for row in rows}
        except Exception as exc:  # noqa: BLE001 - best-effort 契约
            logger.warning(f"Skill lifecycle read failed: {exc}")
            return set()

    def set_enabled(self, name: str, enabled: bool) -> None:
        """持久化技能开关状态（best-effort，DB 失败只 warning）。"""
        if not name:
            return
        try:
            conn = self._conn()
            conn.execute(
                "INSERT INTO skill_lifecycle (name, enabled, enabled_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET "
                "enabled = excluded.enabled, enabled_at = excluded.enabled_at",
                (name, 1 if enabled else 0, _now_ms()),
            )
            conn.commit()
        except Exception as exc:  # noqa: BLE001 - best-effort 契约
            logger.warning(f"Skill lifecycle persist failed for {name!r}: {exc}")

    def get_disabled_names(self) -> Set[str]:
        """返回显式禁用的技能名集合；未登记技能默认启用。"""
        try:
            rows = (
                self._conn()
                .execute("SELECT name FROM skill_lifecycle WHERE enabled = 0")
                .fetchall()
            )
            return {row["name"] for row in rows}
        except Exception as exc:  # noqa: BLE001 - best-effort 契约
            logger.warning(f"Skill lifecycle read failed: {exc}")
            return set()

    def is_archived(self, name: str) -> bool:
        """单个技能是否已归档。best-effort，失败 False。"""
        try:
            row = (
                self._conn()
                .execute("SELECT archived FROM skill_lifecycle WHERE name = ?", (name,))
                .fetchone()
            )
            return bool(row is not None and row["archived"])
        except Exception as exc:  # noqa: BLE001 - best-effort 契约
            logger.warning(f"Skill lifecycle read failed for {name!r}: {exc}")
            return False


# 全局单例（与 get_usage_store 同模式）
_lifecycle_store: Optional[SkillLifecycleStore] = None


def get_lifecycle_store(db=None) -> SkillLifecycleStore:
    """获取全局 SkillLifecycleStore 单例。"""
    global _lifecycle_store
    if _lifecycle_store is None:
        _lifecycle_store = SkillLifecycleStore(db)
    return _lifecycle_store


def reset_lifecycle_store() -> None:
    """重置 SkillLifecycleStore 单例（仅用于测试）。"""
    global _lifecycle_store
    _lifecycle_store = None
