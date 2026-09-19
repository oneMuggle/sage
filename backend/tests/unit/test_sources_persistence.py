"""R81 统一参考来源：引用列持久化往返测试

覆盖 backend/data/session_repo.py 新增的 ``rag_citations`` / ``sources``
JSON-in-TEXT 列：
- dataclass 默认 None
- to_dict 解析成结构化 list（畸形 JSON 降级 None）
- from_row 对缺列（老库行）容错
- save → get_by_session 真库往返
- fork 复制引用列（子会话保留引用区块）
"""

from __future__ import annotations

import json

import pytest

from backend.data.session_repo import (
    Message,
    MessageRepository,
    SessionRepository,
    _insert_forked_message_row,
)

pytestmark = pytest.mark.unit

R81_CITATIONS = [
    {"media_id": "m-1", "filename": "spec.pdf", "mode": "rag", "chunks": [{"index": 0, "score": 0.91}]}
]
R81_SOURCES = [
    {"kind": "web", "title": "Sage", "url": "https://sage.example.com", "snippet": "官网", "query": "sage"},
    {"kind": "wiki", "title": "架构", "path": "wiki/arch.md", "snippet": "分层", "score": 0.87},
]


def test_r81_fields_default_to_none():
    msg = Message(id="m", session_id="s", role="assistant", content="c", created_at=1)
    assert msg.rag_citations is None
    assert msg.sources is None


def test_r81_to_dict_parses_json_columns():
    msg = Message(
        id="m",
        session_id="s",
        role="assistant",
        content="c",
        created_at=1,
        rag_citations=json.dumps(R81_CITATIONS, ensure_ascii=False),
        sources=json.dumps(R81_SOURCES, ensure_ascii=False),
    )
    d = msg.to_dict()
    assert d["rag_citations"] == R81_CITATIONS
    assert d["sources"] == R81_SOURCES


def test_r81_to_dict_malformed_json_degrades_to_none():
    msg = Message(
        id="m",
        session_id="s",
        role="assistant",
        content="c",
        created_at=1,
        rag_citations="{not json",
        sources='{"kind": "web"}',  # dict 而非 list → 形状不符降级
    )
    d = msg.to_dict()
    assert d["rag_citations"] is None
    assert d["sources"] is None


def test_r81_from_row_tolerates_missing_columns():
    """老库行（迁移前写入）没有这两列 → from_row 不抛错、值为 None。"""
    row = {
        "id": "m",
        "session_id": "s",
        "role": "assistant",
        "content": "c",
        "created_at": 1,
        "model": None,
        "provider": None,
        "tool_calls": None,
        "tool_call_id": None,
        "reasoning_content": None,
    }
    msg = Message.from_row(row)
    assert msg.rag_citations is None
    assert msg.sources is None


def test_r81_save_roundtrips_through_db(setup_test_db):
    """save → get_by_session → to_dict 引用列完整往返。"""
    session = SessionRepository().create(title="r58")
    repo = MessageRepository()
    repo.save(
        Message(
            id="msg-r58-1",
            session_id=session.id,
            role="assistant",
            content="回答",
            created_at=1,
            rag_citations=json.dumps(R81_CITATIONS, ensure_ascii=False),
            sources=json.dumps(R81_SOURCES, ensure_ascii=False),
        )
    )

    rows = repo.get_by_session(session.id)
    assert len(rows) == 1
    parsed = rows[0].to_dict()
    assert parsed["rag_citations"] == R81_CITATIONS
    assert parsed["sources"] == R81_SOURCES


def test_r81_fork_copies_citation_columns(setup_test_db):
    """fork 复制消息行时引用列随行复制（子会话保留引用区块）。"""
    session = SessionRepository().create(title="r58-fork")
    repo = MessageRepository()
    src = Message(
        id="msg-r58-src",
        session_id=session.id,
        role="assistant",
        content="回答",
        created_at=1,
        rag_citations=json.dumps(R81_CITATIONS, ensure_ascii=False),
        sources=json.dumps(R81_SOURCES, ensure_ascii=False),
    )
    repo.save(src)

    forked_session = SessionRepository().create(title="r58-fork-child")
    conn = repo.db.get_connection()
    cursor = conn.cursor()
    _insert_forked_message_row(cursor, forked_session.id, src)
    conn.commit()

    rows = repo.get_by_session(forked_session.id)
    assert len(rows) == 1
    parsed = rows[0].to_dict()
    assert parsed["rag_citations"] == R81_CITATIONS
    assert parsed["sources"] == R81_SOURCES
