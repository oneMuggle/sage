"""M2 群聊参与者仓储测试。

覆盖：list_participants 返回顺序与 JOIN、add_participants 幂等与 host 选择、
remove_participant 行为、resolve_mention_agent 最长名字优先匹配。
"""
import sqlite3

import pytest

from backend.data.participant_repo import (
    add_participants,
    list_participants,
    remove_participant,
    resolve_mention_agent,
)


@pytest.fixture()
def conn(tmp_path):
    """构造最小测试库：agents 表 + conversation_participants 表。"""
    db = sqlite3.connect(str(tmp_path / "test.db"))
    db.row_factory = sqlite3.Row
    db.execute(
        """
        CREATE TABLE agents (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            persona_ui TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    db.executemany(
        "INSERT INTO agents (id, name, persona_ui) VALUES (?, ?, ?)",
        [
            ("writer", "写作专家", '{"avatar": "✍️"}'),
            ("writer-junior", "写作助手", '{"avatar": "📝"}'),
            ("researcher", "研究专家", '{"avatar": "🔬"}'),
        ],
    )
    db.execute(
        """
        CREATE TABLE conversation_participants (
            conversation_id TEXT NOT NULL,
            agent_id        TEXT NOT NULL,
            role            TEXT NOT NULL DEFAULT 'member',
            speak_order     INTEGER NOT NULL DEFAULT 0,
            enabled         INTEGER NOT NULL DEFAULT 1,
            added_at        INTEGER NOT NULL,
            PRIMARY KEY (conversation_id, agent_id)
        )
        """
    )
    db.commit()
    yield db
    db.close()


def test_add_participants_first_becomes_host(conn):
    result = add_participants(conn, "session-1", ["writer", "researcher"])

    assert [p["agent_id"] for p in result] == ["writer", "researcher"]
    assert result[0]["role"] == "host"
    assert result[1]["role"] == "member"
    assert result[0]["avatar"] == "✍️"
    assert result[1]["name"] == "研究专家"


def test_add_participants_is_idempotent(conn):
    add_participants(conn, "session-1", ["writer"])
    add_participants(conn, "session-1", ["writer", "researcher"])

    result = list_participants(conn, "session-1")
    assert [p["agent_id"] for p in result] == ["writer", "researcher"]
    # 首次加入的成员保留 host
    assert result[0]["role"] == "host"


def test_add_participants_with_explicit_host(conn):
    result = add_participants(
        conn, "session-1", ["writer", "researcher"], host_agent_id="researcher"
    )

    assert next(p for p in result if p["agent_id"] == "researcher")["role"] == "host"
    assert next(p for p in result if p["agent_id"] == "writer")["role"] == "member"


def test_remove_participant(conn):
    add_participants(conn, "session-1", ["writer", "researcher"])
    assert remove_participant(conn, "session-1", "writer") is True
    assert [p["agent_id"] for p in list_participants(conn, "session-1")] == ["researcher"]
    assert remove_participant(conn, "session-1", "writer") is False  # 再次删除 → 无效


def test_resolve_mention_agent_longest_name_wins(conn):
    add_participants(conn, "session-1", ["writer", "writer-junior", "researcher"])

    # 两个名字都能匹配时取最长
    assert resolve_mention_agent(conn, "session-1", "请 @写作助手 帮我整理") == "writer-junior"
    # 只命中较长名字
    assert resolve_mention_agent(conn, "session-1", "请 @写作专家 起草") == "writer"
    # 无 @ → None
    assert resolve_mention_agent(conn, "session-1", "没有 mention") is None
    # @ 一个不在参与者中 → None
    assert resolve_mention_agent(conn, "session-1", "请 @未知专家 回复") is None


def test_resolve_mention_agent_skips_disabled(conn):
    add_participants(conn, "session-1", ["writer", "researcher"])
    conn.execute(
        "UPDATE conversation_participants SET enabled = 0 WHERE agent_id = 'writer'"
    )
    conn.commit()

    assert resolve_mention_agent(conn, "session-1", "请 @写作专家 起草") is None
