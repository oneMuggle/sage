"""验证 BlackboardRepo 的发布/订阅/标记/清理逻辑。"""

from __future__ import annotations

import time

import pytest

from backend.data.blackboard_repo import BlackboardRepo
from backend.data.database import Database

pytestmark = pytest.mark.unit


@pytest.fixture  # noqa: PT001 — 兼容 CI ruff 0.15.x (偏好无括号)
def repo(tmp_db_path: str) -> BlackboardRepo:
    db = Database(db_path=tmp_db_path)
    db.init_db()
    return BlackboardRepo(db=db)


def test_init_creates_table(repo: BlackboardRepo) -> None:
    conn = repo.db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='agent_blackboard'")
    assert cursor.fetchone() is not None


def test_publish_returns_id(repo: BlackboardRepo) -> None:
    mid = repo.publish(
        session_id="s1",
        agent_name="alice",
        message_type="hello",
        content={"text": "hi"},
    )
    assert mid
    assert isinstance(mid, str)


def test_publish_then_subscribe(repo: BlackboardRepo) -> None:
    repo.publish(session_id="s1", agent_name="alice", message_type="cmd", content={"x": 1})
    msgs = repo.subscribe(agent_name="bob", session_id="s1")
    assert len(msgs) == 1
    assert msgs[0]["content"] == {"x": 1}


def test_subscribe_targeted_message(repo: BlackboardRepo) -> None:
    repo.publish(
        session_id="s1",
        agent_name="alice",
        message_type="dm",
        content={"t": 1},
        target_agent="bob",
    )
    repo.publish(
        session_id="s1",
        agent_name="alice",
        message_type="dm",
        content={"t": 2},
        target_agent="charlie",
    )
    bob_msgs = repo.subscribe(agent_name="bob", session_id="s1")
    assert all(m.get("target_agent") in (None, "bob") for m in bob_msgs)
    assert len(bob_msgs) == 1


def test_subscribe_filter_by_message_type(repo: BlackboardRepo) -> None:
    repo.publish(session_id="s1", agent_name="a", message_type="cmd", content={})
    repo.publish(session_id="s1", agent_name="a", message_type="event", content={})
    msgs = repo.subscribe(agent_name="b", session_id="s1", message_type="cmd")
    assert len(msgs) == 1
    assert msgs[0]["message_type"] == "cmd"


def test_subscribe_excludes_expired(repo: BlackboardRepo) -> None:
    repo.publish(
        session_id="s1",
        agent_name="a",
        message_type="t",
        content={},
        ttl_seconds=1,
    )
    time.sleep(2)
    msgs = repo.subscribe(agent_name="b", session_id="s1")
    assert msgs == []


def test_subscribe_limit_applied(repo: BlackboardRepo) -> None:
    for i in range(5):
        repo.publish(session_id="s1", agent_name="a", message_type="t", content={"i": i})
    msgs = repo.subscribe(agent_name="b", session_id="s1", limit=3)
    assert len(msgs) == 3


def test_mark_read_adds_agent(repo: BlackboardRepo) -> None:
    mid = repo.publish(session_id="s1", agent_name="a", message_type="t", content={})
    assert repo.mark_read(mid, "bob") is True
    msgs = repo.subscribe(agent_name="bob", session_id="s1")
    assert "bob" in msgs[0]["read_by"]


def test_mark_read_dedup(repo: BlackboardRepo) -> None:
    mid = repo.publish(session_id="s1", agent_name="a", message_type="t", content={})
    repo.mark_read(mid, "bob")
    repo.mark_read(mid, "bob")
    msgs = repo.subscribe(agent_name="bob", session_id="s1")
    assert msgs[0]["read_by"].count("bob") == 1


def test_mark_read_missing_returns_false(repo: BlackboardRepo) -> None:
    assert repo.mark_read("missing-id", "bob") is False


def test_clean_expired(repo: BlackboardRepo) -> None:
    repo.publish(
        session_id="s1",
        agent_name="a",
        message_type="t",
        content={},
        ttl_seconds=1,
    )
    repo.publish(session_id="s1", agent_name="a", message_type="t", content={})
    time.sleep(2)
    deleted = repo.clean_expired()
    assert deleted == 1
    remaining = repo.get_session_messages("s1")
    assert len(remaining) == 1


def test_clean_expired_noop(repo: BlackboardRepo) -> None:
    repo.publish(session_id="s1", agent_name="a", message_type="t", content={})
    assert repo.clean_expired() == 0


def test_get_session_messages_orders_desc(repo: BlackboardRepo) -> None:
    repo.publish(session_id="s1", agent_name="a", message_type="t", content={"i": 1})
    time.sleep(1.05)  # created_at 用秒精度，需要超过 1s 才能保证有序
    repo.publish(session_id="s1", agent_name="a", message_type="t", content={"i": 2})
    msgs = repo.get_session_messages("s1")
    assert len(msgs) == 2
    assert msgs[0]["content"]["i"] == 2


def test_get_session_messages_limit(repo: BlackboardRepo) -> None:
    for i in range(4):
        repo.publish(session_id="s1", agent_name="a", message_type="t", content={"i": i})
    msgs = repo.get_session_messages("s1", limit=2)
    assert len(msgs) == 2


def test_get_session_messages_other_session_isolated(repo: BlackboardRepo) -> None:
    repo.publish(session_id="s1", agent_name="a", message_type="t", content={})
    repo.publish(session_id="s2", agent_name="a", message_type="t", content={})
    assert len(repo.get_session_messages("s1")) == 1
    assert len(repo.get_session_messages("s2")) == 1


def test_subscribe_handles_malformed_content(repo: BlackboardRepo) -> None:
    """直接写入非 JSON content 走 except 分支。"""
    conn = repo.db.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO agent_blackboard
        (id, session_id, agent_name, message_type, content, target_agent, created_at, read_by, expires_at)
        VALUES ('x1', 'sX', 'a', 't', 'not-json', NULL, ?, '[]', NULL)""",
        (int(time.time()),),
    )
    conn.commit()
    msgs = repo.subscribe(agent_name="b", session_id="sX")
    assert msgs[0]["content"] == "not-json"
