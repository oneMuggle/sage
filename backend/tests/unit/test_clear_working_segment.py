"""回归 (2026-09-18): 段级清空必须清到 **共享** 工作记忆实例。

历史缺陷：``legacy_routes`` 的 context_reset / 自动话题切换分支写成
``WorkingMemory().clear_segment(...)``。``WorkingMemory`` 是普通类
（无单例、无 ``__new__`` 覆盖），``WorkingMemory()`` 构造的是**全新的空
实例**，``clear_segment`` 遍历空 deque → 整个调用是空操作。

真实实例由 ``agent.memory_manager.working`` 持有（同一个实例也是
legacy_routes L13 记忆注入块的读取源）。这些用例若拿旧实现跑会失败。
"""
from unittest.mock import MagicMock

from backend.api.legacy_routes import _clear_working_segment
from backend.memory.manager import MemoryManager
from backend.memory.working import WorkingMemory


def _manager() -> MemoryManager:
    """真实 WorkingMemory（无 db → 纯内存），episodic/semantic 用桩。"""
    return MemoryManager(
        WorkingMemory(max_size=20, max_tokens=4000),
        MagicMock(),
        MagicMock(),
    )


def _agent(manager: MemoryManager) -> MagicMock:
    agent = MagicMock()
    agent.memory_manager = manager
    return agent


def test_clear_working_segment_clears_only_target_segment():
    """只清 (session, segment) 命中的消息，其他段/其他会话不受影响。"""
    manager = _manager()
    working = manager.working

    working.add("s1", {"role": "user", "content": "old-topic"}, segment_id=0)
    working.add("s1", {"role": "assistant", "content": "old-reply"}, segment_id=0)
    working.add("s1", {"role": "user", "content": "new-topic"}, segment_id=1)
    working.add("s2", {"role": "user", "content": "other-session"}, segment_id=0)

    _clear_working_segment(_agent(manager), "s1", 0)

    assert [m["content"] for m in working.get_context("s1")] == ["new-topic"]
    # 另一会话的段 0 未被误伤
    assert [m["content"] for m in working.get_context("s2")] == ["other-session"]


def test_clear_reflects_on_instance_held_by_agent():
    """守卫：清空结果必须能在 agent.memory_manager.working 上复查到。

    旧实现构造一次性实例，``manager.working`` 上的残留会存活 → 本断言失败。
    """
    manager = _manager()
    manager.working.add("s1", {"role": "user", "content": "stale"}, segment_id=0)

    _clear_working_segment(_agent(manager), "s1", 0)

    assert manager.working.get_context("s1", segment_id=0) == []


def test_clear_working_segment_noop_without_memory_manager():
    """bare agent（memory_manager=None）静默跳过，不抛异常。"""
    agent = MagicMock()
    agent.memory_manager = None

    _clear_working_segment(agent, "s1", 0)
