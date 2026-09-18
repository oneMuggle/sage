"""
Task 11 (2026-09-17): context-isolation retreat endpoint API 测试
- POST /api/v1/sessions/{id}/segments/retreat
- 真实临时 DB（conftest autouse fixture）;无 LLM 依赖。
- 覆盖:
  - 无 separator → ok=false
  - 有 separator → ok=true,合并两 segment,数据库行数减 1
"""

import pytest

from backend.data import database as db_mod
from backend.data.session_repo import MessageRepository

pytestmark = pytest.mark.integration


PREFIX = "/api/v1"


@pytest.fixture()
def db_setup(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db_path))
    monkeypatch.setattr(db_mod, "_db", None)
    db = db_mod.get_database()
    db.init_db()
    return db


def _create_session(db, session_id: str, title: str = "t") -> None:
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (session_id, title, 1000, 1000),
    )
    conn.commit()


@pytest.mark.asyncio()
async def test_retreat_unknown_session_returns_ok_false(client, db_setup):
    """无消息的会话→retreat_segment 找不到 separator,返回 ok=false。"""
    _create_session(db_setup, "missing-seg")
    resp = await client.post(f"{PREFIX}/sessions/missing-seg/segments/retreat")
    assert resp.status_code == 200
    assert resp.json() == {"ok": False}


@pytest.mark.asyncio()
async def test_retreat_undoes_last_separator_merges_segments(client, db_setup):
    """存在 separator → 删最后一行,merge segments,行数减 1。"""
    sess_id = "seg-1"
    _create_session(db_setup, sess_id)
    repo = MessageRepository()
    repo.insert(session_id=sess_id, role="user", content="old", created_at=1)
    repo.advance_segment(sess_id)
    repo.insert(session_id=sess_id, role="user", content="new", created_at=2)

    before_count = len(repo.get_by_session(sess_id))
    assert before_count == 3  # 2 user + 1 separator

    resp = await client.post(f"{PREFIX}/sessions/{sess_id}/segments/retreat")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    after = repo.get_by_session(sess_id)
    assert len(after) == 2
    assert {m.content for m in after} == {"old", "new"}
    # 没有 subtype=topic_separator 残留
    assert all(m.subtype != "topic_separator" for m in after)
