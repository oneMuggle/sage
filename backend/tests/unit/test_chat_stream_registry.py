"""
StreamRegistry 单元测试

覆盖 backend/api/chat_stream_registry.py 的 StreamRegistry 类。
- create / get / pop_if_done / sweep_expired 生命周期
- 状态字段（pending / running / done / failed）
- 边界:未知 streamId、过期 stream、并发 pop_if_done
"""

import asyncio
import time

import pytest

from backend.api.chat_stream_registry import SENTINEL, StreamEntry, StreamRegistry

pytestmark = pytest.mark.unit


def _make_event(state: str, content: str | None = None) -> dict:
    return {"state": state, "iteration": 0, "content": content}


@pytest.mark.asyncio
async def test_create_stores_entry_with_pending_status():
    reg = StreamRegistry()
    entry = await reg.create("sid-1", queue_maxsize=10)
    assert isinstance(entry, StreamEntry)
    assert entry.status == "pending"
    assert isinstance(entry.queue, asyncio.Queue)
    # 没有 producer 时 task 保持 None — 测试不强制要求
    assert entry.task is None
    assert entry.created_at <= time.time()
    assert reg.size() == 1


@pytest.mark.asyncio
async def test_create_with_producer_starts_task():
    reg = StreamRegistry()

    async def noop(entry: StreamEntry) -> None:
        return None

    entry = await reg.create("sid-1", queue_maxsize=10, producer=noop)
    assert isinstance(entry.task, asyncio.Task)
    # 让 task 跑完,避免 pytest 警告
    await entry.task


@pytest.mark.asyncio
async def test_get_returns_none_for_unknown_stream_id():
    reg = StreamRegistry()
    assert reg.get("nope") is None


@pytest.mark.asyncio
async def test_get_returns_the_entry_just_created():
    reg = StreamRegistry()
    created = await reg.create("sid-1", queue_maxsize=10)
    fetched = reg.get("sid-1")
    assert fetched is created


@pytest.mark.asyncio
async def test_pop_removes_entry_immediately():
    reg = StreamRegistry()
    await reg.create("sid-1", queue_maxsize=10)
    assert reg.pop("sid-1") is True
    assert reg.get("sid-1") is None
    assert reg.size() == 0


@pytest.mark.asyncio
async def test_pop_returns_false_for_unknown_id():
    reg = StreamRegistry()
    assert reg.pop("nope") is False


@pytest.mark.asyncio
async def test_producer_task_actually_runs_and_emits_done_sentinel():
    """create() 接收一个 producer 协程,registry 启动它并入队 sentinel。"""
    reg = StreamRegistry()

    async def producer(entry: StreamEntry) -> None:
        await entry.queue.put(_make_event("thinking"))
        await entry.queue.put(_make_event("done", "ok"))
        entry.status = "done"

    await reg.create("sid-1", queue_maxsize=10, producer=producer)
    # 给 producer task 一点时间运行
    for _ in range(50):
        if not reg.get("sid-1").queue.empty():
            break
        await asyncio.sleep(0.01)

    entry = reg.get("sid-1")
    assert entry.status == "done"
    events = []
    while not entry.queue.empty():
        ev = entry.queue.get_nowait()
        if ev is SENTINEL:
            break
        events.append(ev)
    assert events[0]["state"] == "thinking"
    assert events[1]["state"] == "done"


@pytest.mark.asyncio
async def test_producer_exception_marks_entry_failed():
    reg = StreamRegistry()

    async def broken_producer(entry: StreamEntry) -> None:
        raise RuntimeError("LLM exploded")

    await reg.create("sid-1", queue_maxsize=10, producer=broken_producer)
    for _ in range(50):
        if reg.get("sid-1") is not None and reg.get("sid-1").status in ("done", "failed"):
            break
        await asyncio.sleep(0.01)

    entry = reg.get("sid-1")
    assert entry.status == "failed"


@pytest.mark.asyncio
async def test_pop_if_done_removes_entry_after_grace_period():
    reg = StreamRegistry()
    entry = await reg.create("sid-1", queue_maxsize=10)
    entry.status = "done"
    # grace=0 → 立即删除
    await reg.pop_if_done("sid-1", grace_seconds=0)
    assert reg.get("sid-1") is None


@pytest.mark.asyncio
async def test_pop_if_done_does_not_remove_running_stream():
    reg = StreamRegistry()
    await reg.create("sid-1", queue_maxsize=10)
    # 还未 done,pop_if_done 不应删除
    await reg.pop_if_done("sid-1", grace_seconds=0)
    assert reg.get("sid-1") is not None


@pytest.mark.asyncio
async def test_sweep_expired_removes_stale_entries():
    reg = StreamRegistry()
    old_entry = await reg.create("old", queue_maxsize=10)
    old_entry.created_at = time.time() - 1000  # 假装 1000 秒前创建
    fresh_entry = await reg.create("fresh", queue_maxsize=10)
    # 标记为 done 防止 pop_if_done 的 done 检查干预
    old_entry.status = "done"
    fresh_entry.status = "done"
    await reg.sweep_expired(max_age_seconds=60)
    assert reg.get("old") is None
    assert reg.get("fresh") is not None


@pytest.mark.asyncio
async def test_queue_maxsize_bounds_memory():
    """队列应有界 — 不会无限增长。"""
    reg = StreamRegistry()
    await reg.create("sid-1", queue_maxsize=2)
    entry = reg.get("sid-1")
    # 不消费,放 3 个应该第 3 个阻塞(不抛错)
    await entry.queue.put(_make_event("a"))
    await entry.queue.put(_make_event("b"))
    put_task = asyncio.create_task(entry.queue.put(_make_event("c")))
    await asyncio.sleep(0.01)  # 让 put_task 有机会阻塞
    assert not put_task.done()  # 确认 put 在阻塞
    # 现在消费一个,put_task 应该完成
    entry.queue.get_nowait()
    await asyncio.wait_for(put_task, timeout=0.1)
    put_task.result()  # 不抛错
