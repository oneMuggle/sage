"""Memory Registry - 全局 MemoryManager 单例注册表

解决之前每次请求/任务都新建 MemoryManager 导致 WorkingMemory 永远为空的问题。
所有需要 MemoryManager 的地方（legacy_routes、main.py、evolution）都通过此模块获取同一实例。
"""

from __future__ import annotations

import logging
from typing import Optional

from backend.data.database import get_database
from backend.memory.episodic import EpisodicMemory
from backend.memory.manager import MemoryManager
from backend.memory.semantic import SemanticMemory
from backend.memory.working import WorkingMemory

logger = logging.getLogger(__name__)

_memory_manager: Optional[MemoryManager] = None


def get_memory_manager() -> MemoryManager:
    """获取全局 MemoryManager 单例

    首次调用时创建实例，后续调用返回同一实例。
    这保证了 WorkingMemory 跨请求持久存在。

    Returns:
        MemoryManager: 全局共享的记忆管理器实例
    """
    global _memory_manager
    if _memory_manager is None:
        db = get_database()
        _memory_manager = MemoryManager(
            working=WorkingMemory(max_size=20, max_tokens=4000, db=db),
            episodic=EpisodicMemory(db),
            semantic=SemanticMemory(db),
        )
        logger.info("全局 MemoryManager 单例已创建（WorkingMemory 持久化已启用）")
    return _memory_manager


def reset_memory_manager() -> None:
    """重置 MemoryManager 单例（仅用于测试）"""
    global _memory_manager
    _memory_manager = None
