"""Unit tests for :mod:`backend.office.style_template_store`.

Runs against a real :memory: SQLite database produced by
:func:`backend.data.database.Database.init_db`, so the migration for
``office_style_templates`` is exercised too (same pattern as
``test_spec_library.py``).
"""

from __future__ import annotations

import sqlite3

import pytest

from backend.data import database as db_mod
from backend.data.database import Database
from backend.office.errors import OfficeParseError
from backend.office.style_template_store import (
    create_style_template,
    delete_style_template,
    get_default_style_template,
    get_style_template,
    list_style_templates,
    set_default_style_template,
)

WORKSPACE = "/home/tester/ws"
WORKSPACE_2 = "/home/tester/ws2"

_SPEC = {
    "page": {"margins_cm": {"top": 3.0, "bottom": 2.5, "left": 2.6, "right": 2.4}},
    "body": {"font_family": "宋体", "font_size_pt": 12},
}


@pytest.fixture()
def conn() -> sqlite3.Connection:
    db_mod._db = Database(":memory:")
    db_mod._db.init_db()
    yield db_mod._db.get_connection()
    db_mod._db.close()
    db_mod._db = None


def _make_template(conn, *, name="学院论文模板", template_id=None, **kwargs):
    params = {
        "workspace_path": WORKSPACE,
        "name": name,
        "format_spec": _SPEC,
        "source_kind": "manual",
        "template_id": template_id,
    }
    params.update(kwargs)
    return create_style_template(conn, **params)


# ── list / get ────────────────────────────────────────────────────────


def test_list_style_templates_empty_when_no_rows(conn):
    assert list_style_templates(conn, WORKSPACE) == []


def test_create_then_get_round_trip(conn):
    row = _make_template(conn)
    assert row["name"] == "学院论文模板"
    assert row["source_kind"] == "manual"
    assert row["source_ref"] is None
    assert row["is_default"] is False
    assert row["created_at"] > 0
    assert row["updated_at"] >= row["created_at"]
    assert row["format_spec"] == _SPEC

    fetched = get_style_template(conn, row["id"])
    assert fetched is not None
    assert fetched["id"] == row["id"]
    assert fetched["format_spec"]["body"]["font_family"] == "宋体"


def test_create_derives_id_from_uuid_when_absent(conn):
    row = _make_template(conn)
    assert row["id"].startswith("style-")
    assert len(row["id"]) > len("style-")


def test_list_style_templates_orders_default_first(conn):
    _make_template(conn, name="A", template_id="style-a")
    _make_template(conn, name="B", template_id="style-b", is_default=True)
    _make_template(conn, name="C", template_id="style-c")
    rows = list_style_templates(conn, WORKSPACE)
    assert [r["id"] for r in rows] == ["style-b", "style-c", "style-a"]


def test_list_style_templates_scoped_by_workspace(conn):
    _make_template(conn, template_id="style-ws1")
    create_style_template(
        conn,
        workspace_path=WORKSPACE_2,
        name="Other",
        format_spec=_SPEC,
        template_id="style-ws2",
    )
    assert [r["id"] for r in list_style_templates(conn, WORKSPACE)] == ["style-ws1"]
    assert [r["id"] for r in list_style_templates(conn, WORKSPACE_2)] == ["style-ws2"]


# ── default ───────────────────────────────────────────────────────────


def test_create_with_default_clears_previous_default(conn):
    _make_template(conn, name="A", template_id="style-a", is_default=True)
    _make_template(conn, name="B", template_id="style-b", is_default=True)
    assert get_default_style_template(conn, WORKSPACE)["id"] == "style-b"
    assert get_style_template(conn, "style-a")["is_default"] is False


def test_set_default_clears_others(conn):
    _make_template(conn, name="A", template_id="style-a", is_default=True)
    _make_template(conn, name="B", template_id="style-b")
    updated = set_default_style_template(conn, WORKSPACE, "style-b")
    assert updated is not None
    assert updated["id"] == "style-b"
    assert get_default_style_template(conn, WORKSPACE)["id"] == "style-b"
    assert get_style_template(conn, "style-a")["is_default"] is False


def test_set_default_none_clears_default(conn):
    _make_template(conn, template_id="style-a", is_default=True)
    assert set_default_style_template(conn, WORKSPACE, None) is None
    assert get_default_style_template(conn, WORKSPACE) is None


def test_set_default_nonexistent_raises(conn):
    with pytest.raises(OfficeParseError):
        set_default_style_template(conn, WORKSPACE, "no-such-id")


def test_set_default_rejects_cross_workspace_template(conn):
    """ws2 的模板不能被设为 ws1 的默认."""
    _make_template(conn, template_id="style-a", is_default=True)
    create_style_template(
        conn,
        workspace_path=WORKSPACE_2,
        name="Other",
        format_spec=_SPEC,
        template_id="style-ws2",
    )
    with pytest.raises(OfficeParseError):
        set_default_style_template(conn, WORKSPACE, "style-ws2")
    # ws1 原有默认不受影响
    assert get_default_style_template(conn, WORKSPACE)["id"] == "style-a"


# ── validation ────────────────────────────────────────────────────────


def test_create_rejects_blank_name(conn):
    with pytest.raises(OfficeParseError):
        _make_template(conn, name="   ")


def test_create_rejects_overlong_name(conn):
    with pytest.raises(OfficeParseError):
        _make_template(conn, name="长" * 201)


def test_create_rejects_unknown_source_kind(conn):
    with pytest.raises(OfficeParseError):
        _make_template(conn, source_kind="bogus")


def test_create_accepts_rulepack_source_kind(conn):
    row = _make_template(conn, source_kind="rulepack", source_ref="thesis-pack")
    assert row["source_kind"] == "rulepack"
    assert row["source_ref"] == "thesis-pack"


def test_create_rejects_non_dict_format_spec(conn):
    with pytest.raises(OfficeParseError):
        _make_template(conn, format_spec=["not", "a", "dict"])


def test_create_accepts_json_string_format_spec(conn):
    import json

    row = _make_template(conn, format_spec=json.dumps(_SPEC, ensure_ascii=False))
    assert row["format_spec"] == _SPEC


def test_create_rejects_malformed_json_string(conn):
    with pytest.raises(OfficeParseError):
        _make_template(conn, format_spec="{not json")


# ── delete ────────────────────────────────────────────────────────────


def test_delete_nonexistent_returns_false(conn):
    assert delete_style_template(conn, "no-such") is False


def test_delete_removes_row(conn):
    _make_template(conn, template_id="style-a")
    assert delete_style_template(conn, "style-a", workspace_path=WORKSPACE) is True
    assert get_style_template(conn, "style-a") is None


def test_delete_scoped_by_workspace(conn):
    """跨工作区 delete 返回 False 且不删原行."""
    _make_template(conn, template_id="style-ws1")
    assert (
        delete_style_template(conn, "style-ws1", workspace_path=WORKSPACE_2) is False
    )
    assert get_style_template(conn, "style-ws1", workspace_path=WORKSPACE) is not None


def test_get_scoped_by_workspace(conn):
    """模板不能凭 id 跨工作区读取."""
    _make_template(conn, template_id="style-ws1")
    assert get_style_template(conn, "style-ws1", workspace_path=WORKSPACE) is not None
    assert get_style_template(conn, "style-ws1", workspace_path=WORKSPACE_2) is None


# ── snapshot semantics ───────────────────────────────────────────────


def test_saved_template_is_a_snapshot_not_a_reference(conn):
    """保存时的画像快照独立于可变来源——后续以新画像新建模板不影响旧模板."""
    _make_template(conn, template_id="style-a")
    changed = {
        "page": {"margins_cm": {"top": 1.0, "bottom": 1.0, "left": 1.0, "right": 1.0}},
    }
    _make_template(conn, name="Changed", template_id="style-b", format_spec=changed)
    assert get_style_template(conn, "style-a")["format_spec"] == _SPEC
    assert get_style_template(conn, "style-b")["format_spec"] == changed


def test_corrupt_format_spec_tolerated_as_empty_dict(conn):
    """单行 JSON 损坏不拖垮列表——读回空画像."""
    conn.execute(
        "INSERT INTO office_style_templates "
        "(id, workspace_path, name, format_spec, source_kind, source_ref, "
        "is_default, created_at, updated_at) "
        "VALUES ('style-bad', ?, 'Bad', '{broken', 'manual', NULL, 0, 1, 1)",
        (WORKSPACE,),
    )
    conn.commit()
    rows = list_style_templates(conn, WORKSPACE)
    assert rows[0]["format_spec"] == {}


# ── missing table (defensive) ────────────────────────────────────────


def test_list_returns_empty_when_table_absent(conn):
    conn.execute("DROP TABLE IF EXISTS office_style_templates")
    assert list_style_templates(conn, WORKSPACE) == []


def test_get_returns_none_when_table_absent(conn):
    conn.execute("DROP TABLE IF EXISTS office_style_templates")
    assert get_style_template(conn, "style-a") is None
    assert get_default_style_template(conn, WORKSPACE) is None


def test_writes_require_table(conn):
    conn.execute("DROP TABLE IF EXISTS office_style_templates")
    with pytest.raises(OfficeParseError):
        create_style_template(
            conn, workspace_path=WORKSPACE, name="x", format_spec=_SPEC
        )
    with pytest.raises(OfficeParseError):
        set_default_style_template(conn, WORKSPACE, None)
    with pytest.raises(OfficeParseError):
        delete_style_template(conn, "style-a")
