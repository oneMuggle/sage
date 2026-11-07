# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""P3 规则仓库：规则组 / 规则的 SQLite CRUD。"""

from __future__ import annotations

import uuid
from typing import Any, List, Optional

from backend.office.rule_models import Rule, RuleGroup

_RULE_COLUMNS = (
    "id, name, type, severity, scope, description, check_mode, "
    "pattern, ai_prompt, enabled, group_id"
)


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _row_to_rule(row: Any) -> Rule:
    return Rule(
        id=row[0],
        name=row[1],
        type=row[2],
        severity=row[3],
        scope=row[4],
        description=row[5],
        check_mode=row[6],
        pattern=row[7],
        ai_prompt=row[8],
        enabled=bool(row[9]),
        group_id=row[10],
    )


def list_groups(conn: Any) -> List[RuleGroup]:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, name, description, priority, builtin FROM office_rule_groups "
        "ORDER BY priority DESC, created_at"
    )
    groups = []
    for group_id, name, description, priority, builtin in cursor.fetchall():
        groups.append(
            RuleGroup(
                id=group_id,
                name=name,
                description=description,
                rules=list_rules(conn, group_id),
                priority=priority,
                builtin=bool(builtin),
            )
        )
    return groups


def get_group(conn: Any, group_id: str) -> RuleGroup:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, name, description, priority, builtin FROM office_rule_groups " "WHERE id = ?",
        (group_id,),
    )
    row = cursor.fetchone()
    if not row:
        raise ValueError(f"Group not found: {group_id}")
    return RuleGroup(
        id=row[0],
        name=row[1],
        description=row[2],
        rules=list_rules(conn, group_id),
        priority=row[3],
        builtin=bool(row[4]),
    )


def create_group(conn: Any, name: str, description: str, priority: int) -> RuleGroup:
    group_id = _gen_id("group")
    conn.cursor().execute(
        "INSERT INTO office_rule_groups (id, name, description, priority) " "VALUES (?, ?, ?, ?)",
        (group_id, name, description, priority),
    )
    conn.commit()
    return RuleGroup(
        id=group_id,
        name=name,
        description=description,
        rules=[],
        priority=priority,
        builtin=False,
    )


def update_group(
    conn: Any,
    group_id: str,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    priority: Optional[int] = None,
) -> RuleGroup:
    updates = []
    params = []
    for column, value in (
        ("name", name),
        ("description", description),
        ("priority", priority),
    ):
        if value is not None:
            updates.append(f"{column} = ?")
            params.append(value)
    if updates:
        updates.append("updated_at = datetime('now')")
        params.append(group_id)
        conn.cursor().execute(
            f"UPDATE office_rule_groups SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
    return get_group(conn, group_id)


def delete_group(conn: Any, group_id: str) -> None:
    conn.cursor().execute("DELETE FROM office_rule_groups WHERE id = ?", (group_id,))
    conn.commit()


def list_rules(conn: Any, group_id: str) -> List[Rule]:
    cursor = conn.cursor()
    cursor.execute(
        f"SELECT {_RULE_COLUMNS} FROM office_rules WHERE group_id = ?",
        (group_id,),
    )
    return [_row_to_rule(row) for row in cursor.fetchall()]


def get_rule(conn: Any, rule_id: str) -> Rule:
    cursor = conn.cursor()
    cursor.execute(f"SELECT {_RULE_COLUMNS} FROM office_rules WHERE id = ?", (rule_id,))
    row = cursor.fetchone()
    if not row:
        raise ValueError(f"Rule not found: {rule_id}")
    return _row_to_rule(row)


def create_rule(
    conn: Any,
    group_id: str,
    name: str,
    type: str,
    severity: str,
    scope: str,
    check_mode: str,
    *,
    description: str = "",
    pattern: Optional[str] = None,
    ai_prompt: Optional[str] = None,
    enabled: bool = True,
) -> Rule:
    rule_id = _gen_id("rule")
    conn.cursor().execute(
        """
        INSERT INTO office_rules
            (id, name, type, severity, scope, description, check_mode,
             pattern, ai_prompt, enabled, group_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            rule_id,
            name,
            type,
            severity,
            scope,
            description,
            check_mode,
            pattern,
            ai_prompt,
            int(enabled),
            group_id,
        ),
    )
    conn.commit()
    return get_rule(conn, rule_id)


def update_rule(conn: Any, rule_id: str, **kwargs: Any) -> Rule:
    updates = []
    params = []
    for key in (
        "name",
        "type",
        "severity",
        "scope",
        "description",
        "check_mode",
        "pattern",
        "ai_prompt",
    ):
        if key in kwargs:
            updates.append(f"{key} = ?")
            params.append(kwargs[key])
    if "enabled" in kwargs:
        updates.append("enabled = ?")
        params.append(int(kwargs["enabled"]))
    if updates:
        updates.append("updated_at = datetime('now')")
        params.append(rule_id)
        conn.cursor().execute(
            f"UPDATE office_rules SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
    return get_rule(conn, rule_id)


def delete_rule(conn: Any, rule_id: str) -> None:
    conn.cursor().execute("DELETE FROM office_rules WHERE id = ?", (rule_id,))
    conn.commit()
