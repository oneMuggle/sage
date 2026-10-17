"""
闲时自主目标执行系统 — 单元测试

测试范围：
- TimeWindowManager: 时间窗口判断、定价等级、执行决策
- CheckpointManager: 检查点验证（文件、命令）
"""

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from backend.domain.autonomous_goals import (
    Checkpoint,
    CheckpointType,
    ExecutionBudget,
    Goal,
    PricingTier,
    TimeWindow,
)
from backend.services.checkpoint_manager import CheckpointManager
from backend.services.time_window_manager import TimeWindowManager


class TestTimeWindowManager:
    """时间窗口管理器测试"""

    def setup_method(self):
        self.manager = TimeWindowManager(default_timezone="Asia/Shanghai")

    def test_is_off_peak_midnight_to_six(self):
        """测试 22:00-06:00 闲时窗口"""
        time_window = TimeWindow(
            off_peak_start="22:00",
            off_peak_end="06:00",
            weekends_off_peak=False,
        )

        # 23:00 应该在闲时
        assert self.manager.is_off_peak(time_window, datetime(2026, 10, 17, 23, 0))
        # 01:00 应该在闲时
        assert self.manager.is_off_peak(time_window, datetime(2026, 10, 17, 1, 0))
        # 10:00 不应该在闲时
        assert not self.manager.is_off_peak(time_window, datetime(2026, 10, 17, 10, 0))

    def test_is_off_peak_same_day_range(self):
        """测试 01:00-05:00 同一天闲时窗口"""
        time_window = TimeWindow(
            off_peak_start="01:00",
            off_peak_end="05:00",
            weekends_off_peak=False,
        )

        # 03:00 应该在闲时
        assert self.manager.is_off_peak(time_window, datetime(2026, 10, 17, 3, 0))
        # 10:00 不应该在闲时
        assert not self.manager.is_off_peak(time_window, datetime(2026, 10, 17, 10, 0))

    def test_is_off_peak_weekends(self):
        """测试周末闲时"""
        time_window = TimeWindow(
            off_peak_start="22:00",
            off_peak_end="06:00",
            weekends_off_peak=True,
        )

        # 2026-10-17 是周六
        # 周末应该全天闲时
        assert self.manager.is_off_peak(time_window, datetime(2026, 10, 17, 12, 0))
        assert self.manager.is_off_peak(time_window, datetime(2026, 10, 18, 15, 0))  # 周日

        # 工作日不在闲时窗口内不应该闲时
        # 2026-10-19 是周一
        assert not self.manager.is_off_peak(time_window, datetime(2026, 10, 19, 12, 0))

    def test_is_off_peak_holidays(self):
        """测试节假日闲时"""
        time_window = TimeWindow(
            off_peak_start="22:00",
            off_peak_end="06:00",
            weekends_off_peak=False,
            holidays=["2026-10-01", "2026-10-02"],
        )

        # 节假日应该全天闲时
        assert self.manager.is_off_peak(time_window, datetime(2026, 10, 1, 12, 0))
        assert self.manager.is_off_peak(time_window, datetime(2026, 10, 2, 15, 0))

        # 普通工作日不应该闲时
        assert not self.manager.is_off_peak(time_window, datetime(2026, 10, 19, 12, 0))

    def test_get_pricing_tier_off_peak(self):
        """测试闲时定价等级"""
        time_window = TimeWindow(
            off_peak_start="22:00",
            off_peak_end="06:00",
        )

        # 23:00 应该是 OFF_PEAK
        assert (
            self.manager.get_pricing_tier(time_window, datetime(2026, 10, 17, 23, 0))
            == PricingTier.OFF_PEAK
        )

    def test_get_pricing_tier_standard(self):
        """测试平峰定价等级"""
        time_window = TimeWindow(
            off_peak_start="22:00",
            off_peak_end="06:00",
        )

        # 2026-10-19 是周一（工作日）
        # 07:00 应该是 STANDARD (06:00-09:00)
        assert (
            self.manager.get_pricing_tier(time_window, datetime(2026, 10, 19, 7, 0))
            == PricingTier.STANDARD
        )

        # 20:00 应该是 STANDARD (18:00-22:00)
        assert (
            self.manager.get_pricing_tier(time_window, datetime(2026, 10, 19, 20, 0))
            == PricingTier.STANDARD
        )

    def test_get_pricing_tier_peak(self):
        """测试高峰定价等级"""
        time_window = TimeWindow(
            off_peak_start="22:00",
            off_peak_end="06:00",
        )

        # 2026-10-19 是周一（工作日）
        # 12:00 应该是 PEAK
        assert (
            self.manager.get_pricing_tier(time_window, datetime(2026, 10, 19, 12, 0))
            == PricingTier.PEAK
        )

    def test_should_execute_now_within_budget(self):
        """测试在预算内应该执行"""
        goal = Goal(
            id="test_goal_1",
            name="Test Goal",
            description="Test Description",
            time_window=TimeWindow(off_peak_start="22:00", off_peak_end="06:00"),
            budget=ExecutionBudget(max_rounds=10, max_hours=8.0, max_tokens=1_000_000),
        )

        # 23:00 在闲时窗口内，应该执行
        assert self.manager.should_execute_now(goal, datetime(2026, 10, 17, 23, 0))

    def test_should_execute_now_outside_window(self):
        """测试不在闲时窗口不应该执行"""
        goal = Goal(
            id="test_goal_2",
            name="Test Goal",
            description="Test Description",
            time_window=TimeWindow(off_peak_start="22:00", off_peak_end="06:00"),
            budget=ExecutionBudget(max_rounds=10, max_hours=8.0, max_tokens=1_000_000),
        )

        # 2026-10-19 是周一（工作日），12:00 不在闲时窗口，不应该执行
        assert not self.manager.should_execute_now(goal, datetime(2026, 10, 19, 12, 0))

    def test_should_execute_now_max_rounds_reached(self):
        """测试达到最大轮次不应该执行"""
        goal = Goal(
            id="test_goal_3",
            name="Test Goal",
            description="Test Description",
            time_window=TimeWindow(off_peak_start="22:00", off_peak_end="06:00"),
            budget=ExecutionBudget(max_rounds=10, max_hours=8.0, max_tokens=1_000_000),
            current_round=10,  # 已达到最大轮次
        )

        # 即使在闲时窗口，达到最大轮次也不应该执行
        assert not self.manager.should_execute_now(goal, datetime(2026, 10, 17, 23, 0))

    def test_get_next_execution_time_in_off_peak(self):
        """测试在闲时窗口内返回当前时间"""
        goal = Goal(
            id="test_goal_4",
            name="Test Goal",
            description="Test Description",
            time_window=TimeWindow(off_peak_start="22:00", off_peak_end="06:00"),
            budget=ExecutionBudget(),
        )

        now = datetime(2026, 10, 17, 23, 0)
        next_time = self.manager.get_next_execution_time(goal, now)
        assert next_time == now

    def test_get_next_execution_time_before_off_peak(self):
        """测试在闲时窗口前返回今天闲时开始时间"""
        goal = Goal(
            id="test_goal_5",
            name="Test Goal",
            description="Test Description",
            time_window=TimeWindow(off_peak_start="22:00", off_peak_end="06:00"),
            budget=ExecutionBudget(),
        )

        # 2026-10-19 是周一（工作日），10:00 在闲时窗口前
        now = datetime(2026, 10, 19, 10, 0)
        next_time = self.manager.get_next_execution_time(goal, now)
        assert next_time.hour == 22
        assert next_time.minute == 0
        assert next_time.day == 19

    def test_get_next_execution_time_after_off_peak(self):
        """测试在闲时窗口后返回明天闲时开始时间"""
        goal = Goal(
            id="test_goal_6",
            name="Test Goal",
            description="Test Description",
            time_window=TimeWindow(off_peak_start="22:00", off_peak_end="06:00"),
            budget=ExecutionBudget(),
        )

        now = datetime(2026, 10, 17, 23, 30)
        next_time = self.manager.get_next_execution_time(goal, now)
        # 已经在闲时窗口内，应该返回当前时间
        assert next_time == now


class TestCheckpointManager:
    """检查点管理器测试"""

    def setup_method(self):
        self.manager = CheckpointManager()

    @pytest.mark.asyncio
    async def test_verify_file_exists(self):
        """测试文件存在性检查"""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("test content")
            file_path = f.name

        try:
            checkpoint = Checkpoint(
                id="test_1",
                type=CheckpointType.FILE,
                description="File exists",
                file_path=file_path,
            )

            result = await self.manager.verify_checkpoint(checkpoint)
            assert result.passed
            assert result.actual_value == "file_exists"
        finally:
            Path(file_path).unlink()

    @pytest.mark.asyncio
    async def test_verify_file_not_exists(self):
        """测试文件不存在"""
        checkpoint = Checkpoint(
            id="test_2",
            type=CheckpointType.FILE,
            description="File exists",
            file_path="/nonexistent/file.txt",
        )

        result = await self.manager.verify_checkpoint(checkpoint)
        assert not result.passed
        assert result.actual_value == "file_not_found"

    @pytest.mark.asyncio
    async def test_verify_file_line_count(self):
        """测试文件行数检查"""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            # 写入 100 行
            for i in range(100):
                f.write(f"line {i}\n")
            file_path = f.name

        try:
            checkpoint = Checkpoint(
                id="test_3",
                type=CheckpointType.FILE,
                description="File has 100 lines",
                file_path=file_path,
                expected_pattern="100",
            )

            result = await self.manager.verify_checkpoint(checkpoint)
            assert result.passed
            assert "100 lines" in result.actual_value
        finally:
            Path(file_path).unlink()

    @pytest.mark.asyncio
    async def test_verify_file_regex_match(self):
        """测试文件正则匹配"""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("def test_function():")
            file_path = f.name

        try:
            checkpoint = Checkpoint(
                id="test_4",
                type=CheckpointType.FILE,
                description="File contains test function",
                file_path=file_path,
                expected_pattern=r"def test_\w+\(\):",
            )

            result = await self.manager.verify_checkpoint(checkpoint)
            assert result.passed
            assert result.actual_value == "matched"
        finally:
            Path(file_path).unlink()

    @pytest.mark.asyncio
    async def test_verify_command_success(self):
        """测试命令执行成功"""
        checkpoint = Checkpoint(
            id="test_5",
            type=CheckpointType.COMMAND,
            description="Echo success",
            verification_command="echo 'success'",
        )

        result = await self.manager.verify_checkpoint(checkpoint)
        assert result.passed
        assert result.actual_value == "exit_code=0"

    @pytest.mark.asyncio
    async def test_verify_command_failure(self):
        """测试命令执行失败"""
        checkpoint = Checkpoint(
            id="test_6",
            type=CheckpointType.COMMAND,
            description="False command",
            verification_command="false",
        )

        result = await self.manager.verify_checkpoint(checkpoint)
        assert not result.passed
        assert "exit_code=" in result.actual_value

    @pytest.mark.asyncio
    async def test_verify_command_with_regex(self):
        """测试命令输出正则匹配"""
        checkpoint = Checkpoint(
            id="test_7",
            type=CheckpointType.COMMAND,
            description="Echo with pattern",
            verification_command="echo 'test_output_123'",
            expected_pattern=r"test_output_\d+",
        )

        result = await self.manager.verify_checkpoint(checkpoint)
        assert result.passed
        assert result.actual_value == "matched"

    @pytest.mark.asyncio
    async def test_verify_all_checkpoints(self):
        """测试批量验证检查点"""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("test content")
            file_path = f.name

        try:
            checkpoints = [
                Checkpoint(
                    id="test_8a",
                    type=CheckpointType.FILE,
                    description="File exists",
                    file_path=file_path,
                ),
                Checkpoint(
                    id="test_8b",
                    type=CheckpointType.COMMAND,
                    description="Echo success",
                    verification_command="echo 'success'",
                ),
            ]

            report = await self.manager.verify_all(checkpoints)
            assert report.total == 2
            assert report.passed == 2
            assert report.failed == 0
            assert report.progress_percentage == 100.0
        finally:
            Path(file_path).unlink()

    @pytest.mark.asyncio
    async def test_verify_all_empty(self):
        """测试空检查点列表"""
        report = await self.manager.verify_all([])
        assert report.total == 0
        assert report.passed == 0
        assert report.failed == 0
        assert report.progress_percentage == 0.0


class TestCheckpointManagerLLM:
    """CheckpointManager LLM 集成测试"""

    def setup_method(self):
        self.manager = CheckpointManager()

    def test_parse_checkpoints_json_pure_json(self):
        """测试解析纯 JSON 数组"""
        content = """[
  {"type": "file", "description": "检查文件存在", "file_path": "output.md", "verification_command": null, "expected_pattern": null},
  {"type": "command", "description": "运行测试", "file_path": null, "verification_command": "pytest", "expected_pattern": "pass"}
]"""
        checkpoints = self.manager._parse_checkpoints_json(content)
        assert len(checkpoints) == 2
        assert checkpoints[0].type == CheckpointType.FILE
        assert checkpoints[0].description == "检查文件存在"
        assert checkpoints[0].file_path == "output.md"
        assert checkpoints[1].type == CheckpointType.COMMAND
        assert checkpoints[1].verification_command == "pytest"

    def test_parse_checkpoints_json_code_block(self):
        """测试解析代码块包裹的 JSON"""
        content = """这是一些解释文本。

```json
[
  {"type": "file", "description": "报告文件", "file_path": "report.md"}
]
```

以上是生成的检查点。"""
        checkpoints = self.manager._parse_checkpoints_json(content)
        assert len(checkpoints) == 1
        assert checkpoints[0].description == "报告文件"

    def test_parse_checkpoints_json_empty(self):
        """测试解析空内容"""
        assert self.manager._parse_checkpoints_json("") == []
        assert self.manager._parse_checkpoints_json("no json here") == []
        assert self.manager._parse_checkpoints_json("[]") == []

    def test_parse_checkpoints_json_invalid_type(self):
        """测试跳过未知类型"""
        content = """[
  {"type": "unknown", "description": "bad type"},
  {"type": "file", "description": "good", "file_path": "test.txt"}
]"""
        checkpoints = self.manager._parse_checkpoints_json(content)
        assert len(checkpoints) == 1
        assert checkpoints[0].description == "good"

    def test_parse_checkpoints_json_not_array(self):
        """测试非数组返回空"""
        content = '{"type": "file", "description": "single object"}'
        assert self.manager._parse_checkpoints_json(content) == []

    @pytest.mark.asyncio
    async def test_generate_checkpoints_no_llm_config(self):
        """测试无 LLM 配置返回空列表"""
        goal = Goal(
            id="test_1",
            name="Test Goal",
            description="Test Description",
        )
        result = await self.manager.generate_checkpoints(goal, llm_config=None)
        assert result == []

    @pytest.mark.asyncio
    async def test_generate_checkpoints_with_mock_llm(self):
        """测试使用 mock LLM 生成检查点"""
        from unittest.mock import AsyncMock, MagicMock

        goal = Goal(
            id="test_2",
            name="Write Report",
            description="Write a 100-line report about AI",
        )

        # Mock LLM 响应
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = """[
  {"type": "file", "description": "报告文件存在", "file_path": "report.md"},
  {"type": "file", "description": "报告至少 100 行", "file_path": "report.md", "expected_pattern": "100"}
]"""
        mock_response.choices = [mock_choice]

        mock_client = AsyncMock()
        mock_client.chat_completion = AsyncMock(return_value=mock_response)

        mock_config = MagicMock()
        mock_config.model = "test-model"
        mock_config.create_client = MagicMock(return_value=mock_client)

        result = await self.manager.generate_checkpoints(goal, llm_config=mock_config)
        assert len(result) == 2
        assert result[0].description == "报告文件存在"
        assert result[1].expected_pattern == "100"

    @pytest.mark.asyncio
    async def test_generate_checkpoints_llm_error(self):
        """测试 LLM 调用失败返回空列表"""
        from unittest.mock import AsyncMock, MagicMock

        goal = Goal(id="test_3", name="Test", description="Desc")

        mock_config = MagicMock()
        mock_config.model = "test-model"
        mock_client = AsyncMock()
        mock_client.chat_completion = AsyncMock(side_effect=Exception("API error"))
        mock_config.create_client = MagicMock(return_value=mock_client)

        result = await self.manager.generate_checkpoints(goal, llm_config=mock_config)
        assert result == []
