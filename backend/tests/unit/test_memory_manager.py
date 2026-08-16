"""验证 MemoryManager 统一管理三层记忆。"""

from __future__ import annotations

import asyncio
import threading

import pytest

from backend.data.database import Database
from backend.memory.episodic import EpisodicMemory
from backend.memory.manager import MemoryManager
from backend.memory.semantic import SemanticMemory
from backend.memory.working import WorkingMemory
from backend.tests.conftest import ensure_session

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
    # §1.3a: FK enforcement — parent session row must exist.
    ensure_session(manager.episodic.db, "sx")
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


# ----------------------------------------------------------------------------
# Task 4 / Gap A — async remember() threads traceability through to episodic.
# ----------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_remember_threads_source_turn_id(manager: MemoryManager) -> None:
    """aremember() must persist source_turn_id on the episodic row."""
    ensure_session(manager.episodic.db, "sess-1")
    mid = await manager.aremember(
        "user prefers tea",
        session_id="sess-1",
        source_turn_id="turn-7",
    )
    found = manager.episodic.get_by_id(mid)
    assert found is not None
    assert found["source_turn_id"] == "turn-7"


@pytest.mark.asyncio()
async def test_remember_threads_memory_category(manager: MemoryManager) -> None:
    """aremember() must persist memory_category on the episodic row."""
    ensure_session(manager.episodic.db, "sess-1")
    mid = await manager.aremember(
        "用户偏好咖啡",
        session_id="sess-1",
        memory_category="user_pref",
    )
    found = manager.episodic.get_by_id(mid)
    assert found is not None
    assert found["memory_category"] == "user_pref"


@pytest.mark.asyncio()
async def test_remember_threads_all_traceability(manager: MemoryManager) -> None:
    """All three traceability fields pass through in one call."""
    ensure_session(manager.episodic.db, "sess-1")
    mid = await manager.aremember(
        "user mentioned azure on a friday",
        session_id="sess-1",
        source_turn_id="turn-9",
        source_message_id="msg-3",
        memory_category="cross_session_pattern",
    )
    found = manager.episodic.get_by_id(mid)
    assert found is not None
    assert found["source_turn_id"] == "turn-9"
    assert found["source_message_id"] == "msg-3"
    assert found["memory_category"] == "cross_session_pattern"


# ----------------------------------------------------------------------------
# Code review fix — aremember() must not block the event loop.
#
# EpisodicMemory.save() is a synchronous SQLite INSERT; if aremember() awaited
# it directly on the asyncio thread, a slow disk fsync would stall the entire
# event loop. The fix wraps save() in ``asyncio.to_thread`` and re-acquires
# the DB connection *inside* the worker thread so the existing
# ``check_same_thread=False`` / single-connection contract is preserved.
#
# These tests prove the implementation actually off-loads the work to a
# worker thread (the synchronous save() must NOT run on the event loop
# thread that owns the awaiting coroutine).
# ----------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_aremember_does_not_block_event_loop(
    manager: MemoryManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """aremember() must not run EpisodicMemory.save on the event-loop thread.

    We monkey-patch EpisodicMemory.save with a probe that records the
    thread it is invoked on, then assert the thread is different from the
    asyncio event loop's thread.
    """

    event_loop_thread_id = threading.get_ident()
    save_thread_id: dict[str, int | None] = {"value": None}
    original_save = manager.episodic.save

    def _probe_save(*args, **kwargs):
        save_thread_id["value"] = threading.get_ident()
        return original_save(*args, **kwargs)

    monkeypatch.setattr(manager.episodic, "save", _probe_save)
    # The rebinding on the instance is sufficient because Python attribute
    # lookup walks the instance dict before the class.

    # Yield control to the loop so the captured thread id is the loop's.
    await asyncio.sleep(0)

    ensure_session(manager.episodic.db, "probe-sess")
    mid = await manager.aremember(
        "non-blocking probe",
        session_id="probe-sess",
        source_turn_id="probe-turn",
    )

    assert mid, "aremember should return a memory id"
    assert save_thread_id["value"] is not None, "save was never called"
    assert save_thread_id["value"] != event_loop_thread_id, (
        "EpisodicMemory.save ran on the event-loop thread; "
        "aremember() must wrap it in asyncio.to_thread"
    )


@pytest.mark.asyncio()
async def test_aremember_to_thread_preserves_save_contract(
    manager: MemoryManager,
) -> None:
    """The to_thread wrapper must still persist all fields end-to-end.

    Sanity check: after wrapping in asyncio.to_thread the visible contract
    (memory id returned, row findable, traceability fields populated)
    remains identical to the synchronous ``remember()`` path.
    """
    ensure_session(manager.episodic.db, "wrap-sess")
    mid = await manager.aremember(
        "wrap test",
        session_id="wrap-sess",
        source_turn_id="wrap-turn",
        source_message_id="wrap-msg",
        memory_category="user_pref",
    )
    assert mid
    found = manager.episodic.get_by_id(mid)
    assert found is not None
    assert found["content"] == "wrap test"
    assert found["session_id"] == "wrap-sess"
    assert found["source_turn_id"] == "wrap-turn"
    assert found["source_message_id"] == "wrap-msg"
    assert found["memory_category"] == "user_pref"


# ----------------------------------------------------------------------------
# F2 — MemoryManager gains async consolidate() / snapshot() wrappers so the
# MemoryLifecycleManager (and the session-end watchdog in main.py) can drive
# real consolidation/snapshot without calling methods that don't exist.
# ----------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_consolidate_compresses_working_memory(
    manager: MemoryManager,
) -> None:
    """MemoryManager.consolidate(session_id) compresses working memory into
    episodic (delegates to ConsolidationPipeline) and returns a memory id."""
    ensure_session(manager.episodic.db, "sess-c")
    manager.add_to_working(
        "user", "hello consolidation test message worth remembering"
    )
    memory_id = await manager.consolidate("sess-c")
    assert memory_id is None or isinstance(memory_id, str)
    # working memory cleared after consolidation
    assert len(manager.working.messages) == 0
    # episodic now holds the compressed summary
    recent = manager.episodic.get_recent(limit=5)
    assert len(recent) >= 1
    assert "摘要" in recent[0]["content"] or "对话" in recent[0]["content"]


@pytest.mark.asyncio()
async def test_snapshot_does_not_raise(manager: MemoryManager) -> None:
    """MemoryManager.snapshot(session_id) persists working memory state and
    must not raise even when working memory is empty."""
    await manager.snapshot("sess-s")  # empty working memory — no-op, no raise
    manager.add_to_working("user", "hello snapshot me")
    await manager.snapshot("sess-s")  # must not raise
