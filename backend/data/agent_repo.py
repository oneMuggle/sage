"""``AgentRepository`` — AgentProfile 持久化 (PR-3)。

把 ``backend/agents/profiles.py`` 的 dataclass 形态 ``AgentProfile`` 落到
SQLite ``agents`` 表 (见 ``backend/data/database.py:init_db``)。

设计要点
--------

- **JSON 字段**: tools / memory_access / model_config 在 DB 里是 TEXT (JSON 字符串),
  list/dict ↔ JSON 转换在 repo 层做, 上层 (legacy_routes) 直接拿 dict。
- **不耦合 dataclass**: 直接读写原始 dict, 不 import ``AgentProfile``。
  ``profiles.py`` 是默认种子来源, 但运行期数据可与默认分离 (用户改 enabled /
  max_iterations 后, 不回写到 ``profiles.py``)。
- **id 不可变**: update / set_enabled 只动其它字段, 保护默认 agent id 不会
  被前端误改。
- **seed 幂等**: ``seed_defaults_if_empty`` 只在表为空时插, 多次跑安全。

依赖方向
--------
- ``backend.data.database`` (data 层): 拿 Database 单例
- ``backend.agents.profiles`` (应用层): 拿 ``create_default_agents()`` 种子

``agents/`` 子包当前在 ``backend/`` 根下, 不在 ``adapters/out/`` 里 — 这是
项目历史布局, 不强行迁移。
"""

from __future__ import annotations
from typing import Dict, List, Tuple

import json
import time
from typing import Any, Dict, List, Tuple


class AgentRepository:
    """agents 表 CRUD + 种子化。

    所有方法都是同步 (调 SQLite 同步 driver), 调用方在 async 上下文里用
    ``asyncio.to_thread`` 包一层 — 不过本项目 ChatService 是同步风格, 现有
    SessionRepository / MessageRepository 也是同步, 保持一致。
    """

    def __init__(self) -> None:
        # 延迟 import: 避免 data/agent_repo.py 在 import 时触发 backend.main 间接
        from backend.data.database import get_database

        self.db = get_database()

    # ------------------------------------------------------------------ #
    # 读
    # ------------------------------------------------------------------ #

    def list_all(self) -> List[Dict[str, Any]]:
        """列出所有 agent (含 disabled), 按 id 排序。"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM agents ORDER BY id ASC")
        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def get(self, agent_id: str) -> Dict[str, Any] | None:
        """按 id 取单个 agent。"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
        row = cursor.fetchone()
        return self._row_to_dict(row) if row else None

    def count(self) -> int:
        """当前 agent 总数 (供 lifespan seed 判空)。"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM agents")
        return int(cursor.fetchone()[0])

    # ------------------------------------------------------------------ #
    # 写
    # ------------------------------------------------------------------ #

    def upsert(self, profile: Dict[str, Any]) -> None:
        """插入或覆盖一个 agent。 ``updated_at`` 自动写当前毫秒时间戳。"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO agents (
                id, name, role, system_prompt, tools, memory_access,
                model_config, max_iterations, enabled, description, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile["id"],
                profile["name"],
                profile["role"],
                profile.get("system_prompt", ""),
                json.dumps(profile.get("tools", []), ensure_ascii=False),
                json.dumps(profile.get("memory_access", []), ensure_ascii=False),
                json.dumps(profile.get("model_config", {}), ensure_ascii=False),
                int(profile.get("max_iterations", 10)),
                1 if profile.get("enabled", True) else 0,
                profile.get("description", ""),
                int(time.time() * 1000),
            ),
        )
        conn.commit()

    def set_enabled(self, agent_id: str, enabled: bool) -> bool:
        """翻转 enabled 字段。返回 True 当且仅当影响了 1 行。"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE agents SET enabled = ?, updated_at = ? WHERE id = ?",
            (1 if enabled else 0, int(time.time() * 1000), agent_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    def update(self, agent_id: str, profile: Dict[str, Any]) -> bool:
        """部分更新 (PR-4 用)。仅写传入的字段, id 不可改。

        支持字段: name / role / system_prompt / tools / memory_access /
        model_config / max_iterations / enabled / description。
        """
        column_setters: List[Tuple[str, Any]] = []
        for col in (
            "name",
            "role",
            "system_prompt",
            "tools",
            "memory_access",
            "model_config",
            "max_iterations",
            "enabled",
            "description",
        ):
            if col not in profile:
                continue
            value = profile[col]
            if col in ("tools", "memory_access", "model_config") and not isinstance(value, str):
                value = json.dumps(value, ensure_ascii=False)
            elif col == "enabled":
                value = 1 if value else 0
            column_setters.append((col, value))

        if not column_setters:
            return self.get(agent_id) is not None

        set_clause = ", ".join(f"{col} = ?" for col, _ in column_setters) + ", updated_at = ?"
        values: List[Any] = [val for _, val in column_setters]
        values.append(int(time.time() * 1000))
        values.append(agent_id)

        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE agents SET {set_clause} WHERE id = ?",
            values,
        )
        conn.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------ #
    # 种子
    # ------------------------------------------------------------------ #

    def seed_defaults_if_empty(self) -> int:
        """若 agents 表为空, 把 ``create_default_agents()`` 4 个 agent 全量插入。

        返回插入条数 (0 表示表非空, 跳过)。
        """
        if self.count() > 0:
            return 0

        # 延迟 import: profiles.py 在 application 层, 不应在 data 层 eager import
        from backend.agents.profiles import create_default_agents

        for agent in create_default_agents():
            self.upsert(agent.to_dict())
        return self.count()

    # ------------------------------------------------------------------ #
    # 内部辅助
    # ------------------------------------------------------------------ #

    @staticmethod
    def _row_to_dict(row: Any) -> Dict[str, Any]:
        """``sqlite3.Row`` → wire-format dict (与 ``AgentProfile.to_dict()`` 字段对齐)。

        注: ``updated_at`` 在 PR-3 漏返, PR-4 测试 ``test_update_agent_bumps_updated_at``
        显式依赖此字段 (PATCH 后必刷新). 现补上, 不破坏现有调用方.
        """
        return {
            "id": row["id"],
            "name": row["name"],
            "role": row["role"],
            "system_prompt": row["system_prompt"] or "",
            "tools": json.loads(row["tools"]) if row["tools"] else [],
            "memory_access": json.loads(row["memory_access"]) if row["memory_access"] else [],
            "model_config": json.loads(row["model_config"]) if row["model_config"] else {},
            "max_iterations": int(row["max_iterations"]),
            "enabled": bool(row["enabled"]),
            "description": row["description"] or "",
            "updated_at": int(row["updated_at"]),
        }
