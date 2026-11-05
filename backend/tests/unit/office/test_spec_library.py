"""Unit tests for :mod:`backend.office.spec_library`.

Exercises the CRUD + binding resolution against a real :memory: SQLite
database produced by :func:`backend.data.database.Database.init_db`, so
the tests also catch regressions in the migration itself.
"""

from __future__ import annotations

import sqlite3

import pytest

from backend.data import database as db_mod
from backend.data.database import Database
from backend.office.errors import OfficeParseError
from backend.office.spec_library import (
    create_spec,
    delete_spec,
    get_default_spec,
    get_document_spec_id,
    get_spec,
    list_specs,
    resolve_effective_spec,
    set_default_spec,
    update_document_spec,
    update_spec,
)

WORKSPACE = "/home/tester/ws"
WORKSPACE_2 = "/home/tester/ws2"


@pytest.fixture()
def conn() -> sqlite3.Connection:
    db_mod._db = Database(":memory:")
    db_mod._db.init_db()
    yield db_mod._db.get_connection()
    db_mod._db.close()
    db_mod._db = None


def _make_spec(conn, *, name="投稿规范 v2", is_default=False, spec_id=None):
    return create_spec(
        conn,
        workspace_path=WORKSPACE,
        name=name,
        rulepack_id="general-quality",
        is_default=is_default,
        spec_id=spec_id,
    )


# ── list / get ────────────────────────────────────────────────────────


def test_list_specs_empty_when_no_rows(conn):
    assert list_specs(conn, WORKSPACE) == []


def test_create_then_get_round_trip(conn):
    row = _make_spec(conn)
    assert row["name"] == "投稿规范 v2"
    assert row["rulepack_id"] == "general-quality"
    assert row["is_default"] is False
    assert row["created_at"] > 0
    assert row["updated_at"] >= row["created_at"]

    fetched = get_spec(conn, row["id"])
    assert fetched is not None
    assert fetched["id"] == row["id"]


def test_list_specs_orders_default_first(conn):
    _make_spec(conn, name="A", spec_id="spec-a")
    _make_spec(conn, name="B", is_default=True, spec_id="spec-b")
    _make_spec(conn, name="C", spec_id="spec-c")
    rows = list_specs(conn, WORKSPACE)
    assert [r["id"] for r in rows] == ["spec-b", "spec-c", "spec-a"]


# ── default ───────────────────────────────────────────────────────────


def test_set_default_clears_others(conn):
    _make_spec(conn, name="A", is_default=True, spec_id="spec-a")
    new_default = set_default_spec(conn, WORKSPACE, "spec-a")
    assert new_default is not None
    assert new_default["id"] == "spec-a"

    _make_spec(conn, name="B", spec_id="spec-b")
    set_default_spec(conn, WORKSPACE, "spec-b")
    assert get_default_spec(conn, WORKSPACE)["id"] == "spec-b"
    # spec-a no longer default
    assert get_spec(conn, "spec-a")["is_default"] is False


def test_clear_default(conn):
    _make_spec(conn, name="A", is_default=True, spec_id="spec-a")
    set_default_spec(conn, WORKSPACE, None)
    assert get_default_spec(conn, WORKSPACE) is None


def test_set_default_nonexistent_raises(conn):
    with pytest.raises(OfficeParseError):
        set_default_spec(conn, WORKSPACE, "no-such-id")


# ── update ────────────────────────────────────────────────────────────


def test_update_spec_name_bumps_updated_at(conn):
    row = _make_spec(conn)
    old_updated = row["updated_at"]
    updated = update_spec(conn, row["id"], name="投稿规范 v3")
    assert updated["name"] == "投稿规范 v3"
    assert updated["updated_at"] >= old_updated


def test_update_spec_empty_name_rejected(conn):
    row = _make_spec(conn)
    with pytest.raises(OfficeParseError):
        update_spec(conn, row["id"], name="   ")


def test_update_spec_nonexistent_returns_none(conn):
    assert update_spec(conn, "no-such", name="x") is None


# ── delete ────────────────────────────────────────────────────────────


def test_delete_spec_clears_document_binding(conn):
    spec_row = _make_spec(conn, spec_id="spec-target")
    # Seed a managed document row pointing at this spec.
    conn.execute(
        "INSERT INTO office_documents "
        "(id, workspace_path, doc_type, original_filename, "
        "generated_filename, status, created_at, updated_at, metadata, "
        "active_spec_id) "
        "VALUES (?, ?, 'word', 'draft.docx', 'draft.docx', 'managed', "
        "1000, 1000, '{}', ?)",
        ("doc-1", WORKSPACE, spec_row["id"]),
    )
    conn.commit()

    assert get_document_spec_id(conn, "doc-1") == "spec-target"
    assert delete_spec(conn, "spec-target") is True
    assert get_document_spec_id(conn, "doc-1") is None


def test_delete_nonexistent_returns_false(conn):
    assert delete_spec(conn, "no-such") is False


# ── document binding ──────────────────────────────────────────────────


def test_update_document_spec_requires_existing_spec(conn):
    with pytest.raises(OfficeParseError):
        update_document_spec(conn, "doc-1", "no-such")


def test_update_document_spec_none_unbinds(conn):
    spec = _make_spec(conn, spec_id="spec-x")
    conn.execute(
        "INSERT INTO office_documents "
        "(id, workspace_path, doc_type, original_filename, "
        "generated_filename, status, created_at, updated_at, metadata, "
        "active_spec_id) "
        "VALUES (?, ?, 'word', 'f.docx', 'f.docx', 'managed', "
        "1, 1, '{}', ?)",
        ("doc-1", WORKSPACE, spec["id"]),
    )
    conn.commit()
    assert update_document_spec(conn, "doc-1", None) is True
    assert get_document_spec_id(conn, "doc-1") is None


# ── resolve_effective_spec priority ───────────────────────────────────


def test_resolve_explicit_spec_wins(conn):
    default = _make_spec(conn, name="Default", is_default=True, spec_id="spec-default")
    explicit = _make_spec(conn, name="Explicit", spec_id="spec-explicit")
    resolved = resolve_effective_spec(
        conn,
        workspace_path=WORKSPACE,
        doc_id="doc-1",
        spec_id="spec-explicit",
    )
    assert resolved["id"] == explicit["id"]
    assert resolved["id"] != default["id"]


def test_resolve_falls_back_to_document_binding(conn):
    _make_spec(conn, name="Default", is_default=True, spec_id="spec-default")
    doc_level = _make_spec(conn, name="DocLevel", spec_id="spec-doc")
    conn.execute(
        "INSERT INTO office_documents "
        "(id, workspace_path, doc_type, original_filename, "
        "generated_filename, status, created_at, updated_at, metadata, "
        "active_spec_id) "
        "VALUES (?, ?, 'word', 'f.docx', 'f.docx', 'managed', "
        "1, 1, '{}', ?)",
        ("doc-1", WORKSPACE, doc_level["id"]),
    )
    conn.commit()
    resolved = resolve_effective_spec(conn, workspace_path=WORKSPACE, doc_id="doc-1")
    assert resolved["id"] == "spec-doc"


def test_resolve_falls_back_to_workspace_default(conn):
    default = _make_spec(conn, name="Default", is_default=True, spec_id="spec-default")
    resolved = resolve_effective_spec(conn, workspace_path=WORKSPACE, doc_id="doc-1")
    assert resolved["id"] == default["id"]


def test_resolve_returns_none_when_nothing_bound(conn):
    assert resolve_effective_spec(conn, workspace_path=WORKSPACE) is None


# ── cross-workspace isolation (security review H1/H2) ────────────────


def test_get_spec_scoped_by_workspace(conn):
    """spec 元数据不能凭 id 跨工作区读取."""
    row = _make_spec(conn, spec_id="spec-ws1")
    assert get_spec(conn, row["id"], workspace_path=WORKSPACE) is not None
    assert get_spec(conn, row["id"], workspace_path=WORKSPACE_2) is None


def test_update_spec_scoped_by_workspace(conn):
    """跨工作区 update 返回 None 且不改原行."""
    row = _make_spec(conn, name="Original", spec_id="spec-ws1")
    assert (
        update_spec(conn, "spec-ws1", workspace_path=WORKSPACE_2, name="Hacked")
        is None
    )
    assert get_spec(conn, row["id"], workspace_path=WORKSPACE)["name"] == "Original"


def test_delete_spec_scoped_by_workspace(conn):
    """跨工作区 delete 返回 False 且不清理他工作区文档绑定."""
    _make_spec(conn, spec_id="spec-ws1")
    conn.execute(
        "INSERT INTO office_documents "
        "(id, workspace_path, doc_type, original_filename, "
        "generated_filename, status, created_at, updated_at, metadata, "
        "active_spec_id) "
        "VALUES (?, ?, 'word', 'd.docx', 'd.docx', 'managed', 1, 1, '{}', ?)",
        ("doc-ws1", WORKSPACE, "spec-ws1"),
    )
    conn.commit()

    assert delete_spec(conn, "spec-ws1", workspace_path=WORKSPACE_2) is False
    assert get_spec(conn, "spec-ws1", workspace_path=WORKSPACE) is not None
    assert get_document_spec_id(
        conn, "doc-ws1", workspace_path=WORKSPACE
    ) == "spec-ws1"


def test_delete_spec_does_not_clear_other_workspace_bindings(conn):
    """删除 ws1 的 spec 只清理 ws1 文档绑定，不动 ws2 文档."""
    _make_spec(conn, spec_id="spec-ws1")
    for doc_id, workspace in (
        ("doc-ws1", WORKSPACE),
        ("doc-ws2", WORKSPACE_2),
    ):
        conn.execute(
            "INSERT INTO office_documents "
            "(id, workspace_path, doc_type, original_filename, "
            "generated_filename, status, created_at, updated_at, metadata, "
            "active_spec_id) "
            "VALUES (?, ?, 'word', 'd.docx', 'd.docx', 'managed', 1, 1, '{}', ?)",
            (doc_id, workspace, "spec-ws1"),
        )
    conn.commit()

    assert delete_spec(conn, "spec-ws1", workspace_path=WORKSPACE) is True
    assert get_document_spec_id(conn, "doc-ws1") is None
    assert get_document_spec_id(conn, "doc-ws2") == "spec-ws1"


def test_update_document_spec_rejects_cross_workspace_doc(conn):
    """doc 不在给定工作区时绑定被拒绝."""
    spec = _make_spec(conn, spec_id="spec-ws1")
    conn.execute(
        "INSERT INTO office_documents "
        "(id, workspace_path, doc_type, original_filename, "
        "generated_filename, status, created_at, updated_at, metadata) "
        "VALUES (?, ?, 'word', 'd.docx', 'd.docx', 'managed', 1, 1, '{}')",
        ("doc-ws1", WORKSPACE),
    )
    conn.commit()
    with pytest.raises(OfficeParseError):
        update_document_spec(
            conn, "doc-ws1", spec["id"], workspace_path=WORKSPACE_2
        )


def test_update_document_spec_rejects_cross_workspace_spec(conn):
    """spec 不在给定工作区时绑定被拒绝."""
    _make_spec(conn, spec_id="spec-ws1")
    conn.execute(
        "INSERT INTO office_documents "
        "(id, workspace_path, doc_type, original_filename, "
        "generated_filename, status, created_at, updated_at, metadata) "
        "VALUES (?, ?, 'word', 'd.docx', 'd.docx', 'managed', 1, 1, '{}')",
        ("doc-ws2", WORKSPACE_2),
    )
    conn.commit()
    with pytest.raises(OfficeParseError):
        update_document_spec(
            conn, "doc-ws2", "spec-ws1", workspace_path=WORKSPACE_2
        )


def test_resolve_ignores_cross_workspace_spec_id(conn):
    """显式 spec_id 属于其它工作区时解析不到（也不回落其它区默认）."""
    _make_spec(conn, name="Default", is_default=True, spec_id="spec-default")
    _make_spec(conn, name="Other", spec_id="spec-other")

    # spec-other 属于 WORKSPACE，从 WORKSPACE_2 解析 → None
    assert (
        resolve_effective_spec(
            conn, workspace_path=WORKSPACE_2, spec_id="spec-other"
        )
        is None
    )
    resolved = resolve_effective_spec(
        conn, workspace_path=WORKSPACE, spec_id="spec-other"
    )
    assert resolved["id"] == "spec-other"


def test_resolve_ignores_cross_workspace_doc_binding(conn):
    """doc 属于其它工作区时，其绑定的规范书不参与解析."""
    create_spec(
        conn,
        workspace_path=WORKSPACE_2,
        name="Other WS",
        rulepack_id="general-quality",
        spec_id="spec-ws2",
    )
    conn.execute(
        "INSERT INTO office_documents "
        "(id, workspace_path, doc_type, original_filename, "
        "generated_filename, status, created_at, updated_at, metadata, "
        "active_spec_id) "
        "VALUES (?, ?, 'word', 'd.docx', 'd.docx', 'managed', 1, 1, '{}', ?)",
        ("doc-ws2", WORKSPACE_2, "spec-ws2"),
    )
    conn.commit()

    assert (
        resolve_effective_spec(
            conn, workspace_path=WORKSPACE, doc_id="doc-ws2"
        )
        is None
    )
    resolved = resolve_effective_spec(
        conn, workspace_path=WORKSPACE_2, doc_id="doc-ws2"
    )
    assert resolved["id"] == "spec-ws2"


# ── missing table (defensive) ────────────────────────────────────────


def test_list_specs_returns_empty_when_table_absent(conn):
    conn.execute("DROP TABLE IF EXISTS office_spec_documents")
    assert list_specs(conn, WORKSPACE) == []


def test_create_spec_requires_table(conn):
    conn.execute("DROP TABLE IF EXISTS office_spec_documents")
    with pytest.raises(OfficeParseError):
        create_spec(
            conn,
            workspace_path=WORKSPACE,
            name="x",
            rulepack_id="general-quality",
        )
