"""drain_post_turn_tasks 的事件循环隔离契约。

``_POST_TURN_TASKS`` 是模块级集合，跨测试事件循环会残留旧任务；py3.8 的
``asyncio.wait`` 拒绝其它 loop 的 Task（ValueError）。drain 只能等待当前
运行 loop 上的任务，同时仍须等待本 loop 上未完成的任务。
"""

from __future__ import annotations

import asyncio

import pytest

from backend.api import legacy_routes


def test_drain_ignores_tasks_from_other_loops():
    other_loop = asyncio.new_event_loop()
    foreign = other_loop.create_task(asyncio.sleep(60))
    legacy_routes._POST_TURN_TASKS.add(foreign)

    async def _case() -> None:
        # 旧实现会把 foreign 直接交给 asyncio.wait → ValueError。
        await legacy_routes.drain_post_turn_tasks(timeout=0.05)

    try:
        asyncio.run(_case())
    finally:
        legacy_routes._POST_TURN_TASKS.discard(foreign)
        foreign.cancel()
        # 在独立 loop 上消化取消，避免 "Task was destroyed but pending" 警告。
        other_loop.run_until_complete(asyncio.gather(foreign, return_exceptions=True))
        other_loop.close()


@pytest.mark.asyncio()
async def test_drain_awaits_tasks_on_current_loop():
    done = asyncio.Event()

    async def _quick() -> None:
        done.set()

    task = asyncio.create_task(_quick())
    legacy_routes._POST_TURN_TASKS.add(task)
    try:
        await legacy_routes.drain_post_turn_tasks(timeout=1.0)
        assert done.is_set()
    finally:
        legacy_routes._POST_TURN_TASKS.discard(task)
