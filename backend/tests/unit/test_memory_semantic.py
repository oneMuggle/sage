"""验证 SemanticMemory 的 CRUD/FTS/标签操作。"""

from __future__ import annotations

import pytest

from backend.data.database import Database
from backend.memory.semantic import SemanticMemory

pytestmark = pytest.mark.unit


@pytest.fixture()
def semantic(tmp_db_path: str) -> SemanticMemory:
    db = Database(db_path=tmp_db_path)
    db.init_db()
    return SemanticMemory(db)


def test_save_returns_id_and_persists(semantic: SemanticMemory) -> None:
    mid = semantic.save("python is great", summary="lang", tags=["lang", "py"])
    assert mid
    rec = semantic.get_by_id(mid)
    assert rec is not None
    assert rec["content"] == "python is great"
    assert rec["summary"] == "lang"
    assert "py" in rec["tags"]


def test_save_auto_generates_summary_for_long_content(semantic: SemanticMemory) -> None:
    text = "abc" * 200
    mid = semantic.save(text)
    rec = semantic.get_by_id(mid)
    assert rec is not None
    assert rec["summary"].endswith("...")


def test_save_short_content_summary_is_full(semantic: SemanticMemory) -> None:
    short = "tiny"
    mid = semantic.save(short)
    rec = semantic.get_by_id(mid)
    assert rec is not None
    assert rec["summary"] == "tiny"


def test_search_with_fts(semantic: SemanticMemory) -> None:
    semantic.save("apple banana cherry")
    semantic.save("dog cat bird")
    results = semantic.search("banana", limit=5)
    assert len(results) >= 1
    assert any("banana" in r["content"] for r in results)


def test_search_empty_query_returns_recent(semantic: SemanticMemory) -> None:
    semantic.save("first")
    semantic.save("second")
    results = semantic.search("", limit=10)
    assert len(results) == 2


def test_search_multi_word_query(semantic: SemanticMemory) -> None:
    semantic.save("python rocks for backend")
    semantic.save("javascript wins in browsers")
    results = semantic.search("python backend", limit=5)
    assert len(results) >= 1


def test_search_like_fallback_path(semantic: SemanticMemory) -> None:
    """显式调用 LIKE 回退路径，覆盖标签过滤。"""
    semantic.save("hello world", tags=["greeting"])
    semantic.save("goodbye", tags=["farewell"])
    results = semantic._search_like("hello", limit=5)
    assert len(results) >= 1
    filtered = semantic._search_like("hello", limit=5, tags=["nope"])
    assert filtered == []


def test_get_recent_orders_newest_first(semantic: SemanticMemory) -> None:
    import time

    semantic.save("oldest")
    time.sleep(0.01)
    semantic.save("middle")
    time.sleep(0.01)
    newest_id = semantic.save("newest")
    recent = semantic.get_recent(limit=10)
    assert recent[0]["id"] == newest_id


def test_get_all_alias(semantic: SemanticMemory) -> None:
    semantic.save("one")
    semantic.save("two")
    assert len(semantic.get_all()) == 2


def test_count(semantic: SemanticMemory) -> None:
    assert semantic.count() == 0
    semantic.save("x")
    semantic.save("y")
    assert semantic.count() == 2


def test_delete_existing(semantic: SemanticMemory) -> None:
    mid = semantic.save("to delete")
    assert semantic.delete(mid) is True
    assert semantic.get_by_id(mid) is None


def test_delete_unknown_returns_false(semantic: SemanticMemory) -> None:
    assert semantic.delete("missing") is False


def test_update_tags(semantic: SemanticMemory) -> None:
    mid = semantic.save("tagged", tags=["a"])
    assert semantic.update_tags(mid, ["b", "c"]) is True
    rec = semantic.get_by_id(mid)
    assert rec is not None
    assert set(rec["tags"]) == {"b", "c"}


def test_update_tags_missing_id(semantic: SemanticMemory) -> None:
    assert semantic.update_tags("missing", ["x"]) is False


def test_get_by_id_missing(semantic: SemanticMemory) -> None:
    assert semantic.get_by_id("nope") is None


def test_session_filter_applies_to_fts_and_recent(semantic: SemanticMemory) -> None:
    session_a_id = semantic.save("shared semantic fact", session_id="session-a")
    session_b_id = semantic.save("shared semantic fact", session_id="session-b")

    results = semantic.search("shared", session_id="session-a")
    assert [item["id"] for item in results] == [session_a_id]
    assert [item["id"] for item in semantic.search("", session_id="session-b")] == [
        session_b_id
    ]


def test_session_filter_applies_to_like_fallback(semantic: SemanticMemory) -> None:
    semantic.save("fallback-only fact", session_id="session-a")
    semantic.save("fallback-only fact", session_id="session-b")
    semantic._search_fts = lambda *args, **kwargs: []  # type: ignore[method-assign]

    results = semantic.search("fallback-only", session_id="session-b")
    assert len(results) == 1
    assert results[0]["session_id"] == "session-b"


def test_existing_semantic_table_gets_session_column(tmp_db_path: str) -> None:
    db = Database(db_path=tmp_db_path)
    db.init_db()
    conn = db.get_connection()
    conn.execute("DROP TABLE memories_semantic")
    conn.execute(
        """
        CREATE TABLE memories_semantic (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            summary TEXT,
            tags TEXT DEFAULT '[]',
            created_at INTEGER NOT NULL
        )
        """
    )
    conn.commit()

    semantic = SemanticMemory(db)
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(memories_semantic)")
    }
    assert "session_id" in columns
    semantic.save("migrated", session_id="session-a")
    assert semantic.search("migrated", session_id="session-a")
    db.close()


def test_legacy_null_session_rows_backfilled_to_default_on_upgrade(
    tmp_db_path: str,
) -> None:
    """升级前 session_id 列未存在的旧表,在迁移时不仅 ADD COLUMN,还要把历史行
    的 session_id 回填为 'default',否则按 session_id 过滤后历史数据全部不可见
    (Win7 LTS 升级用户场景)。
    """
    db = Database(db_path=tmp_db_path)
    db.init_db()
    conn = db.get_connection()
    conn.execute("DROP TABLE memories_semantic")
    conn.execute(
        """
        CREATE TABLE memories_semantic (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            summary TEXT,
            tags TEXT DEFAULT '[]',
            created_at INTEGER NOT NULL
        )
        """
    )
    # 旧版插入路径不会写 session_id 列(列根本不存在)。
    conn.execute(
        "INSERT INTO memories_semantic (id, content, summary, tags, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("legacy-1", "legacy fact one", None, "[]", 1_700_000_000_000),
    )
    conn.execute(
        "INSERT INTO memories_semantic (id, content, summary, tags, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("legacy-2", "legacy fact two", None, "[]", 1_700_000_001_000),
    )
    conn.commit()

    # 触发 _init_fts: ADD COLUMN + 回填
    SemanticMemory(db)

    rows = {
        row["id"]: row["session_id"]
        for row in conn.execute(
            "SELECT id, session_id FROM memories_semantic ORDER BY id"
        )
    }
    assert rows == {"legacy-1": "default", "legacy-2": "default"}

    # 升级后新建一行带明确 session_id,确认回填只针对迁移窗口,不会影响新行。
    db.close()

    db2 = Database(db_path=tmp_db_path)
    db2.init_db()
    sem = SemanticMemory(db2)
    new_id = sem.save("brand new", session_id="session-x")
    assert sem.get_by_id(new_id)["session_id"] == "session-x"
    db2.close()


def test_post_migration_new_null_writes_are_not_overwritten(tmp_db_path: str) -> None:
    """迁移窗口关闭后,_init_fts 不应再触发回填,避免覆盖调用方明确写入的 NULL。

    注:save() 在语义层强制要求 session_id 非空,直接通过 INSERT 模拟"极端"
    边界值(列允许 NULL,只是语义层不写)。验证 init 只在列刚加时跑 UPDATE,
    不在每次启动都跑。
    """
    db = Database(db_path=tmp_db_path)
    db.init_db()
    conn = db.get_connection()
    conn.execute("DROP TABLE memories_semantic")
    conn.execute(
        """
        CREATE TABLE memories_semantic (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            summary TEXT,
            tags TEXT DEFAULT '[]',
            created_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO memories_semantic (id, content, summary, tags, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("legacy-1", "legacy fact", None, "[]", 1_700_000_000_000),
    )
    conn.commit()
    SemanticMemory(db)
    # 第一轮 init 完成,回填为 default
    row = conn.execute(
        "SELECT session_id FROM memories_semantic WHERE id = 'legacy-1'"
    ).fetchone()
    assert row["session_id"] == "default"
    db.close()

    # 第二轮 init: 列已存在,不应再触发 UPDATE
    db2 = Database(db_path=tmp_db_path)
    db2.init_db()
    conn2 = db2.get_connection()
    conn2.execute(
        "UPDATE memories_semantic SET session_id = NULL WHERE id = 'legacy-1'"
    )
    conn2.commit()
    SemanticMemory(db2)
    row = conn2.execute(
        "SELECT session_id FROM memories_semantic WHERE id = 'legacy-1'"
    ).fetchone()
    assert row["session_id"] is None  # 没被 init 二次回填
    db2.close()


def test_prepare_fts_query_handles_empty() -> None:
    sm = SemanticMemory.__new__(SemanticMemory)
    assert sm._prepare_fts_query("") == '""'
    assert "OR" in sm._prepare_fts_query("a b")
