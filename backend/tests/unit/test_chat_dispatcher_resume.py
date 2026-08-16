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


# ===== Wave 3 A10 (2026-08-14): plan_override 跳过拆解，task_id 沿用不重枚举 =====


@pytest.mark.asyncio()
async def test_override_run_uses_provided_run_id_and_plan():
    """override 建 dispatcher 用 run_id，首 dispatch 读到 override plan。

    走 legacy 的 override 路径不在这里（那是集成测试）；这里验证
    ChatDispatcher 在 run_id 已存在、plan_json=override 时，_ensure_plan_loaded
    能建出匹配 override task_id 的计划索引（resume 恢复流的权威计划来源）。
    """
    from backend.orchestration.chat_dispatcher import ChatDispatcher

    d = ChatDispatcher(stream_id="s1", entry_queue=asyncio.Queue(), run_id="orch-reused")
    d.init_orch_run(
        session_id="s-1",
        plan_json='{"tasks":[{"task_id":"t1","agent_id":"writer","goal":"恢复目标"}],"reasoning":""}',
        original_request="原始请求",
    )
    d._ensure_plan_loaded()  # 同步方法（A4 定义）—— 手动触发索引构建，非 await
    # 直接测计划索引已建
    assert "t1" in d._plan_by_id
    assert d._plan_by_id["t1"]["goal"] == "恢复目标"
