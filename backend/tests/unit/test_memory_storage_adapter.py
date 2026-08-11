"""验证 ``MemoryStorageAdapter`` 行为。

覆盖 ``StoragePort`` 的 5 个方法（``create_session`` / ``list_sessions`` /
``delete_session`` / ``append_message`` / ``get_messages``）以及部分边界
场景：空会话、未知会话、limit 截断、tool_calls 序列化等。
"""

from __future__ import annotations

import pytest
from sage_core import Message, Role, ToolCall
from sage_core.repositories import StoragePort

from backend.adapters.out.storage.memory_adapter import MemoryStorageAdapter

pytestmark = pytest.mark.unit


# ============================================================================
# 1) 创建/列出/删除 会话
# ============================================================================


async def test_create_session_returns_unique_id() -> None:
    storage = MemoryStorageAdapter()
    sid1 = await storage.create_session(title="first")
    sid2 = await storage.create_session(title="second")
    assert sid1 != sid2
    # 默认 id 形如 mem-<uuid4>
    assert sid1.startswith("mem-")
    assert sid2.startswith("mem-")


async def test_create_and_list_session() -> None:
    storage = MemoryStorageAdapter()
    sid = await storage.create_session(title="test session")
    sessions = await storage.list_sessions()
    assert any(s["id"] == sid and s["title"] == "test session" for s in sessions)


async def test_list_sessions_empty() -> None:
    storage = MemoryStorageAdapter()
    sessions = await storage.list_sessions()
    assert sessions == []


async def test_delete_session_removes_from_list() -> None:
    storage = MemoryStorageAdapter()
    sid = await storage.create_session(title="to-delete")
    assert any(s["id"] == sid for s in await storage.list_sessions())
    await storage.delete_session(sid)
    assert all(s["id"] != sid for s in await storage.list_sessions())


async def test_delete_unknown_session_is_noop() -> None:
    storage = MemoryStorageAdapter()
    # 不应抛错
    await storage.delete_session("does-not-exist")


# ============================================================================
# 2) append / get 消息
# ============================================================================


async def test_append_and_get_messages() -> None:
    storage = MemoryStorageAdapter()
    sid = await storage.create_session()
    msg = Message(role=Role.USER, content="hello")
    await storage.append_message(sid, msg)
    msgs = await storage.get_messages(sid)
    assert len(msgs) == 1
    assert msgs[0].content == "hello"
    assert msgs[0].role == Role.USER


async def test_get_messages_limit_returns_most_recent() -> None:
    storage = MemoryStorageAdapter()
    sid = await storage.create_session()
    for i in range(10):
        await storage.append_message(sid, Message(role=Role.USER, content=f"msg{i}"))
    msgs = await storage.get_messages(sid, limit=3)
    assert len(msgs) == 3
    # 末尾 limit 条，按时间正序
    assert [m.content for m in msgs] == ["msg7", "msg8", "msg9"]


async def test_get_messages_unknown_session_returns_empty() -> None:
    storage = MemoryStorageAdapter()
    msgs = await storage.get_messages("nonexistent")
    assert msgs == []


async def test_get_messages_limit_larger_than_history() -> None:
    storage = MemoryStorageAdapter()
    sid = await storage.create_session()
    await storage.append_message(sid, Message(role=Role.USER, content="only"))
    msgs = await storage.get_messages(sid, limit=999)
    assert len(msgs) == 1
    assert msgs[0].content == "only"


async def test_get_messages_limit_zero_returns_empty() -> None:
    storage = MemoryStorageAdapter()
    sid = await storage.create_session()
    await storage.append_message(sid, Message(role=Role.USER, content="x"))
    assert await storage.get_messages(sid, limit=0) == []


async def test_append_to_unknown_session_autocreates() -> None:
    """未显式 create_session 的 session_id 在 append 时自动建空会话。"""
    storage = MemoryStorageAdapter()
    await storage.append_message("ghost", Message(role=Role.USER, content="hi"))
    msgs = await storage.get_messages("ghost")
    assert len(msgs) == 1
    assert msgs[0].content == "hi"


async def test_delete_session_cascades_messages() -> None:
    storage = MemoryStorageAdapter()
    sid = await storage.create_session()
    await storage.append_message(sid, Message(role=Role.USER, content="x"))
    await storage.delete_session(sid)
    assert await storage.get_messages(sid) == []


# ============================================================================
# 3) tool_calls / tool_call_id 往返
# ============================================================================


async def test_append_message_with_tool_calls_preserved() -> None:
    storage = MemoryStorageAdapter()
    sid = await storage.create_session()
    assistant = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[ToolCall(name="search", args={"q": "weather"}, id="call_1")],
    )
    await storage.append_message(sid, assistant)
    tool_msg = Message(
        role=Role.TOOL,
        content="sunny",
        tool_call_id="call_1",
    )
    await storage.append_message(sid, tool_msg)

    msgs = await storage.get_messages(sid)
    assert len(msgs) == 2
    assert msgs[0].role == Role.ASSISTANT
    assert len(msgs[0].tool_calls) == 1
    tc = msgs[0].tool_calls[0]
    assert tc.name == "search"
    assert tc.args == {"q": "weather"}
    assert tc.id == "call_1"
    assert msgs[1].role == Role.TOOL
    assert msgs[1].content == "sunny"
    assert msgs[1].tool_call_id == "call_1"


# ============================================================================
# 4) 结构性子类型（Protocol 契约）
# ============================================================================


def test_satisfies_storage_port_protocol() -> None:
    """``MemoryStorageAdapter`` 必须结构化满足 ``StoragePort``。"""
    storage: StoragePort = MemoryStorageAdapter()
    assert isinstance(storage, MemoryStorageAdapter)


# ============================================================================
# PR B §1.2 回归测试 - 验证 SqliteStorageAdapter 用 asyncio.to_thread offload
# ============================================================================


import asyncio
import sqlite3
import threading
import time
from typing import Any

import pytest

from backend.adapters.out.storage.sqlite_adapter import SqliteStorageAdapter


@pytest.mark.asyncio()
async def test_sqlite_adapter_uses_to_thread():
    """验证 SqliteStorageAdapter 7 个方法都通过 asyncio.to_thread 调度。"""
    adapter = SqliteStorageAdapter()
    call_log: list[str] = []

    # Monkey-patch asyncio.to_thread 记录调用
    original_to_thread = asyncio.to_thread

    async def spy_to_thread(func, *args, **kwargs):
        call_log.append(func.__name__)
        return await original_to_thread(func, *args, **kwargs)

    monkey = pytest.MonkeyPatch()
    monkey.setattr(asyncio, "to_thread", spy_to_thread)
    try:
        # 触发 7 个方法
        sid = await adapter.create_session(title="t")
        await adapter.list_sessions()
        await adapter.get_session(sid)
        await adapter.update_session(sid, title="new")
        await adapter.append_message(sid, _make_message("user", "hi"))
        await adapter.get_messages(sid, limit=10)
        await adapter.delete_session(sid)
    finally:
        monkey.undo()

    # 7 个方法 + 7 个 _sync_X 助手都通过 to_thread
    expected_sync_names = {
        "_sync_create_session",
        "_sync_list_sessions",
        "_sync_get_session",
        "_sync_update_session",
        "_sync_delete_session",
        "_sync_append_message",
        "_sync_get_messages",
    }
    actual_sync_names = set(call_log)
    assert expected_sync_names.issubset(actual_sync_names), (
        f"下列 _sync_X 未通过 to_thread 调用: {expected_sync_names - actual_sync_names}\n"
        f"  实际: {actual_sync_names}"
    )


@pytest.mark.asyncio()
async def test_to_thread_actually_offloads_to_worker():
    """验证 adapter 方法真的在 worker 线程跑,不在主事件循环线程跑。"""
    main_thread_id = threading.get_ident()
    adapter = SqliteStorageAdapter()
    observed_thread_ids: list[int] = []

    original_sync = adapter._sync_create_session

    def probed_sync(title: str) -> str:
        observed_thread_ids.append(threading.get_ident())
        return original_sync(title)

    adapter._sync_create_session = probed_sync  # type: ignore[method-assign]

    await adapter.create_session(title="probe")

    assert len(observed_thread_ids) == 1
    assert observed_thread_ids[0] != main_thread_id, (
        f"create_session 跑在主线程 {main_thread_id},应 offload 到 worker"
    )


@pytest.mark.asyncio()
async def test_concurrent_writes_are_serialized_by_lock():
    """N=20 并发 create_session,实际执行时间不重叠(锁串行)。

    NOTE: 探针挂在 ``adapter._sessions.create`` 而不是 ``_sync_create_session``。
    因为 CRITICAL fix 后锁在 ``_sync_create_session`` **内部**(``with
    _SQLITE_LOCK:``),若探针包在 ``_sync_create_session`` 外层,sleep 就落在锁
    外,测不到串行化。挂到 repo 层才保证 sleep 在临界区内。
    """
    adapter = SqliteStorageAdapter()
    N = 20
    execution_log: list[tuple[float, float]] = []

    original_create = adapter._sessions.create

    def probed_create(*args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        time.sleep(0.005)  # 模拟 SQLite 写延迟,放大可观察窗口
        execution_log.append((start, time.perf_counter()))
        return original_create(*args, **kwargs)

    adapter._sessions.create = probed_create  # type: ignore[method-assign]

    await asyncio.gather(*[adapter.create_session(title=f"t{i}") for i in range(N)])

    assert len(execution_log) == N
    sorted_log = sorted(execution_log)
    for i in range(1, len(sorted_log)):
        prev_end = sorted_log[i - 1][1]
        cur_start = sorted_log[i][0]
        assert cur_start >= prev_end, (
            f"锁失效:task {i} 在 {prev_end:.4f} 结束前就开始了 {cur_start:.4f}"
        )


@pytest.mark.asyncio()
async def test_memory_adapter_concurrent_creates_no_duplicate_ids():
    """HIGH fix regression: 10 并发 create_session 必须返回 10 个唯一 ID。

    修复前: ``_counter += 1`` 的 4 字节码序列让 GIL 切换,两个 worker 拿到
    同一 self._counter 值,产生重复 "mem-N" session ID。

    修复后: ``_sync_create_session`` 用 uuid.uuid4(),概率碰撞可忽略。
    """
    adapter = MemoryStorageAdapter()
    N = 10
    ids = await asyncio.gather(*(adapter.create_session(f"t-{i}") for i in range(N)))
    assert len(set(ids)) == N, (
        f"MemoryStorageAdapter 产生重复 session ID: {len(set(ids))} != {N}\n  ids: {ids}"
    )


@pytest.mark.asyncio()
async def test_to_thread_propagates_sync_exceptions():
    """_sync_X 抛异常,await to_thread 同样抛(行为与原版一致)。"""
    adapter = SqliteStorageAdapter()

    def boom(title: str) -> str:
        raise sqlite3.IntegrityError("UNIQUE constraint failed: test boom")

    adapter._sync_create_session = boom  # type: ignore[method-assign]

    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
        await adapter.create_session(title="test")


def _make_message(role: str, content: str) -> Any:
    """构造一个最小可用的 Message 对象(测试 helper)。"""
    from sage_core import Message, Role

    return Message(role=Role(role), content=content)


# ============================================================================
# PR B §1.2 - MemoryStorageAdapter 也用 asyncio.to_thread 包装(无锁)
# ============================================================================


@pytest.mark.asyncio()
async def test_memory_adapter_uses_to_thread():
    """验证 MemoryStorageAdapter 7 个方法都通过 asyncio.to_thread(无锁)。"""
    adapter = MemoryStorageAdapter()
    call_log: list[str] = []

    original_to_thread = asyncio.to_thread

    async def spy_to_thread(func, *args, **kwargs):
        call_log.append(func.__name__)
        return await original_to_thread(func, *args, **kwargs)

    monkey = pytest.MonkeyPatch()
    monkey.setattr(asyncio, "to_thread", spy_to_thread)
    try:
        sid = await adapter.create_session(title="t")
        await adapter.list_sessions()
        await adapter.get_session(sid)
        await adapter.update_session(sid, title="new")
        await adapter.append_message(sid, _make_message("user", "hi"))
        await adapter.get_messages(sid, limit=10)
        await adapter.delete_session(sid)
    finally:
        monkey.undo()

    expected_sync_names = {
        "_sync_create_session",
        "_sync_list_sessions",
        "_sync_get_session",
        "_sync_update_session",
        "_sync_delete_session",
        "_sync_append_message",
        "_sync_get_messages",
    }
    actual_sync_names = set(call_log)
    assert expected_sync_names.issubset(actual_sync_names), (
        f"Memory 下列 _sync_X 未通过 to_thread: {expected_sync_names - actual_sync_names}"
    )


@pytest.mark.asyncio()
async def test_memory_adapter_offloads_to_worker_no_lock():
    """MemoryStorageAdapter 包 to_thread 但无锁,并发执行,所有 thread_id != 主线程。"""
    main_thread_id = threading.get_ident()
    adapter = MemoryStorageAdapter()
    observed_thread_ids: list[int] = []

    original_sync = adapter._sync_create_session

    def probed_sync(title: str) -> str:
        observed_thread_ids.append(threading.get_ident())
        return original_sync(title)

    adapter._sync_create_session = probed_sync  # type: ignore[method-assign]

    await asyncio.gather(*[adapter.create_session(title=f"t{i}") for i in range(10)])

    assert len(observed_thread_ids) == 10
    assert all(tid != main_thread_id for tid in observed_thread_ids), (
        f"有 task 跑在主线程: {observed_thread_ids}"
    )
    # 注:无锁设计,执行区间可重叠,本断言不约束并发序列化
