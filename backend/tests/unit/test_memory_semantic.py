"""验证 SemanticMemory 的 CRUD/FTS/标签操作。"""

from __future__ import annotations

import time

import pytest

from backend.data.database import Database
from backend.memory.semantic import SemanticMemory

pytestmark = pytest.mark.unit


@pytest.fixture  # noqa: PT001 — 兼容 CI ruff 0.15.x (偏好无括号)
def semantic(tmp_db_path: str) -> SemanticMemory:
    db = Database(db_path=tmp_db_path)
    db.init_db()
    return SemanticMemory(db)


def test_save_returns_id_and_persists(semantic: SemanticMemory) -> None:
    mid = semantic.save("python is great", summary="lang", tags=["lang", "py"])
    assert mid
    rec = semantic.get_by_id(mid)
    assert rec is not None
    assert rec["content"] == "python is great"
    assert rec["summary"] == "lang"
    assert "py" in rec["tags"]


def test_save_auto_generates_summary_for_long_content(semantic: SemanticMemory) -> None:
    text = "abc" * 200
    mid = semantic.save(text)
    rec = semantic.get_by_id(mid)
    assert rec is not None
    assert rec["summary"].endswith("...")


def test_save_short_content_summary_is_full(semantic: SemanticMemory) -> None:
    short = "tiny"
    mid = semantic.save(short)
    rec = semantic.get_by_id(mid)
    assert rec is not None
    assert rec["summary"] == "tiny"


def test_search_with_fts(semantic: SemanticMemory) -> None:
    semantic.save("apple banana cherry")
    semantic.save("dog cat bird")
    results = semantic.search("banana", limit=5)
    assert len(results) >= 1
    assert any("banana" in r["content"] for r in results)


def test_search_empty_query_returns_recent(semantic: SemanticMemory) -> None:
    semantic.save("first")
    semantic.save("second")
    results = semantic.search("", limit=10)
    assert len(results) == 2


def test_search_multi_word_query(semantic: SemanticMemory) -> None:
    semantic.save("python rocks for backend")
    semantic.save("javascript wins in browsers")
    results = semantic.search("python backend", limit=5)
    assert len(results) >= 1


def test_search_like_fallback_path(semantic: SemanticMemory) -> None:
    """显式调用 LIKE 回退路径，覆盖标签过滤。"""
    semantic.save("hello world", tags=["greeting"])
    semantic.save("goodbye", tags=["farewell"])
    results = semantic._search_like("hello", limit=5)
    assert len(results) >= 1
    filtered = semantic._search_like("hello", limit=5, tags=["nope"])
    assert filtered == []


def test_get_recent_orders_newest_first(semantic: SemanticMemory) -> None:
    semantic.save("oldest")
    time.sleep(0.01)
    semantic.save("middle")
    time.sleep(0.01)
    newest_id = semantic.save("newest")
    recent = semantic.get_recent(limit=10)
    assert recent[0]["id"] == newest_id


def test_get_all_alias(semantic: SemanticMemory) -> None:
    semantic.save("one")
    semantic.save("two")
    assert len(semantic.get_all()) == 2


def test_count(semantic: SemanticMemory) -> None:
    assert semantic.count() == 0
    semantic.save("x")
    semantic.save("y")
    assert semantic.count() == 2


def test_delete_existing(semantic: SemanticMemory) -> None:
    mid = semantic.save("to delete")
    assert semantic.delete(mid) is True
    assert semantic.get_by_id(mid) is None


def test_delete_unknown_returns_false(semantic: SemanticMemory) -> None:
    assert semantic.delete("missing") is False


def test_update_tags(semantic: SemanticMemory) -> None:
    mid = semantic.save("tagged", tags=["a"])
    assert semantic.update_tags(mid, ["b", "c"]) is True
    rec = semantic.get_by_id(mid)
    assert rec is not None
    assert set(rec["tags"]) == {"b", "c"}


def test_update_tags_missing_id(semantic: SemanticMemory) -> None:
    assert semantic.update_tags("missing", ["x"]) is False


def test_get_by_id_missing(semantic: SemanticMemory) -> None:
    assert semantic.get_by_id("nope") is None


def test_prepare_fts_query_handles_empty() -> None:
    sm = SemanticMemory.__new__(SemanticMemory)
    assert sm._prepare_fts_query("") == '""'
    assert "OR" in sm._prepare_fts_query("a b")
