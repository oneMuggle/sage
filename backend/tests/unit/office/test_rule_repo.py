from __future__ import annotations

import pytest

from backend.data.database import Database
from backend.office.rule_repo import (
    create_group,
    create_rule,
    delete_group,
    delete_rule,
    get_group,
    get_rule,
    list_groups,
    list_rules,
    update_group,
    update_rule,
)


@pytest.fixture()
def mem_db() -> Database:
    db = Database(db_path=":memory:")
    db.init_db()
    return db


def _rule_kwargs(**overrides: object) -> dict:
    base = dict(  # noqa: C408 — kwargs-shaped fixture keeps overrides readable
        name="No passive",
        type="format",
        severity="warning",
        scope="body",
        check_mode="regex",
        pattern=r"\bis\b.*\bbeen\b",
        enabled=True,
    )
    base.update(overrides)
    return base


def test_create_and_list_groups(mem_db: Database) -> None:
    conn = mem_db.get_connection()
    group = create_group(conn, name="Style", description="Style rules", priority=10)
    assert group.id.startswith("group-")
    assert group.name == "Style"

    groups = list_groups(conn)
    assert len(groups) == 1
    assert groups[0].id == group.id
    assert groups[0].priority == 10


def test_create_rule_in_group(mem_db: Database) -> None:
    conn = mem_db.get_connection()
    group = create_group(conn, name="Style", description="", priority=0)
    rule = create_rule(conn, group_id=group.id, **_rule_kwargs())

    assert rule.id.startswith("rule-")
    assert rule.group_id == group.id
    assert rule.description == ""
    assert rule.enabled is True

    rules = list_rules(conn, group.id)
    assert len(rules) == 1
    assert rules[0].id == rule.id


def test_rule_description_round_trips(mem_db: Database) -> None:
    conn = mem_db.get_connection()
    group = create_group(conn, name="Style", description="", priority=0)
    rule = create_rule(conn, group_id=group.id, **_rule_kwargs(description="避免被动语态"))
    assert get_rule(conn, rule.id).description == "避免被动语态"

    updated = update_rule(conn, rule.id, description="改为主动语态")
    assert updated.description == "改为主动语态"
    assert get_rule(conn, rule.id).description == "改为主动语态"


def test_update_rule_fields_and_toggle(mem_db: Database) -> None:
    conn = mem_db.get_connection()
    group = create_group(conn, name="Style", description="", priority=0)
    rule = create_rule(conn, group_id=group.id, **_rule_kwargs())

    updated = update_rule(conn, rule.id, name="No passive 2", enabled=False)
    assert updated.name == "No passive 2"
    assert updated.enabled is False
    assert updated.pattern == r"\bis\b.*\bbeen\b"


def test_update_group_fields(mem_db: Database) -> None:
    conn = mem_db.get_connection()
    group = create_group(conn, name="Style", description="", priority=0)
    updated = update_group(conn, group.id, name="Style 2", priority=5)
    assert updated.name == "Style 2"
    assert updated.priority == 5
    assert updated.description == ""


def test_delete_rule(mem_db: Database) -> None:
    conn = mem_db.get_connection()
    group = create_group(conn, name="Style", description="", priority=0)
    rule = create_rule(conn, group_id=group.id, **_rule_kwargs())
    delete_rule(conn, rule.id)
    assert list_rules(conn, group.id) == []
    with pytest.raises(ValueError):  # noqa: PT011 — message covered in test_missing_ids_raise
        get_rule(conn, rule.id)


def test_delete_group_cascades(mem_db: Database) -> None:
    conn = mem_db.get_connection()
    group = create_group(conn, name="Style", description="", priority=0)
    create_rule(conn, group_id=group.id, **_rule_kwargs())
    delete_group(conn, group.id)
    assert list_groups(conn) == []
    with pytest.raises(ValueError):  # noqa: PT011 — message covered in test_missing_ids_raise
        get_group(conn, group.id)


def test_missing_ids_raise(mem_db: Database) -> None:
    conn = mem_db.get_connection()
    with pytest.raises(ValueError, match="Group not found: nope"):
        get_group(conn, "nope")
    with pytest.raises(ValueError, match="Rule not found: nope"):
        get_rule(conn, "nope")
