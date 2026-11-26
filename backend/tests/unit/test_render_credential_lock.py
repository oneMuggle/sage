# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""渲染池凭据串行锁单元测试（2026-11-26 多会话隔离 P1）。

``Storage.setCookies/getCookies`` 是浏览器级操作：同一渲染池实例上并发执行
两个不同账号的凭据渲染会互相覆盖 cookie。``_credential_render_lock`` 按
``browser_id`` 提供串行锁；本测试覆盖锁身份与互斥语义。
"""

from __future__ import annotations

import threading
import time

import pytest

from backend.tools import web_render

pytestmark = [pytest.mark.unit]


def test_same_browser_id_returns_same_lock():
    first = web_render._credential_render_lock("browser-a")
    second = web_render._credential_render_lock("browser-a")
    assert first is second


def test_different_browser_ids_use_distinct_locks():
    assert web_render._credential_render_lock("browser-a") is not (
        web_render._credential_render_lock("browser-b")
    )


def test_lock_serializes_concurrent_holders():
    lock = web_render._credential_render_lock("browser-serialize")
    entered: list = []

    def worker() -> None:
        with lock:
            entered.append(threading.current_thread().name)

    first = threading.Thread(target=worker, name="first", daemon=True)
    second = threading.Thread(target=worker, name="second", daemon=True)
    first.start()
    second.start()
    first.join(timeout=5)
    second.join(timeout=5)

    assert sorted(entered) == ["first", "second"]
    assert not lock.locked()


def test_lock_blocks_until_released():
    lock = web_render._credential_render_lock("browser-block")
    acquired = lock.acquire(timeout=1)
    assert acquired is True
    thread = threading.Thread(target=lambda: None, daemon=True)
    try:
        got: list = []

        def try_acquire() -> None:
            got.append(lock.acquire(timeout=5))
            if got[-1]:
                lock.release()

        thread = threading.Thread(target=try_acquire, daemon=True)
        thread.start()
        time.sleep(0.05)
        assert got == []  # 主线程持锁期间，子线程拿不到
    finally:
        lock.release()
    thread.join(timeout=5)
    assert got == [True]
