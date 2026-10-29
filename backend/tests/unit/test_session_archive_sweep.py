"""会话自动归档 sweep 与归档清空（purge）单测。

覆盖:
- ``archive_stale``: 最后活跃时间早于 cutoff 的会话被归档; 近期活跃 /
  置顶 / 运行中的会话跳过。
- ``purge_archived``: 归档会话连同消息一起永久删除; 非归档会话不受影响。
"""

from __future__ import annotations

import time

import pytest

from backend.data.session_repo import Message, MessageRepository, SessionRepository
from backend.tests.conftest import ensure_session

pytestmark = pytest.mark.unit


@pytest.fixture()
def repo(setup_test_db) -> SessionRepository:
    return SessionRepository()


def _backdate_last_message(repo: SessionRepository, session_id: str, days_ago: float) -> None:
    """把会话的 last_message_at 回拨到 days_ago 天前。"""
    conn = repo.db.get_connection()
    ts = int((time.time() - days_ago * 86400) * 1000)
    conn.execute("UPDATE sessions SET last_message_at = ? WHERE id = ?", (ts, session_id))
    conn.commit()


class TestArchiveStale:
    def test_archives_sessions_older_than_cutoff(self, repo, setup_test_db):
        sid = ensure_session(repo.db, "s-old", "旧会话")
        repo.update_run_status(sid, "idle")
        _backdate_last_message(repo, sid, days_ago=30)

        cutoff_ms = int((time.time() - 14 * 86400) * 1000)
        archived = repo.archive_stale(cutoff_ms)

        assert archived >= 1
        assert repo.get(sid).is_archived is True
        assert all(s.id != sid for s in repo.list())

    def test_skips_recently_active_sessions(self, repo, setup_test_db):
        sid = ensure_session(repo.db, "s-new", "新会话")
        _backdate_last_message(repo, sid, days_ago=1)

        cutoff_ms = int((time.time() - 14 * 86400) * 1000)
        assert repo.archive_stale(cutoff_ms) == 0
        assert repo.get(sid).is_archived is False

    def test_skips_pinned_sessions(self, repo, setup_test_db):
        sid = ensure_session(repo.db, "s-pinned", "置顶会话")
        repo.pin(sid, pinned=True)
        _backdate_last_message(repo, sid, days_ago=30)

        cutoff_ms = int((time.time() - 14 * 86400) * 1000)
        assert repo.archive_stale(cutoff_ms) == 0
        assert repo.get(sid).is_archived is False

    def test_skips_running_sessions(self, repo, setup_test_db):
        sid = ensure_session(repo.db, "s-running", "运行中会话")
        repo.update_run_status(sid, "running")
        _backdate_last_message(repo, sid, days_ago=30)

        cutoff_ms = int((time.time() - 14 * 86400) * 1000)
        assert repo.archive_stale(cutoff_ms) == 0
        assert repo.get(sid).is_archived is False


class TestListNodeFilter:
    """``SessionRepository.list(archived=...)`` —— 侧栏默认视图/归档视图。"""

    def test_default_excludes_archived(self, repo, setup_test_db):
        active_id = ensure_session(repo.db, "s-active", "活跃会话")
        archived_id = ensure_session(repo.db, "s-archived", "归档会话")
        repo.archive(archived_id)

        ids = [s.id for s in repo.list()]
        assert active_id in ids
        assert archived_id not in ids

    def test_archived_true_returns_only_archived(self, repo, setup_test_db):
        active_id = ensure_session(repo.db, "s-active2", "活跃会话")
        archived_id = ensure_session(repo.db, "s-archived2", "归档会话")
        repo.archive(archived_id)

        ids = [s.id for s in repo.list(archived=True)]
        assert ids == [archived_id]
        assert active_id not in ids

    def test_archived_false_keeps_default_behavior(self, repo, setup_test_db):
        active_id = ensure_session(repo.db, "s-active3", "活跃会话")
        archived_id = ensure_session(repo.db, "s-archived3", "归档会话")
        repo.archive(archived_id)

        assert [s.id for s in repo.list(archived=False)] == [active_id]

    def test_archived_list_paginates(self, repo, setup_test_db):
        ids = [ensure_session(repo.db, f"s-arch-page-{i}", f"归档-{i}") for i in range(3)]
        for sid in ids:
            repo.archive(sid)

        first = repo.list(limit=2, offset=0, archived=True)
        second = repo.list(limit=2, offset=2, archived=True)
        assert len(first) == 2
        assert len(second) == 1
        assert {s.id for s in first}.isdisjoint({s.id for s in second})


class TestPurgeArchived:
    def test_purges_archived_sessions_with_messages(self, repo, setup_test_db):
        msg_repo = MessageRepository()
        sid = ensure_session(repo.db, "s-purge", "要清空的归档")
        msg_repo.save(
            Message(
                id="m-purge-1",
                session_id=sid,
                role="user",
                content="hello",
                created_at=int(time.time() * 1000),
            )
        )
        repo.archive(sid)

        purged = repo.purge_archived()

        assert purged == 1
        assert repo.get(sid) is None
        conn = repo.db.get_connection()
        count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ?", (sid,)
        ).fetchone()[0]
        assert count == 0

    def test_keeps_non_archived_sessions(self, repo, setup_test_db):
        keep_id = ensure_session(repo.db, "s-keep", "未归档保留")
        purge_id = ensure_session(repo.db, "s-purge2", "归档删除")
        repo.archive(purge_id)

        repo.purge_archived()

        assert repo.get(keep_id) is not None
        assert repo.get(purge_id) is None

    def test_purge_with_nothing_archived(self, repo, setup_test_db):
        assert repo.purge_archived() == 0
