"""验证语义记忆 FTS5 启用：独立索引表、自愈、回填与搜索路径。

WS-B（2026-07-29 记忆系统 P0 优化）：
- 历史版本 external-content FTS5 + 触发器/手动维护违反同步协议，产生
  "database disk image is malformed"，触发器被禁用，search() 退化为 LIKE+jieba；
- 现方案：独立 FTS5 表（存 jieba 分词后的文本）+ SemanticMemory Python 侧显式同步
  （单一写入来源，无触发器）+ init_db 结构检测/完整性自愈/幂等回填；
- search() 优先走 FTS5 MATCH，命中为空或异常时回退 LIKE+jieba（_search_like）。
"""

from __future__ import annotations

import sqlite3

import pytest

from backend.data.database import Database
from backend.memory.semantic import SemanticMemory

pytestmark = pytest.mark.unit

FTS_TABLE = "memories_semantic_fts"


@pytest.fixture()
def db(tmp_path) -> Database:
    """独立临时 DB，不与 conftest autouse 的全局临时 DB 共享文件。"""
    database = Database(db_path=str(tmp_path / "fts.db"))
    database.init_db()
    yield database
    database.close()


@pytest.fixture()
def semantic(db: Database) -> SemanticMemory:
    return SemanticMemory(db)


def _fts_count(db: Database) -> int:
    return db.get_connection().execute(f"SELECT count(*) FROM {FTS_TABLE}").fetchone()[0]


def _assert_fts_path_used(semantic: SemanticMemory) -> None:
    """中和 LIKE 回退路径：此后 search() 仍能命中即证明走的是 FTS5。"""
    semantic._search_like = lambda *args, **kwargs: []  # type: ignore[method-assign]


# ==================== 基本命中 ====================


def test_chinese_phrase_hits_via_fts(db: Database, semantic: SemanticMemory) -> None:
    """中文短语经 jieba 分词后应通过 FTS5 MATCH 命中。"""
    semantic.save("用户喜欢吃火锅")
    semantic.save("天气预报说明天下雨")
    assert _fts_count(db) == 2

    _assert_fts_path_used(semantic)
    results = semantic.search("火锅")
    assert len(results) == 1
    assert "火锅" in results[0]["content"]


def test_english_word_hits_via_fts(db: Database, semantic: SemanticMemory) -> None:
    """英文词应通过 FTS5 MATCH 命中。"""
    semantic.save("python rocks for backend")
    semantic.save("java rules the enterprise")

    _assert_fts_path_used(semantic)
    results = semantic.search("python")
    assert len(results) == 1
    assert "python" in results[0]["content"]


def test_empty_query_returns_recent_without_error(db: Database, semantic: SemanticMemory) -> None:
    """空/纯空白查询返回最近记忆；特殊字符查询不抛异常。"""
    semantic.save("第一条")
    semantic.save("第二条")
    assert len(semantic.search("")) == 2
    assert len(semantic.search("   ")) == 2
    # FTS 语法特殊字符（引号）不应导致异常
    semantic.search('"""')


# ==================== 写入/删除/更新同步 ====================


def test_delete_removes_fts_entry(db: Database, semantic: SemanticMemory) -> None:
    """删除记忆后 FTS 索引行同步删除，不再命中。"""
    memory_id = semantic.save("用户喜欢吃火锅")
    assert _fts_count(db) == 1

    assert semantic.delete(memory_id) is True
    assert _fts_count(db) == 0

    _assert_fts_path_used(semantic)
    assert semantic.search("火锅") == []


def test_tags_indexed_and_updated(db: Database, semantic: SemanticMemory) -> None:
    """标签进入 FTS 索引；update_tags 后索引同步更新。"""
    memory_id = semantic.save("一些普通内容", tags=["火锅"])

    _assert_fts_path_used(semantic)
    assert len(semantic.search("火锅")) == 1

    semantic.update_tags(memory_id, ["编程"])
    assert semantic.search("火锅") == []
    assert len(semantic.search("编程")) == 1


def test_fts_respects_limit_and_tag_filter(db: Database, semantic: SemanticMemory) -> None:
    """FTS 路径保留原有 limit 与标签过滤语义。"""
    semantic.save("火锅底料的做法", tags=["food"])
    semantic.save("火锅店推荐", tags=["food", "city"])
    semantic.save("火锅历史", tags=["history"])

    _assert_fts_path_used(semantic)
    assert len(semantic.search("火锅", limit=2)) == 2

    only_food = semantic.search("火锅", tags=["food"])
    assert len(only_food) == 2
    assert all("food" in r["tags"] for r in only_food)

    history = semantic.search("火锅", tags=["history"])
    assert len(history) == 1
    assert history[0]["tags"] == ["history"]


# ==================== 自愈与回填 ====================


def test_corrupted_fts_self_heals_on_init_db(db: Database, semantic: SemanticMemory) -> None:
    """FTS 表损坏时 init_db 自愈重建，搜索仍可用（走 FTS）。"""
    semantic.save("用户喜欢吃火锅")
    conn = db.get_connection()

    # 模拟损坏：移除索引 shadow 表，此后任何 FTS 读取抛 DatabaseError
    # （实测错误：fts5: corruption found reading blob N from table）
    conn.execute(f"DROP TABLE {FTS_TABLE}_data")
    conn.commit()
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute(f"SELECT count(*) FROM {FTS_TABLE}").fetchone()

    # init_db 必须自愈且不抛异常
    db.init_db()

    assert _fts_count(db) == 1
    assert semantic.count() == 1
    _assert_fts_path_used(semantic)
    results = semantic.search("火锅")
    assert len(results) == 1
    assert "火锅" in results[0]["content"]


def test_legacy_external_content_table_rebuilt(db: Database, semantic: SemanticMemory) -> None:
    """检测到旧 external-content 定义时 drop 重建为独立表并回填。"""
    semantic.save("用户喜欢吃火锅")
    conn = db.get_connection()

    # 退回历史坏结构：external-content FTS5（malformed 根因）
    conn.execute(f"DROP TABLE {FTS_TABLE}")
    conn.execute(
        f"CREATE VIRTUAL TABLE {FTS_TABLE} USING fts5("
        "content, summary, tags, content='memories_semantic', content_rowid='rowid')"
    )
    conn.commit()

    db.init_db()

    schema_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = ?", (FTS_TABLE,)
    ).fetchone()[0]
    assert "content=" not in schema_sql.replace(" ", "").lower()

    assert _fts_count(db) == 1
    _assert_fts_path_used(semantic)
    assert len(semantic.search("火锅")) == 1


def test_backfill_idempotent_across_init_db(db: Database, semantic: SemanticMemory) -> None:
    """init_db 多次执行不产生重复索引行（幂等）。"""
    semantic.save("用户喜欢吃火锅")
    semantic.save("python backend")

    db.init_db()
    db.init_db()

    assert _fts_count(db) == 2
    assert semantic.count() == 2
    _assert_fts_path_used(semantic)
    assert len(semantic.search("火锅")) == 1


def test_backfill_picks_up_direct_main_table_inserts(db: Database, semantic: SemanticMemory) -> None:
    """绕过 SemanticMemory 直接写主表的行（如 evolution 晋升）在下次 init_db 被回填。"""
    conn = db.get_connection()
    conn.execute(
        "INSERT INTO memories_semantic (id, content, summary, tags, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("direct-1", "SQLite 是嵌入式数据库", "db", "[]", 123),
    )
    conn.commit()
    assert _fts_count(db) == 0

    db.init_db()

    assert _fts_count(db) == 1
    _assert_fts_path_used(semantic)
    assert len(semantic.search("数据库")) == 1


def test_missing_fts_table_does_not_break_save_or_search(
    db: Database, semantic: SemanticMemory
) -> None:
    """FTS 表缺失时写入/搜索不中断（搜索回退 LIKE+jieba）。"""
    conn = db.get_connection()
    conn.execute(f"DROP TABLE {FTS_TABLE}")
    conn.commit()

    memory_id = semantic.save("用户喜欢吃火锅")  # 不应抛异常
    assert semantic.get_by_id(memory_id) is not None

    results = semantic.search("火锅")  # FTS 异常 → LIKE 回退
    assert len(results) == 1
    assert "火锅" in results[0]["content"]
