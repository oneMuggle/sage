"""M3-Task 4 — 身份贯穿（attribution / wiring）测试。

验收点（plan §M3-Task 4）：
- ``ToolExecutionContext.agent_id`` → Memory 工具透传到 ``memorize`` / ``search_memories``；
- ``ChatService._extract_and_store_memory`` 缺省按 ``resolve_bound_specialist`` 解析；
- 显式 ``agent_id`` 覆盖会话解析；
- 模块级 ``extract_and_store_memory`` 透传 agent_id 到 ``memory_port.store``；
- ``MemoryAdapter.retrieve`` 的可见性过滤按 agent_id ∪ 共享层裁剪（向量召回路径）；
- ``MemoryAdapter.store`` 透传 agent_id 到 ``MemoryManager.memorize``。

与 ``test_memory_agent_isolation.py`` 的区别：
后者覆盖 **存储层** 的 scope × agent_id 矩阵（is_row_visible / SQL 片段本身）；
本文件覆盖 **调用链** 的 agent_id 贯通，两个文件职责正交。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from backend.adapters.out.memory.adapter import MemoryAdapter
from backend.domain.memory import MemoryContext
from backend.domain.message import Message, Role
from backend.ports.memory import MemoryPort

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# 模块级 helper — extract_and_store_memory 透传 agent_id
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio()
async def test_extract_and_store_memory_forwards_agent_id():
    """模块级 helper 必须把调用方传入的 agent_id 原样传递给 memory_port.store。"""
    from backend.application.services.chat_service import extract_and_store_memory

    memory_port = Mock(spec=MemoryPort)
    memory_port.store = AsyncMock(return_value="mem-id")
    extractor = AsyncMock()
    extractor.extract = AsyncMock(
        return_value=[
            {
                "content": "写作偏好：阈值蓝色优先",
                "importance": 6,
                "tags": ["pref"],
                "category": "project_fact",
            }
        ]
    )

    stored = await extract_and_store_memory(
        memory_port=memory_port,
        extractor=extractor,
        user_text="请帮我写报告",
        assistant_text="好的，按蓝色优先处理",
        session_id="session-abc",
        enabled=True,
        agent_id="specialist-writer",
    )

    assert stored >= 1
    call_kwargs = memory_port.store.call_args.kwargs
    assert call_kwargs["agent_id"] == "specialist-writer"
    assert call_kwargs["session_id"] == "session-abc"
    assert call_kwargs["content"] == "写作偏好：阈值蓝色优先"


@pytest.mark.asyncio()
async def test_extract_and_store_memory_none_agent_id_preserved():
    """显式传 None 的 agent_id 必须保持为 None（共享层），不被 helper 内部改写。"""
    from backend.application.services.chat_service import extract_and_store_memory

    memory_port = Mock(spec=MemoryPort)
    memory_port.store = AsyncMock(return_value="mem-shared")
    extractor = AsyncMock()
    extractor.extract = AsyncMock(
        return_value=[
            {
                "content": "共享事实",
                "importance": 5,
                "tags": [],
                "category": "project_fact",
            }
        ]
    )

    await extract_and_store_memory(
        memory_port=memory_port,
        extractor=extractor,
        user_text="a",
        assistant_text="b",
        session_id="session-x",
        enabled=True,
        agent_id=None,
    )

    assert memory_port.store.call_args.kwargs["agent_id"] is None


@pytest.mark.asyncio()
async def test_extract_and_store_memory_disabled_skips_store():
    """enabled=False 时不应调用 memory_port.store（best-effort）。"""
    from backend.application.services.chat_service import extract_and_store_memory

    memory_port = Mock(spec=MemoryPort)
    memory_port.store = AsyncMock()
    extractor = AsyncMock()
    extractor.extract = AsyncMock(return_value=[{"content": "x"}])

    stored = await extract_and_store_memory(
        memory_port=memory_port,
        extractor=extractor,
        user_text="a",
        assistant_text="b",
        session_id="session-x",
        enabled=False,
        agent_id="specialist-writer",
    )

    assert stored == 0
    memory_port.store.assert_not_called()


# --------------------------------------------------------------------------- #
# ChatService._extract_and_store_memory 解析会话专家
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio()
async def test_chat_service_extract_resolves_bound_specialist_when_agent_id_missing():
    """agent_id=None 时按 resolve_bound_specialist(session_id) 自动解析。"""
    from backend.application.services.chat_service import ChatService

    llm = Mock()
    tools = Mock()
    tools.list_tools = Mock(return_value=[])
    storage = Mock()
    storage.append_message = AsyncMock()
    storage.get_messages = AsyncMock(return_value=[])
    metrics = Mock()
    metrics.counter = Mock()
    metrics.histogram = Mock()
    metrics.gauge = Mock()
    events = Mock()
    events.emit = Mock()

    memory = Mock(spec=MemoryPort)
    memory.store = AsyncMock(return_value="mem-id")
    memory.compress = AsyncMock()
    memory.retrieve = AsyncMock(
        return_value=MemoryContext(working=[], episodic=[], semantic=[])
    )

    svc = ChatService(
        llm=llm,
        tools=tools,
        skills=None,
        storage=storage,
        metrics=metrics,
        events=events,
        memory=memory,
    )

    user_message = Message(role=Role.USER, content="我喜欢红色优先")
    assistant_message = Message(role=Role.ASSISTANT, content="收到")

    # 注入 extractor mock：返回一个事实供 store
    # 注意：ChatService._extract_and_store_memory 用**函数内导入**
    # （from backend.memory.extractor import MemoryExtractor），故 patch
    # 目标必须是源模块，不能是 chat_service 的模块属性。
    with patch(
        "backend.memory.extractor.MemoryExtractor"
    ) as MockExtractor:
        inst = MockExtractor.return_value
        inst.extract = AsyncMock(
            return_value=[
                {
                    "content": "红色优先偏好",
                    "importance": 6,
                    "tags": ["pref"],
                    "category": "project_fact",
                }
            ]
        )
        # resolve_bound_specialist 同样是函数内导入 → patch 源模块
        with patch(
            "backend.chat.specialist_binding.resolve_bound_specialist",
            return_value="specialist-writer",
        ) as mock_resolve:
            await svc._extract_and_store_memory(
                session_id="session-xyz",
                user_message=user_message,
                assistant_message=assistant_message,
            )
            mock_resolve.assert_called_once_with("session-xyz")

    assert memory.store.call_args.kwargs["agent_id"] == "specialist-writer"


@pytest.mark.asyncio()
async def test_chat_service_extract_honors_explicit_agent_id():
    """显式 agent_id 优先于会话解析（不被 resolve_bound_specialist 覆盖）。"""
    from backend.application.services.chat_service import ChatService

    llm = Mock()
    tools = Mock()
    tools.list_tools = Mock(return_value=[])
    storage = Mock()
    storage.append_message = AsyncMock()
    storage.get_messages = AsyncMock(return_value=[])
    metrics = Mock()
    metrics.counter = Mock()
    metrics.histogram = Mock()
    metrics.gauge = Mock()
    events = Mock()
    events.emit = Mock()

    memory = Mock(spec=MemoryPort)
    memory.store = AsyncMock(return_value="mem-id")
    memory.compress = AsyncMock()
    memory.retrieve = AsyncMock(
        return_value=MemoryContext(working=[], episodic=[], semantic=[])
    )

    svc = ChatService(
        llm=llm,
        tools=tools,
        skills=None,
        storage=storage,
        metrics=metrics,
        events=events,
        memory=memory,
    )

    user_message = Message(role=Role.USER, content="a")
    assistant_message = Message(role=Role.ASSISTANT, content="b")

    with patch(
        "backend.memory.extractor.MemoryExtractor"
    ) as MockExtractor:
        inst = MockExtractor.return_value
        inst.extract = AsyncMock(
            return_value=[
                {
                    "content": "事实",
                    "importance": 5,
                    "tags": [],
                    "category": "project_fact",
                }
            ]
        )
        # 显式 agent_id → 不应触发会话解析（patch 源模块，因函数内导入）
        with patch(
            "backend.chat.specialist_binding.resolve_bound_specialist"
        ) as mock_resolve:
            await svc._extract_and_store_memory(
                session_id="session-xyz",
                user_message=user_message,
                assistant_message=assistant_message,
                agent_id="specialist-coder",
            )
            # 显式 agent_id → 不应触发会话解析
            mock_resolve.assert_not_called()

    assert memory.store.call_args.kwargs["agent_id"] == "specialist-coder"


# --------------------------------------------------------------------------- #
# MemoryAdapter 可见性过滤 — 跨专家私有行不可见、共享行可见（向量召回路径）
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio()
async def test_adapter_retrieve_filters_cross_agent_vector_hits():
    """向量召回的跨专家私有行必须被 is_row_visible 过滤掉；共享行保留。"""
    manager = MagicMock()
    # 关键词路返回空（隔离测试已在 test_memory_agent_isolation.py 覆盖）
    manager.recall.return_value = {"episodic": [], "semantic": []}
    # 无 DB → resolve_session_project_key / _recall_db 走降级分支，不碰真实库
    manager.episodic.db = None
    manager.semantic.db = None

    # 向量路返回 3 行：writer 私有 + coder 私有 + 共享
    writer_row = {
        "id": "mem-writer",
        "agent_id": "specialist-writer",
        "scope": "user",
        "importance": 6,
        "content": "写作私有事实",
    }
    coder_row = {
        "id": "mem-coder",
        "agent_id": "specialist-coder",
        "scope": "user",
        "importance": 6,
        "content": "编码私有事实",
    }
    shared_row = {
        "id": "mem-shared",
        "agent_id": None,
        "scope": "user",
        "importance": 6,
        "content": "共享事实",
    }

    def _get_by_id(mem_id):
        return {
            "mem-writer": dict(writer_row),
            "mem-coder": dict(coder_row),
            "mem-shared": dict(shared_row),
        }.get(mem_id)

    manager.episodic.get_by_id = MagicMock(side_effect=_get_by_id)
    manager.semantic.get_by_id = MagicMock(return_value=None)

    adapter = MemoryAdapter.__new__(MemoryAdapter)
    adapter.memory_manager = manager
    adapter.vector_store = MagicMock()
    adapter.vector_store.search.return_value = [
        {"memory_id": "mem-writer", "distance": 0.1, "session_id": "s1"},
        {"memory_id": "mem-coder", "distance": 0.2, "session_id": "s1"},
        {"memory_id": "mem-shared", "distance": 0.3, "session_id": "s1"},
    ]
    # 走语义嵌入器路径（否则向量路被 skip-vector 跳过）
    adapter.embedder = MagicMock()
    adapter.embedder.is_semantic = True
    adapter._recall_eval = None
    adapter.user_profile = None

    # 以 specialist-writer 身份检索：应仅见 writer 私有 + 共享
    ctx = await adapter.retrieve(
        query="测试", session_id="s1", limit=10, agent_id="specialist-writer"
    )

    all_ids = {m.get("id") for m in ctx.episodic + ctx.semantic + ctx.core}
    # writer 私有 + 共享都应可见
    assert "mem-writer" in all_ids
    assert "mem-shared" in all_ids
    # coder 私有不可见
    assert "mem-coder" not in all_ids

    # 检查 recall 也收到了 agent_id
    assert manager.recall.call_args.kwargs["agent_id"] == "specialist-writer"


@pytest.mark.asyncio()
async def test_adapter_retrieve_no_agent_id_keeps_all_rows():
    """agent_id=None（管理视图）不限制 — 所有行可见。"""
    manager = MagicMock()
    manager.recall.return_value = {"episodic": [], "semantic": []}
    manager.episodic.db = None
    manager.semantic.db = None

    rows = [
        {"id": f"mem-{i}", "agent_id": f"agent-{i}", "scope": "user", "importance": 6, "content": f"c{i}"}
        for i in range(3)
    ]

    manager.episodic.get_by_id = MagicMock(
        side_effect=lambda m: dict(next(r for r in rows if r["id"] == m))
    )
    manager.semantic.get_by_id = MagicMock(return_value=None)

    adapter = MemoryAdapter.__new__(MemoryAdapter)
    adapter.memory_manager = manager
    adapter.vector_store = MagicMock()
    adapter.vector_store.search.return_value = [
        {"memory_id": r["id"], "distance": 0.1, "session_id": "s1"} for r in rows
    ]
    adapter.embedder = MagicMock()
    adapter.embedder.is_semantic = True
    adapter._recall_eval = None
    adapter.user_profile = None

    ctx = await adapter.retrieve(query="测试", session_id="s1", limit=10)

    all_ids = {m.get("id") for m in ctx.episodic + ctx.semantic + ctx.core}
    assert {r["id"] for r in rows} <= all_ids


@pytest.mark.asyncio()
async def test_adapter_store_passes_agent_id_to_memorize():
    """MemoryAdapter.store 必须把 agent_id 透传给 MemoryManager.memorize。"""
    from backend.memory.manager import MemoryManager

    manager = MagicMock(spec=MemoryManager)
    manager.memorize.return_value = "mem-new"

    adapter = MemoryAdapter.__new__(MemoryAdapter)
    adapter.memory_manager = manager
    adapter.vector_store = None  # 跳过向量化

    mid = await adapter.store(
        content="写作偏好事实",
        session_id="s1",
        importance=7,
        tags=["pref"],
        agent_id="specialist-writer",
    )

    assert mid == "mem-new"
    assert manager.memorize.call_args.kwargs["agent_id"] == "specialist-writer"
    assert manager.memorize.call_args.kwargs["session_id"] == "s1"
    assert manager.memorize.call_args.kwargs["content"] == "写作偏好事实"


# --------------------------------------------------------------------------- #
# Memory 工具使用 context.agent_id
# --------------------------------------------------------------------------- #


def test_memory_save_tool_forwards_context_agent_id():
    """MemorySaveTool 把 ToolExecutionContext.agent_id 透传给 manager.memorize。"""
    from backend.tools.context import (
        ToolExecutionContext,
        reset_tool_context,
        set_tool_context,
    )
    from backend.tools.memory_tool import MemorySaveTool

    token = set_tool_context(
        ToolExecutionContext(
            session_id="s1",
            stream_id="stream-1",
            binding_generation=1,
            office_doc_scope=frozenset(),
            agent_id="specialist-writer",
        )
    )
    try:
        manager = Mock()
        manager.memorize = MagicMock(return_value="mem-id")
        tool = MemorySaveTool(memory_manager=manager)
        result = tool.execute(content="重要事实", memory_type="episodic", importance=7)

        assert result.success
        # agent_id 必须透传；positional 调用 (content, memory_type, importance, tags, **kwargs)
        args, kwargs = manager.memorize.call_args
        assert kwargs["agent_id"] == "specialist-writer"
        assert kwargs["session_id"] == "s1"
    finally:
        reset_tool_context(token)


def test_memory_search_tool_forwards_context_agent_id():
    """MemorySearchTool 把 ToolExecutionContext.agent_id 透传给 search_memories。"""
    from backend.tools.context import (
        ToolExecutionContext,
        reset_tool_context,
        set_tool_context,
    )
    from backend.tools.memory_tool import MemorySearchTool

    token = set_tool_context(
        ToolExecutionContext(
            session_id="s1",
            stream_id="stream-1",
            binding_generation=1,
            office_doc_scope=frozenset(),
            agent_id="specialist-coder",
        )
    )
    try:
        manager = Mock()
        manager.search_memories = MagicMock(return_value=[{"id": "mem-1"}])
        tool = MemorySearchTool(memory_manager=manager)
        result = tool.execute(query="测试查询")

        assert result.success
        assert manager.search_memories.call_args.kwargs["agent_id"] == "specialist-coder"
        assert manager.search_memories.call_args.kwargs["session_id"] == "s1"
    finally:
        reset_tool_context(token)
