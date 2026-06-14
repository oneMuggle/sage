"""持久化端口（消息、会话、记忆等）。

定义 ``backend.data.*`` 仓储层之上的抽象接口，由
``backend.adapters.storage.sqlite``（SqliteStorageAdapter）
与 ``backend.adapters.storage.memory``（MemoryStorageAdapter，
仅用于测试）实现。
"""

from typing import Any, Protocol

from backend.domain.message import Message


class StoragePort(Protocol):
    """数据持久化端口。

    方法命名沿用既有仓储语义（``append_message`` / ``get_messages``
    / ``create_session`` / ``list_sessions`` / ``delete_session``），
    实现层负责把 domain ``Message`` 与底层行表示互转。
    """

    async def append_message(self, session_id: str, message: Message) -> None:
        """向会话追加一条消息。"""
        ...

    async def get_messages(
        self,
        session_id: str,
        limit: int = 50,
    ) -> list[Message]:
        """按时间正序获取会话的最新若干条消息。"""
        ...

    async def create_session(self, title: str = "") -> str:
        """创建新会话，返回会话 ID。"""
        ...

    async def list_sessions(self) -> list[dict[str, Any]]:
        """列出当前所有会话（字典形式，键集由实现定义）。"""
        ...

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """按 ID 取单个会话；不存在返 ``None``（路由层映射 404）。"""
        ...

    async def update_session(self, session_id: str, **fields: Any) -> int:
        """局部更新会话字段；返受影响行数（0 = 会话不存在, 1 = 已更新）。"""
        ...

    async def delete_session(self, session_id: str) -> int:
        """按 ID 删除会话（级联消息由实现侧负责）；返受影响行数。"""
        ...
