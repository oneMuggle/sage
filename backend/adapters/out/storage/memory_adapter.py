"""内存存储 adapter(单元/集成测试用)。

实现 StoragePort 的纯 in-memory 版本,不写磁盘、不依赖 SQLite,用于:
- 单元测试中替换 SqliteStorageAdapter,避免数据库依赖
- 未来 e2e/integration 跑无数据库环境时快速 mock

PR B §1.2 设计要点
-------------------
- 所有 async 方法包 asyncio.to_thread(与 SqliteStorageAdapter 同形)
- **不加锁**(纯内存 dict 操作,无并发问题)
- 内存操作 μs 级,但仍包 to_thread 保持接口一致性、未来若换 redis
  后端同样行为、单测仍能断言"真在 thread 跑"

其他要点
--------
- 会话存储为 dict[session_id, _SessionState],每会话内消息按追加顺序保存。
- get_messages(limit) 返回"最后" limit 条且保持时间正序。
- create_session 生成 ID 形如 mem-<uuid4>,避免与真实 UUID 格式冲突。
  (原自增计数器实现有 RMW 竞态:`self._counter += 1` 是 4 条字节码,
  GIL 可在中间切换,两个 to_thread worker 会拿到同一个值并产出重复 ID。)
- delete_session 级联清理该会话的所有消息。
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List

from sage_core import Message
from sage_core.repositories import StoragePort  # noqa: F401  (structural typing target)


@dataclass
class _SessionState:
    """单会话的内存状态。"""

    title: str = ""
    messages: List[Message] = field(default_factory=list)


class MemoryStorageAdapter:
    """StoragePort 的纯 in-memory 实现。

    PR B §1.2: 所有方法用 asyncio.to_thread 包装,无锁。
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, _SessionState] = {}

    # ----- 会话 -----

    async def create_session(self, title: str = "") -> str:
        return await asyncio.to_thread(self._sync_create_session, title)

    def _sync_create_session(self, title: str) -> str:
        # PR B §1.2 (HIGH fix): 用 uuid4 而非自增计数器 —— `self._counter += 1`
        # 的 read-modify-write 不是原子操作,并发 to_thread worker 会产出重复 ID。
        session_id = f"mem-{uuid.uuid4()}"
        self._sessions[session_id] = _SessionState(title=title)
        return session_id

    async def list_sessions(self) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self._sync_list_sessions)

    def _sync_list_sessions(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": sid,
                "title": state.title,
                "message_count": len(state.messages),
            }
            for sid, state in self._sessions.items()
        ]

    async def get_session(self, session_id: str) -> Dict[str, Any] | None:
        return await asyncio.to_thread(self._sync_get_session, session_id)

    def _sync_get_session(self, session_id: str) -> Dict[str, Any] | None:
        state = self._sessions.get(session_id)
        if state is None:
            return None
        return {
            "id": session_id,
            "title": state.title,
            "message_count": len(state.messages),
        }

    async def update_session(self, session_id: str, **fields: Any) -> int:
        return await asyncio.to_thread(self._sync_update_session, session_id, fields)

    def _sync_update_session(self, session_id: str, fields: Dict[str, Any]) -> int:
        state = self._sessions.get(session_id)
        if state is None:
            return 0
        if "title" in fields and fields["title"] is not None:
            state.title = fields["title"]
        return 1

    async def delete_session(self, session_id: str) -> int:
        return await asyncio.to_thread(self._sync_delete_session, session_id)

    def _sync_delete_session(self, session_id: str) -> int:
        existed = session_id in self._sessions
        self._sessions.pop(session_id, None)
        return 1 if existed else 0

    # ----- 消息 -----

    async def append_message(self, session_id: str, message: Message) -> str:
        return await asyncio.to_thread(self._sync_append_message, session_id, message)

    def _sync_append_message(self, session_id: str, message: Message) -> str:
        if session_id not in self._sessions:
            self._sessions[session_id] = _SessionState(title="")
        self._sessions[session_id].messages.append(message)
        return str(uuid.uuid4())

    async def get_messages(
        self,
        session_id: str,
        limit: int = 50,
    ) -> List[Message]:
        return await asyncio.to_thread(self._sync_get_messages, session_id, limit)

    def _sync_get_messages(self, session_id: str, limit: int) -> List[Message]:
        state = self._sessions.get(session_id)
        if state is None:
            return []
        if limit <= 0:
            return []
        return list(state.messages[-limit:])
