"""EpisodicMemory FTS5 全文索引测试。

覆盖 PR feat/memory-recall-optimization 的 Phase 2 Task 6:
- memories_episodic_fts 虚表创建 + 写入时同步
- 中文 jieba 分词检索
- session / scope / importance / memory_type 过滤在 FTS 路径同样生效
- FTS 无命中时回退 LIKE
- invalidate / delete 后索引不残留
"""

from __future__ import annotations

import pytest

from backend.data.database import Database
from backend.memory.episodic import EpisodicMemory
from backend.tests.conftest import ensure_session

pytestmark = pytest.mark.unit


@pytest.fixture()
def episodic(tmp_db_path: str) -> EpisodicMemory:
    db = Database(db_path=tmp_db_path)
    db.init_db()
    return EpisodicMemory(db)


def _save_hotpot(episodic: EpisodicMemory, session_id: str = "s1") -> str:
    return episodic.save(
        "用户喜欢在成都吃火锅",
        importance=7,
        session_id=session_id,
        metadata={"tags": ["food", "city"]},
    )


class TestEpisodicFtsIndex:
    def test_fts_table_is_created(self, episodic: EpisodicMemory):
        cursor = episodic.db.get_connection().cursor()
        row = cursor.execute(
            "SELECT name FROM sqlite_master WHERE name = 'memories_episodic_fts'"
        ).fetchone()
        assert row is not None

    def test_save_syncs_fts_row(self, episodic: EpisodicMemory):
        ensure_session(episodic.db, "s1")
        memory_id = _save_hotpot(episodic)

        cursor = episodic.db.get_connection().cursor()
        hits = cursor.execute(
            "SELECT rowid FROM memories_episodic_fts WHERE rowid = "
            "(SELECT rowid FROM memories_episodic WHERE id = ?)",
            (memory_id,),
        ).fetchall()
        assert len(hits) == 1

    def test_backfill_indexes_preexisting_rows(self, episodic: EpisodicMemory):
        """构造绕过 save() 直写主表的存量行, 回填后应能被检索到。"""
        conn = episodic.db.get_connection()
        conn.execute(
            "INSERT INTO memories_episodic "
            "(id, content, summary, importance, tags, created_at, is_valid) "
            "VALUES (?, ?, ?, ?, ?, ?, 1)",
            ("legacy-1", "老数据 麻辣烫", "老数据 麻辣烫", 5, "[]", 1000),
        )
        conn.commit()
        episodic._backfill_fts()

        assert [m["id"] for m in episodic.search("麻辣烫")] == ["legacy-1"]

    def test_backfill_is_idempotent(self, episodic: EpisodicMemory):
        ensure_session(episodic.db, "s1")
        _save_hotpot(episodic)
        episodic._backfill_fts()
        episodic._backfill_fts()

        cursor = episodic.db.get_connection().cursor()
        count = cursor.execute("SELECT COUNT(*) FROM memories_episodic_fts").fetchone()[0]
        assert count == 1

    def test_backfill_indexes_more_than_500_rows(self, episodic: EpisodicMemory):
        """回归测试: 修复前 _backfill_fts 单批 LIMIT 500 即返回, 超过 500 条
        存量的记忆永远进不了 FTS 索引, search() 静默漏召回。修复后循环分批直到
        全部补齐, 600 条存量应全部被索引。"""
        conn = episodic.db.get_connection()
        for i in range(600):
            conn.execute(
                "INSERT INTO memories_episodic "
                "(id, content, summary, importance, tags, created_at, is_valid) "
                "VALUES (?, ?, ?, ?, ?, ?, 1)",
                (
                    f"bulk-{i:04d}",
                    f"bulk topic alpha {i}",
                    f"bulk topic alpha {i}",
                    5,
                    '["alpha"]',
                    1000 + i,
                ),
            )
        conn.commit()

        episodic._backfill_fts()

        cursor = conn.cursor()
        count = cursor.execute("SELECT COUNT(*) FROM memories_episodic_fts").fetchone()[0]
        assert count == 600, f"期望 600 行入 FTS 索引, 实际 {count}"


class TestSyncFtsRowForId:
    """模块级 sync_fts_row_for_id() 辅助函数测试。"""

    def test_syncs_single_row(self):
        """直接调用可为指定 id 同步 FTS 索引。"""
        import os
        import tempfile

        from backend.data.database import Database
        from backend.memory.episodic import sync_fts_row_for_id

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "sync_test.db")
            db = Database(db_path=db_path)
            db.init_db()
            # FTS 表由 EpisodicMemory.__init__ 创建, 必须先实例化一次
            EpisodicMemory(db)
            conn = db.get_connection()
            conn.execute(
                "INSERT INTO memories_episodic "
                "(id, content, summary, importance, tags, created_at, is_valid) "
                "VALUES (?, ?, ?, ?, ?, ?, 1)",
                ("m-sync-1", "sync test content", "sync test", 5, '["t1"]', 1000),
            )
            conn.commit()

            sync_fts_row_for_id(conn, "m-sync-1")
            conn.commit()

            cursor = conn.cursor()
            count = cursor.execute(
                "SELECT COUNT(*) FROM memories_episodic_fts WHERE rowid = "
                "(SELECT rowid FROM memories_episodic WHERE id = 'm-sync-1')"
            ).fetchone()[0]
            assert count == 1

            db.close()

    def test_noop_for_unknown_id(self):
        """不存在的 memory_id 不抛异常, 索引数不变。"""
        import os
        import tempfile

        from backend.data.database import Database
        from backend.memory.episodic import sync_fts_row_for_id

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "sync_test.db")
            db = Database(db_path=db_path)
            db.init_db()
            EpisodicMemory(db)
            conn = db.get_connection()

            sync_fts_row_for_id(conn, "does-not-exist")
            conn.commit()

            cursor = conn.cursor()
            count = cursor.execute(
                "SELECT COUNT(*) FROM memories_episodic_fts"
            ).fetchone()[0]
            assert count == 0

            db.close()


class TestEpisodicFtsSearch:
    def test_chinese_content_is_searchable(self, episodic: EpisodicMemory):
        ensure_session(episodic.db, "s1")
        memory_id = _save_hotpot(episodic)
        assert [m["id"] for m in episodic.search("火锅")] == [memory_id]

    def test_search_matches_second_token(self, episodic: EpisodicMemory):
        """jieba 分词后 query 任一 token 命中即返回。"""
        ensure_session(episodic.db, "s1")
        memory_id = _save_hotpot(episodic)
        assert [m["id"] for m in episodic.search("成都")] == [memory_id]

    def test_search_tags_are_indexed(self, episodic: EpisodicMemory):
        ensure_session(episodic.db, "s1")
        memory_id = _save_hotpot(episodic)
        assert [m["id"] for m in episodic.search("food")] == [memory_id]

    def test_search_returns_parsed_tags(self, episodic: EpisodicMemory):
        ensure_session(episodic.db, "s1")
        _save_hotpot(episodic)
        assert episodic.search("火锅")[0]["tags"] == ["food", "city"]

    def test_empty_query_returns_recent(self, episodic: EpisodicMemory):
        ensure_session(episodic.db, "s1")
        _save_hotpot(episodic)
        assert len(episodic.search("")) == 1

    def test_session_filter_still_isolates_on_fts_path(self, episodic: EpisodicMemory):
        ensure_session(episodic.db, "s1")
        ensure_session(episodic.db, "s2")
        _save_hotpot(episodic, session_id="s1")

        assert episodic.search("火锅", session_id="s2") == []
        assert len(episodic.search("火锅", session_id="s1")) == 1

    def test_scope_search_crosses_sessions(self, episodic: EpisodicMemory):
        ensure_session(episodic.db, "s1")
        memory_id = _save_hotpot(episodic, session_id="s1")
        assert [m["id"] for m in episodic.search("火锅", scope="user")] == [memory_id]

    def test_min_importance_filters_on_fts_path(self, episodic: EpisodicMemory):
        ensure_session(episodic.db, "s1")
        _save_hotpot(episodic)
        assert episodic.search("火锅", min_importance=9) == []

    def test_memory_type_filters_on_fts_path(self, episodic: EpisodicMemory):
        ensure_session(episodic.db, "s1")
        episodic.save("火锅是食物", importance=7, session_id="s1", memory_type="conversation")
        assert episodic.search("火锅", memory_type="fact") == []

    def test_invalidated_memory_is_not_recalled(self, episodic: EpisodicMemory):
        ensure_session(episodic.db, "s1")
        memory_id = _save_hotpot(episodic)
        episodic.invalidate(memory_id)
        assert episodic.search("火锅") == []

    def test_deleted_memory_is_not_recalled(self, episodic: EpisodicMemory):
        ensure_session(episodic.db, "s1")
        memory_id = _save_hotpot(episodic)
        episodic.delete(memory_id)
        assert episodic.search("火锅") == []

    def test_results_sorted_by_importance_desc(self, episodic: EpisodicMemory):
        ensure_session(episodic.db, "s1")
        episodic.save("火锅低优先级", importance=2, session_id="s1")
        episodic.save("火锅高优先级", importance=9, session_id="s1")
        results = episodic.search("火锅", limit=10)
        assert results[0]["importance"] == 9

    def test_like_fallback_finds_unindexed_row(self, episodic: EpisodicMemory):
        """绕过 save() 直写主表 (FTS 无该行) 时仍应被 LIKE 路径召回。"""
        conn = episodic.db.get_connection()
        conn.execute(
            "INSERT INTO memories_episodic "
            "(id, content, summary, importance, tags, created_at, is_valid) "
            "VALUES (?, ?, ?, ?, ?, ?, 1)",
            ("orphan-1", "未索引的稀饭条目", "未索引的稀饭条目", 5, "[]", 1000),
        )
        conn.commit()
        assert [m["id"] for m in episodic.search("稀饭")] == ["orphan-1"]

    def test_malformed_fts_input_does_not_raise(self, episodic: EpisodicMemory):
        """FTS 语法注入类输入必须被 _prepare_fts_query 转义掉。"""
        ensure_session(episodic.db, "s1")
        _save_hotpot(episodic)
        assert episodic.search('火锅" OR "1=1') is not None

    def test_blank_query_does_not_raise(self, episodic: EpisodicMemory):
        assert episodic.search("   ") is not None
