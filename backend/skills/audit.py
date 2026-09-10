"""SkillAuditLog - 技能审计台账 (Round 3, 对标 hermes-agent curator)

append-only 台账: 技能的每次 create/update/archive/restore/rollback 都
落一条不可变记录（含 before/after 快照），支撑:

1. 审计视图 —— ``GET /skills/{name}/audit``（谁在何时改了什么）
2. 单条回滚 —— ``POST /skills/{name}/rollback`` 从最近 before 快照恢复

对标 hermes 的设计动线: 自动写入 + 事后审计 + 一键回滚, 取代
"每次修改都人工事前审批"的阻塞模式, 同时保留 Sage 的透明可控承诺。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: 台账动作（append-only 语义: 记录永不 UPDATE/DELETE）
AUDIT_ACTIONS = (
    "create",
    "update",
    "archive",
    "restore",
    "rollback",
    "consolidation_note",  # Round 5: LLM 巡检建议（只记录，不动文件）
)


class SkillAuditLog:
    """技能审计台账（append-only SQLite 表）

    Args:
        db: Database 实例；缺省用全局 ``get_database()``。
    """

    def __init__(self, db=None) -> None:
        self.db = db

    def _conn(self):
        if self.db is None:
            from backend.data.database import get_database

            self.db = get_database()
        return self.db.get_connection()

    def _ensure_table(self) -> None:
        self._conn().execute(
            """
            CREATE TABLE IF NOT EXISTS skill_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_name TEXT NOT NULL,
                action TEXT NOT NULL,
                actor TEXT NOT NULL DEFAULT 'system',
                before_content TEXT,
                after_content TEXT,
                source TEXT,
                created_at INTEGER NOT NULL
            )
            """
        )
        self._conn().execute(
            "CREATE INDEX IF NOT EXISTS idx_skill_audit_name "
            "ON skill_audit_log(skill_name, created_at)"
        )

    def record(
        self,
        skill_name: str,
        action: str,
        *,
        actor: str = "system",
        before_content: Optional[str] = None,
        after_content: Optional[str] = None,
        source: Optional[str] = None,
    ) -> bool:
        """追加一条审计记录。best-effort: 失败仅告警，不拖垮调用方。

        Args:
            skill_name: 技能名
            action: create/update/archive/restore/rollback
            actor: user（人工操作）/ system（后台自动）
            before_content: 变更前 SKILL.md 全文（回滚数据源）
            after_content: 变更后 SKILL.md 全文
            source: 关联来源（如 draft_id）
        """
        if action not in AUDIT_ACTIONS:
            logger.warning("skill audit: 未知动作 %r，跳过记录", action)
            return False
        try:
            self._ensure_table()
            conn = self._conn()
            conn.execute(
                "INSERT INTO skill_audit_log "
                "(skill_name, action, actor, before_content, after_content, source, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    skill_name,
                    action,
                    actor,
                    before_content,
                    after_content,
                    source,
                    int(time.time() * 1000),
                ),
            )
            conn.commit()
            return True
        except Exception as exc:  # noqa: BLE001 — 审计为旁路, 不拖垮主流程
            logger.warning("skill audit 记录失败 (name=%s): %s", skill_name, exc)
            return False

    def list_entries(
        self, skill_name: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """按技能名（可选）倒序查询台账条目"""
        try:
            self._ensure_table()
            conn = self._conn()
            if skill_name:
                rows = conn.execute(
                    "SELECT id, skill_name, action, actor, source, created_at "
                    "FROM skill_audit_log WHERE skill_name = ? "
                    "ORDER BY created_at DESC, id DESC LIMIT ?",
                    (skill_name, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, skill_name, action, actor, source, created_at "
                    "FROM skill_audit_log "
                    "ORDER BY created_at DESC, id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [
                {
                    "id": r[0],
                    "skill_name": r[1],
                    "action": r[2],
                    "actor": r[3],
                    "source": r[4],
                    "created_at": r[5],
                }
                for r in rows
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("skill audit 查询失败: %s", exc)
            return []

    def latest_before_snapshot(self, skill_name: str) -> Optional[str]:
        """取该技能最近一条带 before_content 的记录（回滚数据源）"""
        try:
            self._ensure_table()
            row = self._conn().execute(
                "SELECT before_content FROM skill_audit_log "
                "WHERE skill_name = ? AND before_content IS NOT NULL "
                "ORDER BY created_at DESC, id DESC LIMIT 1",
                (skill_name,),
            ).fetchone()
            return row[0] if row else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("skill audit 快照查询失败 (name=%s): %s", skill_name, exc)
            return None


# ------------------------------------------------------------------ #
# Global singleton（与 get_lifecycle_store 同模式）
# ------------------------------------------------------------------ #

_skill_audit_log: Optional[SkillAuditLog] = None


def get_skill_audit_log(db=None) -> SkillAuditLog:
    """返回全局 SkillAuditLog 单例"""
    global _skill_audit_log
    if _skill_audit_log is None:
        _skill_audit_log = SkillAuditLog(db=db)
    return _skill_audit_log


def reset_skill_audit_log() -> None:
    """重置单例（测试环境按用例重绑 Database 时调用）"""
    global _skill_audit_log
    _skill_audit_log = None
