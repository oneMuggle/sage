"""验证 EpisodicMemory 的 CRUD 与搜索行为。"""

from __future__ import annotations

import pytest

from backend.data.database import Database
from backend.memory.episodic import EpisodicMemory

pytestmark = pytest.mark.unit


@pytest.fixture()
def episodic(tmp_db_path: str) -> EpisodicMemory:
    db = Database(db_path=tmp_db_path)
    db.init_db()
    return EpisodicMemory(db)


def test_save_returns_id(episodic: EpisodicMemory) -> None:
    mid = episodic.save("hello world", importance=7)
    assert mid
    assert isinstance(mid, str)


def test_save_with_metadata_and_session(episodic: EpisodicMemory) -> None:
    mid = episodic.save(
        "user prefers tea",
        importance=8,
        metadata={"tags": ["preference", "drinks"]},
        session_id="sess-1",
        memory_type="fact",
    )
    found = episodic.get_by_id(mid)
    assert found is not None
    assert found["session_id"] == "sess-1"
    assert found["memory_type"] == "fact"
    assert found["importance"] == 8
    assert "preference" in found["tags"]


def test_search_finds_matching_content(episodic: EpisodicMemory) -> None:
    episodic.save("favourite color is blue", importance=5)
    episodic.save("unrelated content", importance=5)
    results = episodic.search("blue", limit=5)
    assert len(results) >= 1
    assert any("blue" in r["content"] for r in results)


def test_search_filters_by_importance(episodic: EpisodicMemory) -> None:
    episodic.save("low importance match", importance=2)
    episodic.save("high importance match", importance=9)
    results = episodic.search("match", limit=10, min_importance=8)
    assert all(r["importance"] >= 8 for r in results)


def test_search_filters_by_type(episodic: EpisodicMemory) -> None:
    episodic.save("alpha event", importance=5, memory_type="event")
    episodic.save("alpha note", importance=5, memory_type="note")
    events = episodic.search("alpha", memory_type="event")
    assert all(r["memory_type"] == "event" for r in events)
    assert len(events) >= 1


def test_get_recent_global_and_by_session(episodic: EpisodicMemory) -> None:
    episodic.save("a", session_id="s1")
    episodic.save("b", session_id="s2")
    episodic.save("c", session_id="s1")
    all_recent = episodic.get_recent(limit=10)
    assert len(all_recent) == 3
    s1_recent = episodic.get_recent(limit=10, session_id="s1")
    assert len(s1_recent) == 2
    assert all(r["session_id"] == "s1" for r in s1_recent)


def test_get_by_session_alias(episodic: EpisodicMemory) -> None:
    episodic.save("x", session_id="abc")
    results = episodic.get_by_session("abc")
    assert len(results) == 1


def test_delete_soft_marks_invalid(episodic: EpisodicMemory) -> None:
    mid = episodic.save("to delete")
    assert episodic.delete(mid) is True
    assert episodic.get_by_id(mid) is None
    assert episodic.count() == 0


def test_delete_unknown_returns_false(episodic: EpisodicMemory) -> None:
    assert episodic.delete("missing-id") is False


def test_count_excludes_invalid(episodic: EpisodicMemory) -> None:
    episodic.save("a")
    mid = episodic.save("b")
    episodic.delete(mid)
    assert episodic.count() == 1


def test_summary_truncated_for_long_content(episodic: EpisodicMemory) -> None:
    long_text = "x" * 500
    mid = episodic.save(long_text)
    found = episodic.get_by_id(mid)
    assert found is not None
    assert found["summary"].endswith("...")
    assert len(found["summary"]) <= 110


def test_search_increments_access_count(episodic: EpisodicMemory) -> None:
    mid = episodic.save("counter test")
    episodic.search("counter")
    rec = episodic.get_by_id(mid)
    assert rec is not None
    assert rec["access_count"] >= 1


def test_get_by_id_missing_returns_none(episodic: EpisodicMemory) -> None:
    assert episodic.get_by_id("nope") is None
