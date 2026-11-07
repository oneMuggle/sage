# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""Rule pack export/import for the Office rules workspace (P3).

Export snapshots selected groups (with their rules) into a transportable
``RulePack``. Import always allocates fresh ids so a pack can be imported
repeatedly or on a second machine without primary-key collisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, List

from backend.office.errors import OfficeParseError
from backend.office.rule_models import RulePack
from backend.office.rule_repo import create_group, create_rule, get_group

_MAX_IMPORT_RULES = 500


@dataclass
class ImportReport:
    groups: int
    imported_rules: int


def build_rule_pack(
    conn: Any,
    group_ids: List[str],
    *,
    name: str,
    version: str = "1.0",
    exported_by: str = "local",
) -> RulePack:
    # Deduplicate preserving first-seen order (safety net — endpoint also dedupes).
    unique_ids = list(dict.fromkeys(group_ids))
    groups = [get_group(conn, gid) for gid in unique_ids]
    return RulePack(
        name=name,
        version=version,
        groups=groups,
        exported_at=datetime.now(timezone.utc).isoformat(),  # noqa: UP017 — timezone.utc is py38-safe
        exported_by=exported_by,
    )


def import_rule_pack(conn: Any, pack: RulePack) -> ImportReport:
    total_rules = sum(len(group.rules) for group in pack.groups)
    if not pack.groups:
        raise OfficeParseError("规则包为空：至少需要一个规则分组")
    if total_rules == 0:
        raise OfficeParseError("规则包中没有任何规则")
    if total_rules > _MAX_IMPORT_RULES:
        raise OfficeParseError(f"规则包包含 {total_rules} 条规则，超过上限 {_MAX_IMPORT_RULES}")

    groups = 0
    imported_rules = 0
    for group in pack.groups:
        created = create_group(conn, group.name, group.description, group.priority)
        groups += 1
        for rule in group.rules:
            create_rule(
                conn,
                created.id,
                rule.name,
                rule.type,
                rule.severity,
                rule.scope,
                rule.check_mode,
                pattern=rule.pattern,
                ai_prompt=rule.ai_prompt,
                enabled=rule.enabled,
                description=rule.description,
            )
            imported_rules += 1
    return ImportReport(groups=groups, imported_rules=imported_rules)
