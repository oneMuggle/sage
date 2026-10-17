"""
闲时自主目标执行系统 — GoalService 单元测试

测试范围：
- CRUD 操作
- 执行控制（start/pause/cancel）
- _should_continue 逻辑
- _review_completion 逻辑
- _apply_degradation 逻辑
- get_execution_report
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.domain.autonomous_goals import (
    DegradationLevel,
    ExecutionBudget,
    ExecutionRound,
    Goal,
    GoalStatus,
    TimeWindow,
)
from backend.services.goal_service import GoalService
from backend.services.checkpoint_manager import CheckpointReport


class MockGoalRepository:
    """内存 mock 的 GoalRepository"""

    def __init__(self):
        self.goals = {}

    def create(self, goal):
        self.goals[goal.id] = goal
        return goal

    def get(self, goal_id):
        return self.goals.get(goal_id)

    def list_all(self, status=None, limit=50, offset=0):
        goals = list(self.goals.values())
        if status:
            goals = [g for g in goals if g.status == status]
        return goals[offset : offset + limit]

    def update(self, goal):
        self.goals[goal.id] = goal
        return goal

    def delete(self, goal_id):
        if goal_id in self.goals:
            del self.goals[goal_id]
            return True
        return False


class TestGoalServiceCRUD:
    """CRUD 操作测试"""

    def setup_method(self):
        self.mock_repo = MockGoalRepository()
        self.service = GoalService(goal_repository=self.mock_repo)

    @pytest.mark.asyncio
    async def test_create_goal(self):
        """测试创建目标"""
        goal = await self.service.create_goal(
            name="Test Goal",
            description="Test description",
            time_window=TimeWindow(off_peak_start="22:00", off_peak_end="06:00"),
            budget=ExecutionBudget(max_rounds=5),
        )

        assert goal.id.startswith("goal_")
        assert goal.name == "Test Goal"
        assert goal.status == GoalStatus.PENDING
        assert goal.budget.max_rounds == 5
        assert self.mock_repo.get(goal.id) is not None

    @pytest.mark.asyncio
    async def test_get_goal(self):
        """测试获取目标"""
        created = await self.service.create_goal(name="Test", description="Desc")
        fetched = await self.service.get_goal(created.id)

        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.name == "Test"

    @pytest.mark.asyncio
    async def test_get_goal_not_found(self):
        """测试获取不存在目标"""
        result = await self.service.get_goal("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_goals(self):
        """测试列出目标"""
        await self.service.create_goal(name="Goal 1", description="Desc 1")
        await self.service.create_goal(name="Goal 2", description="Desc 2")

        goals = await self.service.list_goals()
        assert len(goals) == 2

    @pytest.mark.asyncio
    async def test_list_goals_by_status(self):
        """测试按状态过滤"""
        g1 = await self.service.create_goal(name="Goal 1", description="Desc 1")
        g2 = await self.service.create_goal(name="Goal 2", description="Desc 2")

        # 修改 g1 状态
        g1.status = GoalStatus.RUNNING
        self.mock_repo.update(g1)

        pending = await self.service.list_goals(status=GoalStatus.PENDING)
        assert len(pending) == 1
        assert pending[0].id == g2.id

    @pytest.mark.asyncio
    async def test_delete_goal(self):
        """测试删除目标"""
        goal = await self.service.create_goal(name="Test", description="Desc")
        assert await self.service.delete_goal(goal.id)
        assert await self.service.get_goal(goal.id) is None


class TestGoalServiceExecutionControl:
    """执行控制测试"""

    def setup_method(self):
        self.mock_repo = MockGoalRepository()
        self.service = GoalService(goal_repository=self.mock_repo)

    @pytest.mark.asyncio
    async def test_start_execution(self):
        """测试启动执行"""
        goal = await self.service.create_goal(name="Test", description="Desc")

        # Mock _execute_loop 避免实际执行
        with patch.object(self.service, "_execute_loop"):
            started = await self.service.start_execution(goal.id)

        assert started.status == GoalStatus.RUNNING
        assert started.started_at is not None

    @pytest.mark.asyncio
    async def test_start_execution_not_found(self):
        """测试启动不存在目标"""
        with pytest.raises(ValueError, match="Goal not found"):
            await self.service.start_execution("nonexistent")

    @pytest.mark.asyncio
    async def test_start_execution_wrong_status(self):
        """测试启动已完成目标"""
        goal = await self.service.create_goal(name="Test", description="Desc")
        goal.status = GoalStatus.COMPLETED
        self.mock_repo.update(goal)

        with pytest.raises(ValueError, match="Cannot start goal"):
            await self.service.start_execution(goal.id)

    @pytest.mark.asyncio
    async def test_pause_execution(self):
        """测试暂停执行"""
        goal = await self.service.create_goal(name="Test", description="Desc")
        goal.status = GoalStatus.RUNNING
        self.mock_repo.update(goal)

        paused = await self.service.pause_execution(goal.id)
        assert paused.status == GoalStatus.PAUSED

    @pytest.mark.asyncio
    async def test_cancel_execution(self):
        """测试取消执行"""
        goal = await self.service.create_goal(name="Test", description="Desc")
        goal.status = GoalStatus.RUNNING
        self.mock_repo.update(goal)

        cancelled = await self.service.cancel_execution(goal.id)
        assert cancelled.status == GoalStatus.CANCELLED
        assert cancelled.completed_at is not None


class TestShouldContinue:
    """_should_continue 逻辑测试"""

    def setup_method(self):
        self.mock_repo = MockGoalRepository()
        self.service = GoalService(goal_repository=self.mock_repo)

    @pytest.mark.asyncio
    async def test_continue_running(self):
        """测试运行中应该继续"""
        goal = Goal(
            id="test_1",
            name="Test",
            description="Desc",
            status=GoalStatus.RUNNING,
            budget=ExecutionBudget(max_rounds=10, max_hours=8.0, max_tokens=1_000_000),
        )
        assert await self.service._should_continue(goal)

    @pytest.mark.asyncio
    async def test_stop_completed(self):
        """测试已完成不应继续"""
        goal = Goal(
            id="test_2",
            name="Test",
            description="Desc",
            status=GoalStatus.COMPLETED,
            budget=ExecutionBudget(),
        )
        assert not await self.service._should_continue(goal)

    @pytest.mark.asyncio
    async def test_stop_failed(self):
        """测试失败不应继续"""
        goal = Goal(
            id="test_3",
            name="Test",
            description="Desc",
            status=GoalStatus.FAILED,
            budget=ExecutionBudget(),
        )
        assert not await self.service._should_continue(goal)

    @pytest.mark.asyncio
    async def test_stop_cancelled(self):
        """测试取消不应继续"""
        goal = Goal(
            id="test_4",
            name="Test",
            description="Desc",
            status=GoalStatus.CANCELLED,
            budget=ExecutionBudget(),
        )
        assert not await self.service._should_continue(goal)

    @pytest.mark.asyncio
    async def test_stop_max_rounds(self):
        """测试达到最大轮次不应继续"""
        goal = Goal(
            id="test_5",
            name="Test",
            description="Desc",
            status=GoalStatus.RUNNING,
            budget=ExecutionBudget(max_rounds=5),
            current_round=5,
        )
        assert not await self.service._should_continue(goal)

    @pytest.mark.asyncio
    async def test_stop_max_hours(self):
        """测试超过时间预算不应继续"""
        goal = Goal(
            id="test_6",
            name="Test",
            description="Desc",
            status=GoalStatus.RUNNING,
            budget=ExecutionBudget(max_hours=1.0),
            started_at=datetime.utcnow() - timedelta(hours=2),
        )
        assert not await self.service._should_continue(goal)

    @pytest.mark.asyncio
    async def test_stop_max_tokens(self):
        """测试超过 token 预算不应继续"""
        goal = Goal(
            id="test_7",
            name="Test",
            description="Desc",
            status=GoalStatus.RUNNING,
            budget=ExecutionBudget(max_tokens=1000),
            total_tokens_used=1500,
        )
        assert not await self.service._should_continue(goal)


class TestReviewCompletion:
    """_review_completion 逻辑测试"""

    def setup_method(self):
        self.mock_repo = MockGoalRepository()
        self.service = GoalService(goal_repository=self.mock_repo)

    @pytest.mark.asyncio
    async def test_all_checkpoints_pass(self):
        """测试全部检查点通过"""
        goal = Goal(
            id="test_1",
            name="Test",
            description="Desc",
            status=GoalStatus.RUNNING,
        )

        report = CheckpointReport(
            total=3,
            passed=3,
            failed=0,
            pending=0,
            results=[],
            progress_percentage=100.0,
        )

        assert await self.service._review_completion(goal, report)

    @pytest.mark.asyncio
    async def test_high_completion_rate(self):
        """测试高完成率（>= 95%）"""
        goal = Goal(
            id="test_2",
            name="Test",
            description="Desc",
            status=GoalStatus.RUNNING,
        )

        report = CheckpointReport(
            total=20,
            passed=19,
            failed=1,
            pending=0,
            results=[],
            progress_percentage=95.0,
        )

        assert await self.service._review_completion(goal, report)

    @pytest.mark.asyncio
    async def test_low_completion_rate(self):
        """测试低完成率"""
        goal = Goal(
            id="test_3",
            name="Test",
            description="Desc",
            status=GoalStatus.RUNNING,
        )

        report = CheckpointReport(
            total=10,
            passed=5,
            failed=5,
            pending=0,
            results=[],
            progress_percentage=50.0,
        )

        assert not await self.service._review_completion(goal, report)

    @pytest.mark.asyncio
    async def test_no_checkpoints(self):
        """测试无检查点"""
        goal = Goal(
            id="test_4",
            name="Test",
            description="Desc",
            status=GoalStatus.RUNNING,
        )

        report = CheckpointReport(
            total=0,
            passed=0,
            failed=0,
            pending=0,
            results=[],
            progress_percentage=0.0,
        )

        assert not await self.service._review_completion(goal, report)


class TestApplyDegradation:
    """_apply_degradation 逻辑测试"""

    def setup_method(self):
        self.mock_repo = MockGoalRepository()
        self.service = GoalService(goal_repository=self.mock_repo)

    @pytest.mark.asyncio
    async def test_first_failure_model_downgrade(self):
        """测试第一次失败降级模型"""
        goal = Goal(
            id="test_1",
            name="Test",
            description="Desc",
            status=GoalStatus.RUNNING,
            rounds=[
                ExecutionRound(
                    round_number=1,
                    started_at=datetime.utcnow(),
                    error_message="Task failed",
                ),
            ],
        )

        await self.service._apply_degradation(goal, Exception("Test error"))
        assert goal.degradation_level == DegradationLevel.MODEL_DOWNGRADE

    @pytest.mark.asyncio
    async def test_second_failure_task_simplify(self):
        """测试第二次失败简化任务"""
        goal = Goal(
            id="test_2",
            name="Test",
            description="Desc",
            status=GoalStatus.RUNNING,
            rounds=[
                ExecutionRound(
                    round_number=1,
                    started_at=datetime.utcnow(),
                    error_message="Task failed 1",
                ),
                ExecutionRound(
                    round_number=2,
                    started_at=datetime.utcnow(),
                    error_message="Task failed 2",
                ),
            ],
        )

        await self.service._apply_degradation(goal, Exception("Test error"))
        assert goal.degradation_level == DegradationLevel.TASK_SIMPLIFY

    @pytest.mark.asyncio
    async def test_third_failure_stop(self):
        """测试第三次失败停止"""
        goal = Goal(
            id="test_3",
            name="Test",
            description="Desc",
            status=GoalStatus.RUNNING,
            rounds=[
                ExecutionRound(
                    round_number=1,
                    started_at=datetime.utcnow(),
                    error_message="Task failed 1",
                ),
                ExecutionRound(
                    round_number=2,
                    started_at=datetime.utcnow(),
                    error_message="Task failed 2",
                ),
                ExecutionRound(
                    round_number=3,
                    started_at=datetime.utcnow(),
                    error_message="Task failed 3",
                ),
            ],
        )

        await self.service._apply_degradation(goal, Exception("Test error"))
        assert goal.degradation_level == DegradationLevel.STOPPED
        assert goal.status == GoalStatus.FAILED


class TestGetExecutionReport:
    """get_execution_report 测试"""

    def setup_method(self):
        self.mock_repo = MockGoalRepository()
        self.service = GoalService(goal_repository=self.mock_repo)

    @pytest.mark.asyncio
    async def test_report_basic(self):
        """测试基本报告"""
        goal = await self.service.create_goal(name="Test", description="Desc")
        goal.status = GoalStatus.COMPLETED
        goal.started_at = datetime.utcnow() - timedelta(hours=1)
        goal.completed_at = datetime.utcnow()
        goal.rounds = [
            ExecutionRound(
                round_number=1,
                started_at=datetime.utcnow(),
                tasks_executed=3,
                tasks_succeeded=2,
                tasks_failed=1,
                tokens_used=5000,
            ),
        ]
        goal.total_tokens_used = 5000
        goal.completion_percentage = 66.7
        self.mock_repo.update(goal)

        report = await self.service.get_execution_report(goal.id)

        assert report["goal_id"] == goal.id
        assert report["status"] == "completed"
        assert report["total_rounds"] == 1
        assert report["total_tasks"] == 3
        assert report["tasks_succeeded"] == 2
        assert report["tasks_failed"] == 1
        assert report["total_tokens_used"] == 5000

    @pytest.mark.asyncio
    async def test_report_not_found(self):
        """测试报告目标不存在"""
        with pytest.raises(ValueError, match="Goal not found"):
            await self.service.get_execution_report("nonexistent")


class TestReviewCompletionLLM:
    """review_completion_with_llm 测试"""

    def setup_method(self):
        self.mock_repo = MockGoalRepository()
        self.service = GoalService(goal_repository=self.mock_repo)

    @pytest.mark.asyncio
    async def test_review_no_llm_fallback(self):
        """测试无 LLM 回退到基础版"""
        goal = Goal(
            id="test_1",
            name="Test",
            description="Desc",
            status=GoalStatus.RUNNING,
        )
        report = CheckpointReport(
            total=3, passed=3, failed=0, pending=0, results=[], progress_percentage=100.0
        )

        result = await self.service.review_completion_with_llm(goal, report, llm_config=None)
        assert result["is_complete"] is True
        assert "基础判断" in result["reasoning"]

    @pytest.mark.asyncio
    async def test_review_with_mock_llm(self):
        """测试使用 mock LLM 审查"""
        import json

        goal = Goal(
            id="test_2",
            name="Write Report",
            description="Write a report",
            status=GoalStatus.RUNNING,
        )
        report = CheckpointReport(
            total=5, passed=4, failed=1, pending=0, results=[], progress_percentage=80.0
        )

        # Mock LLM 响应
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = json.dumps({
            "is_complete": False,
            "confidence": 0.8,
            "reasoning": "大部分检查点通过，但还有1个失败",
            "suggestions": ["修复失败的检查点"],
        })
        mock_response.choices = [mock_choice]

        mock_client = AsyncMock()
        mock_client.chat_completion = AsyncMock(return_value=mock_response)

        mock_config = MagicMock()
        mock_config.model = "test-model"
        mock_config.create_client = MagicMock(return_value=mock_client)

        result = await self.service.review_completion_with_llm(
            goal, report, llm_config=mock_config
        )
        assert result["is_complete"] is False
        assert result["confidence"] == 0.8
        assert "大部分检查点通过" in result["reasoning"]
        assert len(result["suggestions"]) == 1

    @pytest.mark.asyncio
    async def test_review_llm_error_fallback(self):
        """测试 LLM 错误时回退"""

        goal = Goal(
            id="test_3",
            name="Test",
            description="Desc",
            status=GoalStatus.RUNNING,
        )
        report = CheckpointReport(
            total=5, passed=5, failed=0, pending=0, results=[], progress_percentage=100.0
        )

        mock_config = MagicMock()
        mock_config.model = "test-model"
        mock_client = AsyncMock()
        mock_client.chat_completion = AsyncMock(side_effect=Exception("API error"))
        mock_config.create_client = MagicMock(return_value=mock_client)

        result = await self.service.review_completion_with_llm(
            goal, report, llm_config=mock_config
        )
        assert result["is_complete"] is True  # 100% passed -> complete even in fallback
        assert "回退到基础判断" in result["reasoning"]
