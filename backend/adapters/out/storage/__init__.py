"""存储出站适配器。

- ``SqliteStorageAdapter`` ：生产实现，包装 ``backend.data.session_repo``。
- ``MemoryStorageAdapter`` ：纯 in-memory 实现（单元/集成测试用）。
"""

from backend.adapters.out.storage.memory_adapter import MemoryStorageAdapter
from backend.adapters.out.storage.sqlite_adapter import SqliteStorageAdapter

__all__ = ["MemoryStorageAdapter", "SqliteStorageAdapter"]
