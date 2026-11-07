# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
from __future__ import annotations

from typing import Any, List

import pytest

from backend.data.database import Database
from backend.office.errors import OfficeParseError
from backend.office.rule_models import Rule, RuleGroup, RulePack
from backend.office.rule_pack_io import build_rule_pack, import_rule_pack
from backend.office.rule_repo import create_group, create_rule, list_groups


@pytest.fixture()
def db() -> Database:
    database = Database(":memory:")
    database.init_db()
    return database


def _seed(conn: Any) -> str:
    group = create_group(conn, "规范", "写作规范", 10)
    create_rule(
        conn,
        group.id,
        "禁用待定",
        "terminology",
        "warning",
        "body",
        "regex",
        pattern="待定",
        description="终稿不得出现占位词",
    )
    return group.id


def test_build_rule_pack_shape(db: Database) -> None:
    conn = db.get_connection()
    group_id = _seed(conn)
    pack = build_rule_pack(conn, [group_id], name="我的规则包")
    assert pack.name == "我的规则包"
    assert pack.version == "1.0"
    assert pack.exported_by == "local"
    assert pack.exported_at.endswith("+00:00")
    assert len(pack.groups) == 1
    assert pack.groups[0].rules[0].description == "终稿不得出现占位词"


def test_build_rule_pack_unknown_group_raises(db: Database) -> None:
    with pytest.raises(ValueError, match="Group not found"):
        build_rule_pack(db.get_connection(), ["group-missing"], name="x")


def test_import_roundtrip_regenerates_ids(db: Database) -> None:
    conn = db.get_connection()
    original_group_id = _seed(conn)
    pack = build_rule_pack(conn, [original_group_id], name="包")
    original_rule_id = pack.groups[0].rules[0].id

    report = import_rule_pack(conn, pack)
    assert report.groups == 1
    assert report.imported_rules == 1

    groups = list_groups(conn)
    assert len(groups) == 2
    imported = [group for group in groups if group.id != original_group_id][0]
    assert imported.id != original_group_id
    assert imported.rules[0].id != original_rule_id
    assert imported.rules[0].group_id == imported.id


def test_import_rejects_empty_pack(db: Database) -> None:
    empty = RulePack(
        name="空",
        version="1.0",
        groups=[],
        exported_at="2026-11-07T00:00:00+00:00",
        exported_by="local",
    )
    with pytest.raises(OfficeParseError):
        import_rule_pack(db.get_connection(), empty)


def test_import_rejects_too_many_rules(db: Database) -> None:
    groups: List[RuleGroup] = []
    for group_index in range(6):
        rules: List[Rule] = [
            Rule(
                id=f"rule-{rule_index}",
                name="规则",
                type="custom",
                severity="warning",
                scope="body",
                check_mode="regex",
                pattern="x",
                group_id=f"group-{group_index}",
            )
            for rule_index in range(100)
        ]
        groups.append(RuleGroup(id=f"group-{group_index}", name="组", rules=rules))
    pack = RulePack(
        name="过大",
        version="1.0",
        groups=groups,
        exported_at="2026-11-07T00:00:00+00:00",
        exported_by="local",
    )
    with pytest.raises(OfficeParseError):
        import_rule_pack(db.get_connection(), pack)
