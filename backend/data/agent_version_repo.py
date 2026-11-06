# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""``AgentVersionRepository`` — 专家人设版本快照仓储 (M4-T3)。

存什么
------
每次专家 profile 写入（create / update / rollback）时落一行完整 profile JSON，
以 ``(agent_id, version)`` 为主键。``reason`` 标记快照来源（``create`` /
``update`` / ``rollback``），方便前端列表区分颜色/图标。

何时写
------
- ``POST /agents`` 创建成功 → ``reason=create``、``version=profile.version``
- ``PATCH /agents/{id}`` 成功且版本号变化 → ``reason=update``、``version=新值``
  （PATCH 前先幂等存一份旧版本，保证 ``version=1`` 也有快照可回滚）
- ``POST /agents/{id}/rollback`` 成功 → ``reason=rollback``、``version=新值``

保留策略
--------
每个专家默认保留最近 50 个版本；snapshot 后自动调用 :meth:`prune`，按 version
升序删旧。单行只多一行 JSON 文本（几 KB），开销低。

读与比对
--------
- :meth:`list_versions` 按 version DESC 返回 ``[{version, reason, created_at}]``
- :meth:`read_version` 取完整 profile dict
- :meth:`diff` 白名单字段级比对，返回 ``[{field, before, after}]``
  （白名单：name / role / system_prompt / description / permission_mode /
  source / max_iterations / enabled / version / tools / memory_access /
  skills / knowledge_bindings / memory_policy / persona_ui / model_config）
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from backend.data.database import get_database

logger = logging.getLogger(__name__)

#: 默认每专家保留的最多版本数。超过后按 version 升序裁剪。
DEFAULT_VERSION_CAP = 50

#: diff 比对的字段白名单。未列入的字段（如 updated_at）不呈现给前端。
DIFF_FIELD_WHITELIST: tuple = (
    "name",
    "role",
    "system_prompt",
    "description",
    "permission_mode",
    "source",
    "max_iterations",
    "enabled",
    "version",
    "tools",
    "memory_access",
    "skills",
    "knowledge_bindings",
    "memory_policy",
    "persona_ui",
    "model_config",
)


def _normalize_for_diff(value: Any) -> Any:
    """把 dict/list 规整为规范化形式，便于稳定比对。

    list 排序后再比（顺序变化也算 diff，但重复/乱序不算），dict 按 key 排序
    输出 list[tuple]。None / 基础类型直出。
    """
    if isinstance(value, list):
        try:
            return sorted((_normalize_for_diff(v) for v in value), key=lambda x: str(x))
        except TypeError:
            return [_normalize_for_diff(v) for v in value]
    if isinstance(value, dict):
        return [[k, _normalize_for_diff(value[k])] for k in sorted(value.keys())]
    return value


class AgentVersionRepository:
    """专家人设快照仓储。"""

    # ------------------------------------------------------------------ #
    # 写
    # ------------------------------------------------------------------ #

    def snapshot(
        self,
        agent_id: str,
        profile: Dict[str, Any],
        reason: str = "update",
        cap: int = DEFAULT_VERSION_CAP,
        overwrite: bool = True,
    ) -> int:
        """写入一个快照，返回实际写入的 version。

        :param agent_id: 专家 id（必须在 agents 表存在，本方法不做外键校验）
        :param profile: 完整 profile dict（与 ``agents`` 表行形态一致）
        :param reason: ``create`` / ``update`` / ``rollback``
        :param cap: 保留上限，默认 50
        :param overwrite: True（默认）= 同 version 覆盖；False = 已存在则保留
            原行（PATCH 前的回填钩子用 False，避免 clobber 原始的
            ``reason='create'`` 记录）
        :return: 写入的 version 号
        :raises ValueError: version 字段缺失或非正整数
        """
        version = profile.get("version")
        if version is None or int(version) <= 0:
            raise ValueError(
                f"profile.version 缺失或非正整数: {version!r} (agent={agent_id})"
            )
        version = int(version)

        verb = "INSERT OR REPLACE" if overwrite else "INSERT OR IGNORE"
        conn = get_database().get_connection()
        conn.execute(
            f"""
            {verb} INTO agent_versions
                (agent_id, version, profile, reason, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                agent_id,
                version,
                json.dumps(profile, ensure_ascii=False),
                reason,
                int(time.time() * 1000),
            ),
        )
        conn.commit()
        self.prune(agent_id, cap=cap)
        return version

    def prune(self, agent_id: str, cap: int = DEFAULT_VERSION_CAP) -> int:
        """裁剪超出 cap 的旧版本，返回删除行数。

        按 version 升序排序，保留最大的 ``cap`` 行；超过部分删除。
        """
        if cap <= 0:
            raise ValueError(f"cap 必须为正整数: {cap}")
        conn = get_database().get_connection()
        rows = conn.execute(
            "SELECT version FROM agent_versions "
            "WHERE agent_id = ? ORDER BY version DESC",
            (agent_id,),
        ).fetchall()
        if len(rows) <= cap:
            return 0
        to_delete = [int(r[0]) for r in rows[cap:]]
        if not to_delete:
            return 0
        placeholders = ",".join("?" * len(to_delete))
        cursor = conn.execute(
            f"DELETE FROM agent_versions "
            f"WHERE agent_id = ? AND version IN ({placeholders})",
            [agent_id, *to_delete],
        )
        conn.commit()
        return int(cursor.rowcount)

    # ------------------------------------------------------------------ #
    # 读
    # ------------------------------------------------------------------ #

    def list_versions(self, agent_id: str) -> List[Dict[str, Any]]:
        """列出某专家的所有快照，按 version DESC（最新在前）。

        每条包含 ``{version, reason, created_at}``，不含完整 profile。
        """
        conn = get_database().get_connection()
        rows = conn.execute(
            "SELECT version, reason, created_at FROM agent_versions "
            "WHERE agent_id = ? ORDER BY version DESC",
            (agent_id,),
        ).fetchall()
        return [
            {
                "version": int(r[0]),
                "reason": r[1] or "update",
                "created_at": int(r[2]),
            }
            for r in rows
        ]

    def read_version(self, agent_id: str, version: int) -> Optional[Dict[str, Any]]:
        """读取某版本完整 profile dict；不存在返回 None。"""
        conn = get_database().get_connection()
        row = conn.execute(
            "SELECT profile FROM agent_versions "
            "WHERE agent_id = ? AND version = ?",
            (agent_id, int(version)),
        ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row[0])
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning(
                "agent_versions profile JSON 解析失败 (agent=%s version=%s): %s",
                agent_id,
                version,
                exc,
            )
            return None

    def latest_version(self, agent_id: str) -> Optional[int]:
        """返回该专家最新版本号，无快照时返回 None。"""
        conn = get_database().get_connection()
        row = conn.execute(
            "SELECT MAX(version) FROM agent_versions WHERE agent_id = ?",
            (agent_id,),
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return int(row[0])

    # ------------------------------------------------------------------ #
    # 比对
    # ------------------------------------------------------------------ #

    def diff(
        self, agent_id: str, from_version: int, to_version: int
    ) -> List[Dict[str, Any]]:
        """字段级 diff。只比对白名单字段。

        :raises ValueError: 任一版本不存在
        :return: ``[{field, before, after}]``，未变更的字段不返回
        """
        before = self.read_version(agent_id, int(from_version))
        after = self.read_version(agent_id, int(to_version))
        if before is None:
            raise ValueError(
                f"version {from_version} 不存在 (agent={agent_id})"
            )
        if after is None:
            raise ValueError(
                f"version {to_version} 不存在 (agent={agent_id})"
            )

        changes: List[Dict[str, Any]] = []
        for field in DIFF_FIELD_WHITELIST:
            b_val = _normalize_for_diff(before.get(field))
            a_val = _normalize_for_diff(after.get(field))
            if b_val == a_val:
                continue
            changes.append({"field": field, "before": before.get(field), "after": after.get(field)})
        return changes

    # ------------------------------------------------------------------ #
    # 级联删除
    # ------------------------------------------------------------------ #

    def delete_all_for_agent(self, agent_id: str) -> int:
        """删除某专家的全部版本快照，返回删除行数。"""
        conn = get_database().get_connection()
        cursor = conn.execute(
            "DELETE FROM agent_versions WHERE agent_id = ?",
            (agent_id,),
        )
        conn.commit()
        return int(cursor.rowcount)


__all__ = [
    "AgentVersionRepository",
    "DEFAULT_VERSION_CAP",
    "DIFF_FIELD_WHITELIST",
]
