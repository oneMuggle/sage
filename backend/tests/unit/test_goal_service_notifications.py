"""goal_service 在目标终态时推通知的回归测试 —— 经 _execute_loop 真实路径。

Ruling 11：本文件**不得**出现 ``get_goal_notification_queue().push(...)``。
所有通知必须由被测的 ``GoalService._execute_loop`` 内部路径自己产生 ——
否则测试就是"自己 push 再断言队列里有"的同义反复。

实现说明（与 brief 的差异见提交说明）：
- 用 ``contextlib.ExitStack`` 而非括号化 ``with (...)``：括号化 with 是
  Python 3.10+ 语法，本文件要 cherry-pick 到 release/win7（py3.8），
  括号化写法会让 py38 的 ``pytest --collect-only`` 直接语法错误。
- 失败用例额外 patch 了 ``time_window_mgr.should_execute_now``：真实实现
  依赖当前本地时间，不 patch 时可能走进"窗口外等待"分支
  （``asyncio.sleep`` 最长 3600s），用例会挂死。
"""

from contextlib import ExitStack
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.domain.autonomous_goals import ExecutionRound
from backend.services.goal_notifications import (
    get_goal_notification_queue,
    reset_goal_notification_queue,
)
from backend.services.goal_service import GoalService
from backend.tests.unit.test_goal_service import MockGoalRepository


@pytest.fixture(autouse=True)
def _clean_queue():
    """隔离进程级通知队列：每个用例前后清空，避免跨文件串味。"""
    reset_goal_notification_queue()
    yield
    reset_goal_notification_queue()


@pytest.fixture()
def service():
    return GoalService(goal_repository=MockGoalRepository())


@pytest.mark.asyncio()
async def test_execute_loop_completed_pushes_notification(service):
    """目标走完一轮并被判定完成 → 队列里有一条 succeeded 通知。"""
    goal = await service.create_goal(name="测试目标", description="")

    with ExitStack() as stack:
        # 让 while 循环至少跑一次然后退出
        stack.enter_context(
            patch.object(service, "_should_continue", AsyncMock(side_effect=[True, False]))
        )
        # 跳过"时间窗口外等待"分支（否则会 asyncio.sleep 到下个窗口）
        stack.enter_context(
            patch.object(service.time_window_mgr, "should_execute_now", return_value=True)
        )
        stack.enter_context(
            patch.object(
                service,
                "execute_round",
                AsyncMock(
                    return_value=ExecutionRound(
                        round_number=1,
                        started_at=datetime.now(tz=timezone.utc),  # noqa: UP017 — datetime.UTC 是 Py 3.11+, win7 跑 3.8
                        tasks_executed=1,
                        tasks_succeeded=1,
                    )
                ),
            )
        )
        stack.enter_context(
            patch.object(
                service.checkpoint_mgr,
                "verify_all",
                AsyncMock(return_value=MagicMock(progress_percentage=100)),
            )
        )
        # 触发 _execute_loop 的 COMPLETED 分支
        stack.enter_context(
            patch.object(service, "_review_completion", AsyncMock(return_value=True))
        )

        await service._execute_loop(goal.id)

    items = get_goal_notification_queue().drain()
    assert len(items) == 1
    assert items[0]["kind"] == "goal"
    assert items[0]["goal_id"] == goal.id
    assert items[0]["status"] == "succeeded"
    assert items[0]["title"].startswith("✅")
    assert "测试目标" in items[0]["title"]


@pytest.mark.asyncio()
async def test_execute_loop_failed_pushes_notification(service):
    """执行抛异常 → 目标转 FAILED → 队列里有一条 failed 通知（含错误原因）。"""
    goal = await service.create_goal(name="失败目标", description="")

    with ExitStack() as stack:
        stack.enter_context(
            patch.object(service, "_should_continue", AsyncMock(side_effect=[True, False]))
        )
        stack.enter_context(
            patch.object(service.time_window_mgr, "should_execute_now", return_value=True)
        )
        stack.enter_context(
            patch.object(
                service,
                "execute_round",
                AsyncMock(side_effect=RuntimeError("模拟失败")),
            )
        )

        await service._execute_loop(goal.id)

    items = get_goal_notification_queue().drain()
    assert len(items) == 1
    assert items[0]["kind"] == "goal"
    assert items[0]["goal_id"] == goal.id
    assert items[0]["status"] == "failed"
    assert items[0]["title"].startswith("❌")
    assert "模拟失败" in items[0]["body"]
