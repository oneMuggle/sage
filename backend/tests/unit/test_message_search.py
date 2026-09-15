"""MessageSearchIndex 单元测试（Round 2 session_search 底层）"""

from __future__ import annotations

import tempfile
import time

import pytest

from backend.data.database import Database
from backend.data.message_search import MessageSearchIndex

pytestmark = pytest.mark.unit


@pytest.fixture()
def tmp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = Database(f.name)
        db.init_db()
        yield db
        db.close()


@pytest.fixture()
def index(tmp_db):
    return MessageSearchIndex(tmp_db)


def _insert_message(db, message_id, session_id, role, content, created_at=None):
    conn = db.get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO sessions (id, title, created_at, updated_at) "
        "VALUES (?, 't', ?, ?)",
        (session_id, int(time.time()), int(time.time())),
    )
    conn.execute(
        "INSERT INTO messages (id, session_id, role, content, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            message_id,
            session_id,
            role,
            content,
            created_at or int(time.time()),
        ),
    )
    conn.commit()


class TestIndexAndSearch:
    def test_index_and_search_chinese(self, tmp_db, index):
        _insert_message(tmp_db, "m1", "s1", "user", "我们上次怎么解决那个构建报错的")
        assert index.index_message("m1", "s1", "user", "我们上次怎么解决那个构建报错的")
        results = index.search("构建报错")
        assert len(results) >= 1
        assert results[0]["message_id"] == "m1"
        assert "构建报错" in results[0]["excerpt"]

    def test_index_is_idempotent(self, tmp_db, index):
        _insert_message(tmp_db, "m1", "s1", "user", "部署流程说明")
        index.index_message("m1", "s1", "user", "部署流程说明")
        index.index_message("m1", "s1", "user", "部署流程说明")
        assert index.search("部署流程") .__len__() >= 1

    def test_session_filter(self, tmp_db, index):
        _insert_message(tmp_db, "m1", "s1", "user", "Vite 构建配置优化")
        _insert_message(tmp_db, "m2", "s2", "user", "Vite 插件开发调试")
        index.index_message("m1", "s1", "user", "Vite 构建配置优化")
        index.index_message("m2", "s2", "user", "Vite 插件开发调试")
        results = index.search("Vite", session_id="s1")
        assert len(results) == 1
        assert results[0]["session_id"] == "s1"

    def test_empty_content_skipped(self, index):
        assert index.index_message("m-empty", "s1", "tool", "   ") is False

    def test_search_empty_query(self, index):
        assert index.search("") == []
        assert index.search("   ") == []

    def test_rebuild_all(self, tmp_db, index):
        _insert_message(tmp_db, "m1", "s1", "user", "数据库迁移方案讨论")
        _insert_message(tmp_db, "m2", "s1", "assistant", "迁移脚本已生成")
        # 先不索引，直接 rebuild
        count = index.rebuild_all()
        assert count >= 2
        results = index.search("迁移脚本")
        assert any(r["message_id"] == "m2" for r in results)


class TestLikeFallback:
    def test_like_fallback_on_unavailable_index(self, tmp_db, index, monkeypatch):
        """FTS 表损坏（不可用）→ LIKE 回退仍能命中"""
        _insert_message(tmp_db, "m1", "s1", "user", "Python asyncio 并发模型详解")
        index.index_message("m1", "s1", "user", "Python asyncio 并发模型详解")
        # 破坏 FTS 表使其不可用
        conn = tmp_db.get_connection()
        conn.execute("DROP TABLE messages_fts")
        conn.commit()
        results = index.search("asyncio")
        assert len(results) >= 1
        assert results[0]["message_id"] == "m1"
