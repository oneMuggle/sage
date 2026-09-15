"""classify_memory_type 统一分类函数 + MemoryManager session 感知集成测试（WS-A）。

覆盖:
- 模块级 classify_memory_type 规则（显式类型透传 / auto 三分支 / 边界值）
- MemoryManager._classify_memory_type 私有包装与模块级函数一致
- memorize(memory_type='working') 返回合成 id ``wm:<session>:<seq>``
- search_memories 并入工作记忆条目（memory_type='working', source='working_memory'）
- search_memories / memorize 的 session 隔离
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from backend.memory.manager import MemoryManager, classify_memory_type
from backend.memory.working import WorkingMemory

pytestmark = pytest.mark.unit


# ==================== classify_memory_type 规则 ====================


def test_explicit_type_passthrough() -> None:
    """显式指定的非 auto 类型原样返回，不受 importance/content 影响。"""
    assert classify_memory_type("working", 9, "anything") == "working"
    assert classify_memory_type("episodic", 10, "x") == "episodic"
    assert classify_memory_type("semantic", 1, "x") == "semantic"


def test_auto_high_importance_goes_semantic() -> None:
    assert classify_memory_type("auto", 8, "任意内容") == "semantic"
    assert classify_memory_type("auto", 10, "任意内容") == "semantic"


def test_auto_short_low_importance_goes_working() -> None:
    assert classify_memory_type("auto", 4, "短内容") == "working"
    assert classify_memory_type("auto", 1, "x" * 199) == "working"


def test_auto_default_goes_episodic() -> None:
    # 中等重要性短内容
    assert classify_memory_type("auto", 5, "短内容") == "episodic"
    # 长内容即使低重要性
    assert classify_memory_type("auto", 3, "x" * 200) == "episodic"
    # 高重要性门槛以下 + 长内容
    assert classify_memory_type("auto", 7, "x" * 300) == "episodic"


def test_auto_boundary_values() -> None:
    """边界：importance==8 → semantic；len==200 → episodic；len==199 且 imp==4 → working。"""
    assert classify_memory_type("auto", 8, "x") == "semantic"
    assert classify_memory_type("auto", 7, "x" * 200) == "episodic"
    assert classify_memory_type("auto", 4, "x" * 199) == "working"
    assert classify_memory_type("auto", 4, "x" * 200) == "episodic"


def test_manager_private_wrapper_consistent() -> None:
    """MemoryManager._classify_memory_type 与模块级函数结果一致（同一规则的薄包装）。"""
    mgr = MemoryManager.__new__(MemoryManager)
    samples = [(9, "abc"), (2, "short"), (5, "x" * 300), (4, "x" * 100), (8, "y" * 250)]
    for importance, content in samples:
        assert mgr._classify_memory_type(content, importance) == classify_memory_type(
            "auto", importance, content
        )


# ==================== MemoryManager session 感知集成 ====================


@pytest.fixture()
def manager() -> MemoryManager:
    """真实 WorkingMemory + Mock episodic/semantic（本测试只关注 working 路径）。"""
    episodic = Mock()
    semantic = Mock()
    episodic.search.return_value = []
    semantic.search.return_value = []
    return MemoryManager(working=WorkingMemory(), episodic=episodic, semantic=semantic)


def test_memorize_working_returns_synthetic_id(manager: MemoryManager) -> None:
    """memorize(memory_type='working') 不再返回 None，而是合成 id wm:<session>:<seq>。"""
    mid1 = manager.memorize("临时笔记", memory_type="working")
    assert mid1 == "wm:default:1"

    mid2 = manager.memorize("第二条", memory_type="working")
    assert mid2 == "wm:default:2"

    mid_s1 = manager.memorize("会话1的笔记", memory_type="working", session_id="s1")
    assert mid_s1 == "wm:s1:1"  # per-session 独立计数


def test_memorize_working_auto_classified_returns_id(manager: MemoryManager) -> None:
    """auto 分类到 working 的路径同样返回合成 id。"""
    mid = manager.memorize("short low", memory_type="auto", importance=3)
    assert mid == "wm:default:1"
    assert len(manager.working.get_context()) == 1


def test_memorize_working_session_isolation(manager: MemoryManager) -> None:
    """写入 s1 的工作记忆不出现在 s2 的上下文中。"""
    manager.memorize("给 s1 的内容", memory_type="working", session_id="s1")

    assert [m["content"] for m in manager.working.get_context("s1")] == ["给 s1 的内容"]
    assert manager.working.get_context("s2") == []


def test_memorize_episodic_passes_session_id(manager: MemoryManager) -> None:
    """episodic 分支把 session_id 透传给 episodic.save。"""
    manager.memorize("x" * 250, memory_type="episodic", importance=5, session_id="s9")

    call_kwargs = manager.episodic.save.call_args[1]
    assert call_kwargs["session_id"] == "s9"


def test_search_includes_working_entries(manager: MemoryManager) -> None:
    """search_memories(memory_type=None) 并入当前 session 的工作记忆条目并打标。"""
    manager.add_to_working("user", "find me please")
    manager.add_to_working("user", "无关消息")

    results = manager.search_memories("find")

    working_hits = [r for r in results if r.get("memory_type") == "working"]
    assert len(working_hits) == 1
    assert working_hits[0]["content"] == "find me please"
    assert working_hits[0]["source"] == "working_memory"
    assert working_hits[0]["id"] == "wm:default:1"


def test_search_working_type_only(manager: MemoryManager) -> None:
    """memory_type='working' 只返回工作记忆条目（带标记）。"""
    manager.add_to_working("user", "find me")

    results = manager.search_memories("find", memory_type="working")

    assert len(results) == 1
    assert results[0]["memory_type"] == "working"
    assert results[0]["source"] == "working_memory"


def test_search_working_session_scoped(manager: MemoryManager) -> None:
    """search_memories 的 working 并入按 session_id 隔离。"""
    manager.add_to_working("user", "find me", session_id="s1")

    # s2 看不到 s1 的工作记忆（episodic/semantic mock 返回空）
    assert manager.search_memories("find", session_id="s2") == []

    # s1 可以看到
    results = manager.search_memories("find", session_id="s1")
    assert len(results) == 1
    assert results[0]["content"] == "find me"


def test_recall_working_session_scoped(manager: MemoryManager) -> None:
    """recall 的 working 检索按 session_id 隔离。"""
    manager.add_to_working("user", "alpha question", session_id="sA")

    results_a = manager.recall("alpha", session_id="sA")
    assert len(results_a["working"]) == 1

    results_b = manager.recall("alpha", session_id="sB")
    assert results_b["working"] == []


def test_compress_only_clears_target_session(manager: MemoryManager) -> None:
    """compress(session_id) 只压缩并清空指定会话的工作记忆。"""
    manager.add_to_working("user", "session A 的消息", session_id="sA")
    manager.add_to_working("user", "session B 的消息", session_id="sB")

    manager.compress(session_id="sA")

    assert manager.working.get_context("sA") == []
    assert [m["content"] for m in manager.working.get_context("sB")] == ["session B 的消息"]
    # 摘要存入 episodic 且带 session_id
    call_kwargs = manager.episodic.save.call_args[1]
    assert call_kwargs["session_id"] == "sA"
    assert "对话摘要" in call_kwargs["content"]
