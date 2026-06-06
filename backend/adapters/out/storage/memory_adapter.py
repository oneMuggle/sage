"""内存存储 adapter（单元/集成测试用）。

实现 ``StoragePort`` 的纯 in-memory 版本，不写磁盘、不依赖 SQLite，
用于：

- 单元测试中替换 ``SqliteStorageAdapter``，避免数据库依赖
- 未来 e2e/integration 跑无数据库环境时快速 mock

设计要点
--------

- 会话存储为 ``dict[session_id, _SessionState]``，每会话内消息按追加顺序保存。
- ``get_messages(limit)`` 返回**最后** ``limit`` 条且保持时间正序，便于
  喂给 LLM 时按"最新上下文"语义取窗口。
- ``create_session`` 计数器自增 ID 形如 ``mem-1`` / ``mem-2``，避免与真实
  UUID 格式冲突，便于在测试中断言。
- ``delete_session`` 级联清理该会话的所有消息。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.domain.message import Message
from backend.ports.storage import StoragePort  # noqa: F401  (structural typing target)


@dataclass
class _SessionState:
    """单会话的内存状态。"""

    title: str = ""
    messages: list[Message] = field(default_factory=list)


class MemoryStorageAdapter:
    """``StoragePort`` 的纯 in-memory 实现。

    采用结构化子类型（structural typing）：不显式继承 ``StoragePort``，
    仅通过方法签名匹配来满足协议。
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _SessionState] = {}
        self._counter: int = 0

    # ----- 会话 -----

    async def create_session(self, title: str = "") -> str:
        self._counter += 1
        session_id = f"mem-{self._counter}"
        self._sessions[session_id] = _SessionState(title=title)
        return session_id

    async def list_sessions(self) -> list[dict[str, Any]]:
        return [
            {
                "id": sid,
                "title": state.title,
                "message_count": len(state.messages),
            }
            for sid, state in self._sessions.items()
        ]

    async def delete_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    # ----- 消息 -----

    async def append_message(self, session_id: str, message: Message) -> None:
        if session_id not in self._sessions:
            # 自动建会话（与既有 api 行为兼容：append 未知 session 不报错）
            self._sessions[session_id] = _SessionState(title="")
        self._sessions[session_id].messages.append(message)

    async def get_messages(
        self,
        session_id: str,
        limit: int = 50,
    ) -> list[Message]:
        state = self._sessions.get(session_id)
        if state is None:
            return []
        if limit <= 0:
            return []
        return list(state.messages[-limit:])
