"""SkillUsageStore - 技能使用统计持久化（借鉴 hermes-agent .usage.json）

按技能名聚合 ``use_count / success_count / last_used_at``，供技能生命周期
（curator）与前端使用统计使用。registry（``InprocSkillAdapter``）是技能来源
真相，本表只记聚合统计，不定义技能本身。

设计要点
--------

- **best-effort**：DB 写入失败只 warning，绝不抛错 —— 使用统计是辅助数据，
  不得影响技能执行热路径。
- **幂等 UPSERT**：按 ``name`` 主键增量累加。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _now_ms() -> int:
    """当前时间（ms epoch）。"""
    return int(time.time() * 1000)


class SkillUsageStore:
    """技能使用统计存储（SQLite ``skill_usage`` 表）。

    Example:
        >>> store = SkillUsageStore(db)
        >>> store.bump("search", success=True)
        >>> store.get("search")
        {"name": "search", "use_count": 1, "success_count": 1, "last_used_at": ...}
        >>> store.get_all()
        [{"name": "search", "use_count": 1, ...}]
    """

    def __init__(self, db=None) -> None:
        """初始化使用统计存储。

        Args:
            db: Database 实例；缺省用全局 ``get_database()``。
        """
        self.db = db

    def bump(self, name: str, success: bool = True) -> None:
        """技能使用次数 +1（成功时 success_count 同步 +1）。

        best-effort：DB 不可用 / 表不存在时只 warning，不抛错。
        """
        if not name:
            return
        try:
            if self.db is None:
                from backend.data.database import get_database

                self.db = get_database()
            conn = self.db.get_connection()
            now = _now_ms()
            conn.execute(
                "INSERT INTO skill_usage (name, use_count, success_count, last_used_at) "
                "VALUES (?, 1, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET "
                "use_count = use_count + 1, "
                "success_count = success_count + ?, "
                "last_used_at = excluded.last_used_at",
                (name, 1 if success else 0, now, 1 if success else 0),
            )
            conn.commit()
        except Exception as exc:  # noqa: BLE001 - best-effort 契约
            logger.warning(f"Skill usage persist failed for {name!r}: {exc}")

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        """读取单个技能的聚合统计。"""
        try:
            if self.db is None:
                from backend.data.database import get_database

                self.db = get_database()
            row = self.db.get_connection().execute(
                "SELECT name, use_count, success_count, last_used_at "
                "FROM skill_usage WHERE name = ?",
                (name,),
            ).fetchone()
            if row is None:
                return None
            return dict(row)
        except Exception as exc:  # pragma: no cover - 防御性兜底
            logger.warning(f"Skill usage read failed for {name!r}: {exc}")
            return None

    def get_all(self) -> List[Dict[str, Any]]:
        """读取全部技能的聚合统计（按 last_used_at 降序）。"""
        try:
            if self.db is None:
                from backend.data.database import get_database

                self.db = get_database()
            rows = self.db.get_connection().execute(
                "SELECT name, use_count, success_count, last_used_at "
                "FROM skill_usage ORDER BY last_used_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:  # pragma: no cover - 防御性兜底
            logger.warning(f"Skill usage list failed: {exc}")
            return []


# 全局单例（与 get_memory_manager 同模式）
_usage_store: Optional[SkillUsageStore] = None


def get_usage_store(db=None) -> SkillUsageStore:
    """获取全局 SkillUsageStore 单例。"""
    global _usage_store
    if _usage_store is None:
        _usage_store = SkillUsageStore(db)
    return _usage_store


def reset_usage_store() -> None:
    """重置 SkillUsageStore 单例（仅用于测试）。"""
    global _usage_store
    _usage_store = None
