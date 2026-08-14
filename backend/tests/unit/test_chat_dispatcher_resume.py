"""Wave 2 P1-4 — ChatDispatcher _reviewed 守卫 + _first_dispatch_at 跟踪。

Plan Step 4:_reviewed=True 跳过 review / review 失败复位 / 首次 dispatch 设时间戳。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio()
async def test_review_blocked_by_reviewed_guard():
    """_reviewed=True 时 gate 不再触发 _run_review。"""
    from backend.orchestration.chat_dispatcher import ChatDispatcher

    dispatcher = ChatDispatcher(
        stream_id="s1",
        entry_queue=asyncio.Queue(),
        run_id="orch-test",
        total_tasks=1,
    )
    dispatcher._reviewed = True  # 模拟已 review 过
    with patch.object(
        dispatcher,
        "_run_review",
        new=AsyncMock(return_value={"block": "", "verdict": "pass"}),
    ) as mock_review:
        # _next_task_index >= total_tasks 触发 gate,但 _reviewed=True 跳过
        dispatcher._next_task_index = 1
        await dispatcher.dispatch([])
        mock_review.assert_not_called()


@pytest.mark.asyncio()
async def test_review_failure_resets_guard():
    """review 抛异常 → _reviewed=False → 下次可重试。"""
    from backend.orchestration.chat_dispatcher import ChatDispatcher

    dispatcher = ChatDispatcher(
        stream_id="s1",
        entry_queue=asyncio.Queue(),
        run_id="orch-test",
        total_tasks=1,
    )
    dispatcher._next_task_index = 1
    with patch.object(
        dispatcher,
        "_run_review",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        await dispatcher.dispatch([])
    assert dispatcher._reviewed is False


@pytest.mark.asyncio()
async def test_first_dispatch_at_set_on_first_call():
    """首次 dispatch → _first_dispatch_at 被设。"""
    from backend.orchestration.chat_dispatcher import ChatDispatcher

    dispatcher = ChatDispatcher(
        stream_id="s1",
        entry_queue=asyncio.Queue(),
        run_id="orch-test",
    )
    assert dispatcher._first_dispatch_at is None
    with patch.object(
        dispatcher,
        "_run_subagent",
        new=AsyncMock(return_value="ok"),
    ):
        await dispatcher.dispatch([{"agent_id": "primary", "goal": "g"}])
    assert dispatcher._first_dispatch_at is not None
