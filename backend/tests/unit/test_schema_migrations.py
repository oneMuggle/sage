# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""schema 版本化迁移框架测试（DSH 对标 R9，C3）。

全局 MIGRATIONS 注册表用 fixture 隔离（save/restore），测试注册的迁移
不污染其他用例。init_db 集成用例验证生产接线（空注册表 → no-op）。
"""

from __future__ import annotations

import pytest

from backend.data.migrations.runner import (
    MIGRATIONS,
    applied_versions,
    ensure_version_table,
    register_migration,
    run_pending_migrations,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def clean_registry():
    """隔离全局注册表：测试结束恢复原内容。"""
    saved = list(MIGRATIONS)
    MIGRATIONS.clear()
    yield MIGRATIONS
    MIGRATIONS[:] = saved


def _add_migration(version, name, fn):
    register_migration(version, name, fn)


def test_fresh_db_applies_all_in_order(setup_test_db, clean_registry):
    calls = []
    _add_migration(1, "m1", lambda conn: calls.append(1))
    _add_migration(2, "m2", lambda conn: calls.append(2))

    applied = run_pending_migrations(setup_test_db.get_connection())
    assert applied == [1, 2]
    assert calls == [1, 2]
    assert applied_versions(setup_test_db.get_connection()) == {1, 2}


def test_idempotent_second_run_is_noop(setup_test_db, clean_registry):
    calls = []
    _add_migration(1, "m1", lambda conn: calls.append(1))

    conn = setup_test_db.get_connection()
    assert run_pending_migrations(conn) == [1]
    assert run_pending_migrations(conn) == []  # 第二次：全部已应用
    assert calls == [1]  # 迁移函数只执行一次


def test_existing_versions_are_skipped(setup_test_db, clean_registry):
    ensure_version_table(setup_test_db.get_connection())
    setup_test_db.get_connection().execute(
        "INSERT INTO schema_version (version, name, applied_at) VALUES (1, '历史迁移', 0)"
    )
    setup_test_db.get_connection().commit()

    calls = []
    _add_migration(1, "m1", lambda conn: calls.append("不应执行"))
    _add_migration(2, "m2", lambda conn: calls.append(2))

    applied = run_pending_migrations(setup_test_db.get_connection())
    assert applied == [2]
    assert calls == [2]  # v1 已在账本 → 跳过


def test_non_increasing_version_rejected(clean_registry):
    _add_migration(2, "m2", lambda conn: None)
    with pytest.raises(ValueError, match="严格递增"):
        _add_migration(2, "dup", lambda conn: None)
    with pytest.raises(ValueError, match="严格递增"):
        _add_migration(1, "backwards", lambda conn: None)


def test_failed_migration_not_recorded(setup_test_db, clean_registry):
    def _boom(conn):
        raise RuntimeError("迁移炸了")

    _add_migration(1, "boom", _boom)
    with pytest.raises(RuntimeError):
        run_pending_migrations(setup_test_db.get_connection())
    # 失败版本不留账本记录（半应用可定位）
    assert applied_versions(setup_test_db.get_connection()) == set()


def test_migration_can_execute_ddl(setup_test_db, clean_registry):
    def _create_sentinel(conn):
        conn.execute(
            "CREATE TABLE IF NOT EXISTS _migration_sentinel (id INTEGER PRIMARY KEY)"
        )
        conn.commit()

    _add_migration(1, "sentinel", _create_sentinel)
    run_pending_migrations(setup_test_db.get_connection())
    conn = setup_test_db.get_connection()
    conn.execute("INSERT INTO _migration_sentinel DEFAULT VALUES")
    conn.commit()


# ---- init_db 生产接线（空注册表 → no-op，不破坏既有初始化）----


def test_init_db_with_empty_registry_is_noop(tmp_path):
    from backend.data.database import Database

    db = Database(db_path=str(tmp_path / "fresh.db"))
    try:
        db.init_db()  # 空注册表：迁移步骤 no-op，不抛错
        versions = applied_versions(db.get_connection())
        assert versions == set()
        # schema_version 表已建（账本就绪）
        rows = db.get_connection().execute("SELECT * FROM schema_version").fetchall()
        assert rows == []
    finally:
        db.close()
