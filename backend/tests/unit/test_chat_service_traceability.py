"""Gap E fix round — source_message_id must point at a real stored message id.

End-to-end contract: ChatService.run_turn → extract → memory.store must set
``source_message_id`` to the ACTUAL persisted message id (the one Chat renders
as ``data-turn-id={message.id}``), so the MemoryCard traceability link can
scroll-and-highlight the producing message instead of being a silent no-op.

Asserts on the real SQLite DB row (conftest temp DB) — not a mock.
"""

from unittest.mock import AsyncMock, Mock

import pytest
from sage_core import Message, Role

from backend.adapters.out.memory.adapter import MemoryAdapter
from backend.adapters.out.storage.sqlite_adapter import SqliteStorageAdapter
from backend.application.services.chat_service import ChatService
from backend.data.session_repo import MessageRepository
from backend.memory import get_memory_manager

pytestmark = pytest.mark.unit


@pytest.fixture()
def real_chat_service():
    """ChatService backed by the real SqliteStorageAdapter + real MemoryAdapter
    (conftest autouse fixture provides a fresh temp DB per test)."""
    storage = SqliteStorageAdapter()
    memory = MemoryAdapter(get_memory_manager())

    llm = Mock()
    llm.chat = AsyncMock(
        side_effect=[
            # 主对话回复（assistant，落库）
            Message(
                role=Role.ASSISTANT,
                content="好的，我记住了，用户喜欢吃火锅，特别是四川麻辣口味。" + "x" * 30,
            ),
            # 事实提取（JSON 字符串，新词表）
            Message(
                role=Role.ASSISTANT,
                content='[{"content":"用户喜欢吃火锅","importance":7,"category":"user_pref","tags":["火锅"]}]',
            ),
        ]
    )

    tools = Mock()
    tools.list_tools = Mock(return_value=[])
    metrics = Mock()
    metrics.counter = Mock()
    metrics.histogram = Mock()
    metrics.gauge = Mock()
    events = Mock()
    events.emit = Mock()

    service = ChatService(
        llm=llm,
        tools=tools,
        skills=None,
        storage=storage,
        metrics=metrics,
        events=events,
        memory=memory,
    )
    return service, storage, memory


@pytest.mark.asyncio()
async def test_source_message_id_is_real_stored_message_id(real_chat_service):
    """extract → store → the stored memory's source_message_id must equal a
    message id that actually exists in the messages table (the assistant reply)."""
    service, storage, _memory = real_chat_service

    session_id = await storage.create_session(title="traceability")
    user_content = (
        "我喜欢吃火锅，请推荐四川口味的火锅店。麻辣锅底最佳，最好在市中心。" + "x" * 20
    )
    user_message = Message(role=Role.USER, content=user_content)
    await service.run_turn(session_id, user_message)

    # 1) 记忆已落库（episodic + user_pref）
    rows = get_memory_manager().episodic.find_by_category("user_pref")
    assert len(rows) == 1, f"expected 1 user_pref memory, got {len(rows)}"
    smid = rows[0]["source_message_id"]
    assert smid, "source_message_id must be populated on the real DB row"
    assert rows[0]["source_turn_id"], "source_turn_id must remain populated"

    # 2) source_message_id 必须是 messages 表中真实存在的 assistant 消息 id
    msgs = MessageRepository().get_by_session(session_id, limit=100, offset=0)
    stored_ids = [m.id for m in msgs]
    assert smid in stored_ids, f"source_message_id {smid!r} not among stored messages {stored_ids}"

    assistant_ids = [m.id for m in msgs if m.role == "assistant"]
    assert smid in assistant_ids, (
        f"source_message_id {smid!r} should point at the assistant reply, got {assistant_ids}"
    )
