"""PauseState 单测。"""

import asyncio

import pytest

from backend.orchestration.pause_state import PauseState


@pytest.mark.asyncio()
async def test_initial_unpaused():
    ps = PauseState()
    assert ps.paused is False


@pytest.mark.asyncio()
async def test_wait_when_unpaused_returns_immediately():
    ps = PauseState()
    await ps.wait_if_paused()  # 不应阻塞


@pytest.mark.asyncio()
async def test_pause_blocks_until_resume():
    ps = PauseState()
    assert ps.request_pause() is True
    assert ps.paused is True

    waiter_done = asyncio.Event()

    async def waiter():
        await ps.wait_if_paused()
        waiter_done.set()

    task = asyncio.create_task(waiter())
    await asyncio.sleep(0)  # 让 waiter 跑起来
    assert not waiter_done.is_set()

    assert ps.request_resume() is True
    await asyncio.wait_for(waiter_done.wait(), timeout=1.0)
    await task


@pytest.mark.asyncio()
async def test_pause_idempotent():
    ps = PauseState()
    assert ps.request_pause() is True
    assert ps.request_pause() is False  # 已是暂停


@pytest.mark.asyncio()
async def test_resume_idempotent():
    ps = PauseState()
    assert ps.request_resume() is False  # 本就运行


@pytest.mark.asyncio()
async def test_concurrent_pause_resume():
    ps = PauseState()
    ps.request_pause()

    async def toggle():
        await asyncio.sleep(0.05)
        ps.request_resume()

    asyncio.create_task(toggle())
    await asyncio.wait_for(ps.wait_if_paused(), timeout=1.0)
    assert ps.paused is False
