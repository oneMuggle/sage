"""Unit tests for MemoryExtractionQueue — 记忆提取异步化队列。"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from backend.memory.async_extractor import (
    ExtractionRequest,
    get_memory_extraction_queue,
    reset_memory_extraction_queue,
)


@pytest.fixture()
def queue():
    reset_memory_extraction_queue()
    yield get_memory_extraction_queue()
    reset_memory_extraction_queue()


_DUMMY_MEMORY = AsyncMock(spec=object)


def _req(memory="default", enabled=True, text="用户想吃火锅"):
    if memory == "default":
        memory = _DUMMY_MEMORY
    return ExtractionRequest(
        memory_port=memory,
        extractor=AsyncMock(),
        user_text=text,
        assistant_text="好的",
        session_id="s1",
        enabled=enabled,
    )


@pytest.mark.asyncio()
async def test_submit_is_non_blocking(queue):
    """submit 立即返回，提取在后台 worker 执行（不在 submit 内）。"""
    with patch(
        "backend.application.services.chat_service.extract_and_store_memory",
        new=AsyncMock(),
    ) as mock_extract:
        queue.submit(_req())
        assert mock_extract.await_count == 0  # 未同步执行
        await queue.drain()
        assert mock_extract.await_count == 1


@pytest.mark.asyncio()
async def test_worker_passes_request_through(queue):
    """worker 把请求原样透传给 extract_and_store_memory。"""
    req = _req()
    with patch(
        "backend.application.services.chat_service.extract_and_store_memory",
        new=AsyncMock(),
    ) as mock_extract:
        queue.submit(req)
        await queue.drain()
        mock_extract.assert_awaited_once()
        call = mock_extract.await_args[1]
        assert call["memory_port"] is req.memory_port
        assert call["session_id"] == "s1"


@pytest.mark.asyncio()
async def test_submits_processed_in_order(queue):
    """多请求按提交顺序消费。"""
    order = []

    async def fake_extract(memory_port, extractor, user_text, assistant_text, session_id, enabled):
        order.append(user_text)
        return 1

    with patch(
        "backend.application.services.chat_service.extract_and_store_memory",
        new=fake_extract,
    ):
        queue.submit(_req(text="第一"))
        queue.submit(_req(text="第二"))
        queue.submit(_req(text="第三"))
        await queue.drain()
    assert order == ["第一", "第二", "第三"]


@pytest.mark.asyncio()
async def test_single_worker_serial(queue):
    """并发 submit 不并发执行（单 worker 串行）。"""
    active = 0
    max_active = 0

    async def fake_extract(memory_port, extractor, user_text, assistant_text, session_id, enabled):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return 1

    with patch(
        "backend.application.services.chat_service.extract_and_store_memory",
        new=fake_extract,
    ):
        for i in range(5):
            queue.submit(_req(text=f"m{i}"))
        await queue.drain()
    assert max_active == 1


@pytest.mark.asyncio()
async def test_worker_survives_single_failure(queue):
    """单条失败不杀 worker，后续项继续，failed 计数 +1。"""

    async def fake_extract(memory_port, extractor, user_text, assistant_text, session_id, enabled):
        if user_text == "boom":
            raise RuntimeError("extractor boom")
        return 1

    with patch(
        "backend.application.services.chat_service.extract_and_store_memory",
        new=fake_extract,
    ):
        queue.submit(_req(text="boom"))
        queue.submit(_req(text="ok"))
        await queue.drain()
    assert queue.failed == 1
    assert queue.completed == 1


@pytest.mark.asyncio()
async def test_drain_waits_and_times_out_gracefully(queue):
    """drain 等待完成；超时返回不抛，worker 存活继续处理。"""

    async def slow_extract(memory_port, extractor, user_text, assistant_text, session_id, enabled):
        await asyncio.sleep(0.5)
        return 1

    with patch(
        "backend.application.services.chat_service.extract_and_store_memory",
        new=slow_extract,
    ):
        queue.submit(_req())
        await queue.drain(timeout=0.05)  # 超时返回，不抛
        await queue.drain(timeout=2.0)  # worker 存活，等慢任务完成
    assert queue.completed == 1


@pytest.mark.asyncio()
async def test_submit_filters_disabled_and_none(queue):
    """memory_port=None / enabled=False → skipped，不入队。"""
    with patch(
        "backend.application.services.chat_service.extract_and_store_memory",
        new=AsyncMock(),
    ) as mock_extract:
        queue.submit(_req(memory=None))
        queue.submit(_req(enabled=False))
        await queue.drain()
    assert queue.skipped == 2
    assert queue.pending() == 0
    assert mock_extract.await_count == 0
