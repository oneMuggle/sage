"""验证 MemoryManager 统一管理三层记忆。"""

from __future__ import annotations

import pytest

from backend.data.database import Database
from backend.memory.episodic import EpisodicMemory
from backend.memory.manager import MemoryManager
from backend.memory.semantic import SemanticMemory
from backend.memory.working import WorkingMemory

pytestmark = pytest.mark.unit


@pytest.fixture()
def manager(tmp_db_path: str) -> MemoryManager:
    db = Database(db_path=tmp_db_path)
    db.init_db()
    return MemoryManager(
        working=WorkingMemory(max_size=10, max_tokens=2000),
        episodic=EpisodicMemory(db),
        semantic=SemanticMemory(db),
    )


def test_init_holds_three_layers(manager: MemoryManager) -> None:
    assert isinstance(manager.working, WorkingMemory)
    assert isinstance(manager.episodic, EpisodicMemory)
    assert isinstance(manager.semantic, SemanticMemory)


def test_remember_stores_in_episodic(manager: MemoryManager) -> None:
    mid = manager.remember("simple fact")
    assert mid
    found = manager.episodic.get_by_id(mid)
    assert found is not None
    assert found["content"] == "simple fact"


def test_remember_with_metadata(manager: MemoryManager) -> None:
    mid = manager.remember(
        "session-bound",
        metadata={"importance": 9, "session_id": "sx", "memory_type": "note"},
    )
    found = manager.episodic.get_by_id(mid)
    assert found is not None
    assert found["importance"] == 9
    assert found["session_id"] == "sx"
    assert found["memory_type"] == "note"


def test_memorize_auto_high_importance_goes_to_semantic(manager: MemoryManager) -> None:
    mid = manager.memorize("key fact", memory_type="auto", importance=9)
    assert mid is not None
    assert manager.semantic.get_by_id(mid) is not None


def test_memorize_auto_low_importance_short_goes_to_working(
    manager: MemoryManager,
) -> None:
    mid = manager.memorize("short low", memory_type="auto", importance=3)
    assert mid is None
    assert len(manager.working.messages) == 1


def test_memorize_auto_default_goes_to_episodic(manager: MemoryManager) -> None:
    long_text = "x" * 250
    mid = manager.memorize(long_text, memory_type="auto", importance=5)
    assert mid is not None
    assert manager.episodic.get_by_id(mid) is not None


def test_memorize_explicit_episodic_with_tags(manager: MemoryManager) -> None:
    mid = manager.memorize("tagged ep", memory_type="episodic", importance=5, tags=["t1"])
    assert mid is not None
    rec = manager.episodic.get_by_id(mid)
    assert rec is not None
    assert "t1" in rec["tags"]


def test_memorize_explicit_semantic(manager: MemoryManager) -> None:
    mid = manager.memorize("sem", memory_type="semantic", tags=["s"])
    assert mid is not None
    assert manager.semantic.get_by_id(mid) is not None


def test_memorize_unknown_type_returns_none(manager: MemoryManager) -> None:
    assert manager.memorize("nope", memory_type="unknown_kind") is None


def test_recall_returns_dict_of_lists(manager: MemoryManager) -> None:
    manager.add_to_working("user", "alpha question")
    manager.episodic.save("alpha episode")
    manager.semantic.save("alpha knowledge")

    results = manager.recall("alpha", limit=5)
    assert set(results.keys()) == {"working", "episodic", "semantic"}
    assert len(results["working"]) >= 1
    assert len(results["episodic"]) >= 1
    assert len(results["semantic"]) >= 1


def test_recall_filtered_types(manager: MemoryManager) -> None:
    manager.add_to_working("user", "filter")
    manager.episodic.save("filter ep")
    results = manager.recall("filter", limit=5, memory_types=["working"])
    assert results["working"]
    assert results["episodic"] == []


def test_recall_empty_query_returns_recent_working(manager: MemoryManager) -> None:
    manager.add_to_working("user", "one")
    manager.add_to_working("user", "two")
    results = manager.recall("", limit=5, memory_types=["working"])
    assert len(results["working"]) >= 1


def test_get_context_combines_all(manager: MemoryManager) -> None:
    manager.add_to_working("user", "hi")
    manager.episodic.save("episode A")
    manager.semantic.save("knowledge B")
    ctx = manager.get_context(limit=5)
    assert "当前对话" in ctx
    assert "相关经历" in ctx
    assert "相关知识" in ctx


def test_get_context_empty_returns_empty_string(manager: MemoryManager) -> None:
    assert manager.get_context() == ""


def test_compress_moves_working_to_episodic(manager: MemoryManager) -> None:
    manager.add_to_working("user", "hello")
    manager.add_to_working("assistant", "world")
    manager.compress()
    assert len(manager.working.messages) == 0
    recent = manager.episodic.get_recent(limit=5)
    assert any("对话摘要" in r["content"] for r in recent)


def test_compress_noop_when_empty(manager: MemoryManager) -> None:
    manager.compress()
    assert manager.episodic.count() == 0


def test_add_to_working(manager: MemoryManager) -> None:
    manager.add_to_working("user", "hi")
    assert manager.working.messages[0]["role"] == "user"
    assert manager.working.messages[0]["content"] == "hi"


def test_search_memories_episodic(manager: MemoryManager) -> None:
    manager.episodic.save("zebra")
    results = manager.search_memories("zebra", memory_type="episodic")
    assert len(results) >= 1


def test_search_memories_semantic(manager: MemoryManager) -> None:
    manager.semantic.save("zebra concept")
    results = manager.search_memories("zebra", memory_type="semantic")
    assert len(results) >= 1


def test_search_memories_working(manager: MemoryManager) -> None:
    manager.add_to_working("user", "find me")
    results = manager.search_memories("find", memory_type="working")
    assert len(results) >= 1


def test_search_memories_all(manager: MemoryManager) -> None:
    manager.episodic.save("alpha ep")
    manager.semantic.save("alpha sm")
    results = manager.search_memories("alpha")
    assert len(results) >= 2


def test_delete_memory_episodic(manager: MemoryManager) -> None:
    mid = manager.episodic.save("to del")
    assert manager.delete_memory(mid, "episodic") is True


def test_delete_memory_semantic(manager: MemoryManager) -> None:
    mid = manager.semantic.save("to del s")
    assert manager.delete_memory(mid, "semantic") is True


def test_delete_memory_unknown_type(manager: MemoryManager) -> None:
    assert manager.delete_memory("any", "unknown") is False


def test_get_stats(manager: MemoryManager) -> None:
    manager.add_to_working("user", "x")
    manager.episodic.save("ep")
    manager.semantic.save("sm")
    stats = manager.get_stats()
    assert stats["working"]["message_count"] == 1
    assert stats["episodic"]["total"] == 1
    assert stats["semantic"]["total"] == 1


def test_classify_high_importance() -> None:
    mgr = MemoryManager.__new__(MemoryManager)
    assert mgr._classify_memory_type("abc", 9) == "semantic"


def test_classify_low_importance_short() -> None:
    mgr = MemoryManager.__new__(MemoryManager)
    assert mgr._classify_memory_type("short", 2) == "working"


def test_classify_default_episodic() -> None:
    mgr = MemoryManager.__new__(MemoryManager)
    assert mgr._classify_memory_type("x" * 300, 5) == "episodic"
