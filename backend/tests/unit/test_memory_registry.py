"""验证 MemoryManager 全局单例注册表。"""

from __future__ import annotations

import pytest

from backend.memory import get_memory_manager, reset_memory_manager
from backend.memory.manager import MemoryManager

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_singleton():
    """每个测试前后重置单例，确保测试隔离。"""
    reset_memory_manager()
    yield
    reset_memory_manager()


def test_get_memory_manager_returns_singleton() -> None:
    """多次调用应返回同一实例。"""
    mm1 = get_memory_manager()
    mm2 = get_memory_manager()
    assert mm1 is mm2


def test_get_memory_manager_returns_memory_manager() -> None:
    """返回值应为 MemoryManager 实例。"""
    mm = get_memory_manager()
    assert isinstance(mm, MemoryManager)


def test_singleton_preserves_working_memory() -> None:
    """单例确保 WorkingMemory 跨调用保持状态。"""
    mm1 = get_memory_manager()
    mm1.working.add({"role": "user", "content": "测试消息"})

    mm2 = get_memory_manager()
    assert len(mm2.working.messages) == 1
    assert mm2.working.messages[0]["content"] == "测试消息"


def test_reset_clears_singleton() -> None:
    """reset_memory_manager() 后应创建新实例。"""
    mm1 = get_memory_manager()
    mm1.working.add({"role": "user", "content": "旧消息"})

    reset_memory_manager()

    mm2 = get_memory_manager()
    assert mm1 is not mm2
    assert len(mm2.working.messages) == 0
