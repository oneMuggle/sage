"""R126 — LazyLock（线程感知惰性 asyncio.Lock）单元测试。

覆盖：构造零副作用（惰性核心）、单例创建、async with 互斥与 locked()
三态、手动 acquire/release 配对、未持锁 release 抛错、issue #536 回归
（无事件循环线程实例化安全）、异常路径释放。
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from backend.orchestration._lazy_lock import LazyLock

pytestmark = pytest.mark.unit


def test_construction_creates_no_lock():
    ll = LazyLock()
    assert ll._lock is None  # 惰性核心：__init__ 零副作用
    assert ll.locked() is False


@pytest.mark.asyncio()
async def test_lock_created_once_on_first_use():
    ll = LazyLock()
    async with ll:
        created = ll._lock
        assert created is not None
    assert ll._lock is created  # 后续访问返回同一把锁


@pytest.mark.asyncio()
async def test_async_with_mutual_exclusion():
    ll = LazyLock()
    order = []

    async def holder():
        async with ll:
            order.append("acquired")
            await asyncio.sleep(0.05)
            order.append("released")

    task = asyncio.create_task(holder())
    await asyncio.sleep(0.01)
    assert ll.locked() is True
    assert order == ["acquired"]  # 第二协程尚未进入
    await task
    assert order == ["acquired", "released"]
    assert ll.locked() is False


@pytest.mark.asyncio()
async def test_acquire_release_manual_pair():
    ll = LazyLock()
    assert await ll.acquire() is True
    assert ll.locked() is True
    ll.release()
    assert ll.locked() is False


@pytest.mark.asyncio()
async def test_release_without_acquire_raises():
    ll = LazyLock()
    with pytest.raises(RuntimeError):
        ll.release()  # 构造出锁但未持有 → RuntimeError


def test_instantiation_without_event_loop_thread():
    """issue #536 回归：无事件循环的普通线程中实例化必须安全。"""
    errors = []

    def build():
        try:
            ll = LazyLock()
            assert ll._lock is None
        except Exception as exc:  # pragma: no cover - 汇入 errors
            errors.append(exc)

    t = threading.Thread(target=build)
    t.start()
    t.join()
    assert errors == []


@pytest.mark.asyncio()
async def test_async_with_returns_self():
    ll = LazyLock()
    async with ll as entered:
        assert entered is ll


@pytest.mark.asyncio()
async def test_exception_inside_critical_section_releases():
    ll = LazyLock()
    with pytest.raises(ValueError, match="boom"):
        async with ll:
            raise ValueError("boom")
    assert ll.locked() is False  # 异常路径不泄漏锁
    # 且锁可立即复用
    async with ll:
        assert ll.locked() is True
