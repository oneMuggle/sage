"""Session Lineage 单元测试（Round 4 压缩谱系）"""

from __future__ import annotations

import tempfile

import pytest

from backend.data.database import Database
from backend.data.session_lineage import list_archives
from backend.data.session_repo import MessageRepository

pytestmark = pytest.mark.unit


@pytest.fixture()
def tmp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = Database(f.name)
        db.init_db()
        yield db
        db.close()


def _mk_session(db, session_id: str = "sess-lin", title: str = "构建问题排查") -> str:
    conn = db.get_connection()
    conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, 1, 1)",
        (session_id, title),
    )
    conn.commit()
    return session_id


def _mk_message(db, message_id: str, session_id: str, content: str, created_at: int):
    conn = db.get_connection()
    conn.execute(
        "INSERT INTO messages (id, session_id, role, content, created_at) "
        "VALUES (?, ?, 'user', ?, ?)",
        (message_id, session_id, content, created_at),
    )
    conn.commit()


class TestReplacePrefixArchives:
    def test_compaction_creates_archive_with_original_text(self, tmp_db):
        """压缩替换 → 归档会话存在且原文完整、谱系正确"""
        sid = _mk_session(tmp_db)
        repo = MessageRepository()
        repo.db = tmp_db
        ids = []
        for i, text in enumerate(["报错现场 A", "尝试方案 B", "最终解决 C"]):
            mid = f"m{i}"
            _mk_message(tmp_db, mid, sid, text, 1700000000 + i)
            ids.append(mid)

        from backend.data.session_repo import Message as Msg

        continuation = Msg(
            id="cont-1",
            session_id=sid,
            role="assistant",
            content="[压缩摘要] 之前讨论了报错排查",
            created_at=1700000010,
        )
        repo.replace_prefix_with_continuation(
            sid, ids, continuation
        )

        archives = list_archives(tmp_db, sid)
        assert len(archives) == 1
        arch = archives[0]
        assert "压缩归档" in arch["title"]
        assert arch["message_count"] == 3

        # 归档会话保留原文（新 id，原 created_at 保序）
        arch_msgs = repo.get_by_session(arch["archive_session_id"], limit=50)
        assert [m.content for m in arch_msgs] == ["报错现场 A", "尝试方案 B", "最终解决 C"]

        # 2026-11-05 非破坏压缩：原文保留在会话（compacted_at 标记）；
        # 续接行排在保留尾部之后，会话页面看到完整 4 条记录。
        remaining = repo.get_by_session(sid, limit=50)
        assert [m.id for m in remaining] == ["m0", "m1", "m2", "cont-1"]
        by_id = {m.id: m for m in remaining}
        assert by_id["m0"].compacted_at is not None
        assert by_id["m1"].compacted_at is not None
        assert by_id["m2"].compacted_at is not None
        assert by_id["cont-1"].compacted_at is None

        # 归档会话被标记 archived
        row = tmp_db.get_connection().execute(
            "SELECT is_archived FROM sessions WHERE id = ?",
            (arch["archive_session_id"],),
        ).fetchone()
        assert row[0] == 1

    def test_compaction_rollback_removes_archive(self, tmp_db):
        """归档副本用新 id，压缩仍成功（2026-11-05 后归档是兼容入口）。"""
        sid = _mk_session(tmp_db)
        repo = MessageRepository()
        repo.db = tmp_db
        ids = []
        for i in range(2):
            mid = f"m{i}"
            _mk_message(tmp_db, mid, sid, f"text {i}", 1700000000 + i)
            ids.append(mid)

        from backend.data.session_repo import Message as Msg

        continuation = Msg(
            id="cont-bad",
            session_id=sid,
            role="assistant",
            content="x",
            created_at=1700000010,
            tool_call_id="nonexistent-fk",
        )
        repo.replace_prefix_with_continuation(sid, ids, continuation)
        archives = list_archives(tmp_db, sid)
        assert len(archives) == 1
        arch_msgs = repo.get_by_session(archives[0]["archive_session_id"], limit=10)
        # 归档副本用新 id，主会话原文仍保留（compacted_at 标记）
        assert all(m.id not in ids for m in arch_msgs)
        assert all(m.session_id == archives[0]["archive_session_id"] for m in arch_msgs)
        main_remaining = repo.get_by_session(sid, limit=50)
        assert all(getattr(m, "compacted_at", None) is not None for m in main_remaining[:2])


class TestListArchives:
    def test_no_archives_empty(self, tmp_db):
        sid = _mk_session(tmp_db)
        assert list_archives(tmp_db, sid) == []
