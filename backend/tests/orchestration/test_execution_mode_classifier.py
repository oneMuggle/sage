"""``test_execution_mode_classifier`` — 执行模式分类器单元测试。

测试策略：
1. 响应解析（_parse_response）：覆盖正常/畸形/非法值场景
2. 降级策略：无 LLM 配置 / LLM 调用失败 / 响应解析失败 → ask_user 默认
3. 步骤摘要提取（_extract_steps_summary）：覆盖 Plan 对象的各种结构
4. 便捷函数：classify_execution_mode() 与 ExecutionModeClassifier().classify() 等价

不测试 LLM 调用本身（由 integration test 覆盖），只测试解析逻辑和降级纪律。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List
from unittest.mock import AsyncMock, patch

import pytest

from backend.orchestration.execution_mode_classifier import (
    ExecutionModeClassification,
    ExecutionModeClassifier,
    classify_execution_mode,
)

# ---------------------------------------------------------------------------
# 测试替身
# ---------------------------------------------------------------------------


@dataclass
class FakeTask:
    """模拟 Task 对象。"""

    name: str
    blocked_by: List[str] = field(default_factory=list)


@dataclass
class FakePlan:
    """模拟 Plan 对象。"""

    tasks: List[FakeTask]


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


class TestExecutionModeClassifierParseResponse:
    """测试 _parse_response() 方法。"""

    def setup_method(self):
        self.classifier = ExecutionModeClassifier()

    def test_parse_single_response(self):
        """正常 single 响应。"""
        raw = json.dumps(
            {
                "mode": "single",
                "confidence": 0.9,
                "reasoning": "步骤强依赖，必须串行",
            }
        )
        result = self.classifier._parse_response(raw)
        assert result.mode == "single"
        assert result.confidence == 0.9
        assert "步骤强依赖" in result.reasoning

    def test_parse_multi_response(self):
        """正常 multi 响应。"""
        raw = json.dumps(
            {
                "mode": "multi",
                "confidence": 0.85,
                "reasoning": "有独立步骤可并行",
            }
        )
        result = self.classifier._parse_response(raw)
        assert result.mode == "multi"
        assert result.confidence == 0.85

    def test_parse_ask_user_response(self):
        """正常 ask_user 响应。"""
        raw = json.dumps(
            {
                "mode": "ask_user",
                "confidence": 0.3,
                "reasoning": "ambiguous，让用户选择",
            }
        )
        result = self.classifier._parse_response(raw)
        assert result.mode == "ask_user"
        assert result.confidence == 0.3

    def test_parse_with_markdown_fence(self):
        """LLM 输出带 markdown 围栏 → 正常解析。"""
        raw = '```json\n{"mode": "single", "confidence": 0.9, "reasoning": "test"}\n```'
        result = self.classifier._parse_response(raw)
        assert result.mode == "single"

    def test_parse_empty_response(self):
        """空响应 → 降级为 ask_user。"""
        result = self.classifier._parse_response("")
        assert result.mode == "ask_user"
        assert result.confidence == 0.0
        assert "空响应" in result.reasoning

    def test_parse_none_response(self):
        """None 响应 → 降级为 ask_user。"""
        result = self.classifier._parse_response(None)
        assert result.mode == "ask_user"

    def test_parse_invalid_json(self):
        """非法 JSON → 降级为 ask_user。"""
        result = self.classifier._parse_response("not a json")
        assert result.mode == "ask_user"
        assert "JSON 解析失败" in result.reasoning

    def test_parse_non_dict_response(self):
        """JSON 但非 dict → 降级为 ask_user。"""
        result = self.classifier._parse_response('["not", "a", "dict"]')
        assert result.mode == "ask_user"
        assert "响应非 dict" in result.reasoning

    def test_parse_invalid_mode_value(self):
        """非法 mode 值 → 降级为 ask_user。"""
        raw = json.dumps(
            {
                "mode": "invalid",
                "confidence": 0.8,
                "reasoning": "test",
            }
        )
        result = self.classifier._parse_response(raw)
        assert result.mode == "ask_user"
        assert "非法 mode" in result.reasoning

    def test_parse_missing_confidence(self):
        """缺失 confidence → 默认 0.5。"""
        raw = json.dumps({"mode": "single", "reasoning": "test"})
        result = self.classifier._parse_response(raw)
        assert result.mode == "single"
        assert result.confidence == 0.5

    def test_parse_confidence_clamp(self):
        """confidence 超出 [0, 1] → clamp 到合法范围。"""
        raw = json.dumps({"mode": "single", "confidence": 1.5, "reasoning": "test"})
        result = self.classifier._parse_response(raw)
        assert result.confidence == 1.0

        raw = json.dumps({"mode": "single", "confidence": -0.5, "reasoning": "test"})
        result = self.classifier._parse_response(raw)
        assert result.confidence == 0.0

    def test_parse_missing_reasoning(self):
        """缺失 reasoning → 空字符串。"""
        raw = json.dumps({"mode": "multi", "confidence": 0.8})
        result = self.classifier._parse_response(raw)
        assert result.mode == "multi"
        assert result.reasoning == ""


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


class TestExtractStepsSummary:
    """测试 _extract_steps_summary() 方法。"""

    def setup_method(self):
        self.classifier = ExecutionModeClassifier()

    def test_extract_from_plan_with_tasks(self):
        """从 Plan 对象提取步骤摘要（含依赖信息）。"""
        plan = FakePlan(
            tasks=[
                FakeTask("Task 1: Setup"),
                FakeTask("Task 2: Build", blocked_by=["Task 1"]),
                FakeTask("Task 3: Test", blocked_by=["Task 1", "Task 2"]),
            ]
        )
        summary = self.classifier._extract_steps_summary(plan)
        assert "Task 1: Setup" in summary
        assert "Task 2: Build" in summary
        assert "依赖: Task 1" in summary
        assert "Task 3: Test" in summary
        assert "依赖: Task 1, Task 2" in summary

    def test_extract_from_empty_plan(self):
        """Plan 无任务 → 返回 '无步骤'。"""
        plan = FakePlan(tasks=[])
        summary = self.classifier._extract_steps_summary(plan)
        assert summary == "无步骤"

    def test_extract_from_plan_without_tasks_attr(self):
        """Plan 对象无 tasks 属性 → 返回 '无步骤'。"""

        class NoTasksPlan:
            pass

        summary = self.classifier._extract_steps_summary(NoTasksPlan())
        assert summary == "无步骤"

    def test_extract_handles_exception(self):
        """提取失败 → 返回 '步骤提取失败'。"""
        # 制造异常场景：tasks 属性访问时抛出异常
        class BrokenPlan:
            @property
            def tasks(self):
                raise RuntimeError("tasks property broken")

        summary = self.classifier._extract_steps_summary(BrokenPlan())
        assert summary == "步骤提取失败"


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


class TestExecutionModeClassifierDegradation:
    """测试降级策略。"""

    @pytest.mark.asyncio()
    async def test_no_llm_config(self):
        """无 LLM 配置 → 降级为 ask_user。"""
        with patch(
            "backend.orchestration.llm_factory.build_llm_client_from_settings",
            return_value=None,
        ):
            classifier = ExecutionModeClassifier()
            plan = FakePlan(tasks=[FakeTask("Task 1")])
            result = await classifier.classify(plan)
            assert result.mode == "ask_user"
            assert "无 LLM 配置" in result.reasoning

    @pytest.mark.asyncio()
    async def test_llm_call_failure(self):
        """LLM 调用失败 → 降级为 ask_user。"""
        mock_client = AsyncMock()
        mock_client.complete.side_effect = Exception("LLM error")

        with patch(
            "backend.orchestration.llm_factory.build_llm_client_from_settings",
            return_value=mock_client,
        ):
            classifier = ExecutionModeClassifier()
            plan = FakePlan(tasks=[FakeTask("Task 1")])
            result = await classifier.classify(plan)
            assert result.mode == "ask_user"
            assert "LLM 调用失败" in result.reasoning

    @pytest.mark.asyncio()
    async def test_successful_classification(self):
        """正常 LLM 调用 → 返回分类结果。"""
        mock_client = AsyncMock()
        mock_client.complete.return_value = json.dumps(
            {
                "mode": "single",
                "confidence": 0.9,
                "reasoning": "test",
            }
        )

        with patch(
            "backend.orchestration.llm_factory.build_llm_client_from_settings",
            return_value=mock_client,
        ):
            classifier = ExecutionModeClassifier()
            plan = FakePlan(tasks=[FakeTask("Task 1"), FakeTask("Task 2")])
            result = await classifier.classify(plan)
            assert result.mode == "single"

    @pytest.mark.asyncio()
    async def test_malformed_json_degrades(self):
        """LLM 返回畸形 JSON → 降级为 ask_user。"""
        mock_client = AsyncMock()
        mock_client.complete.return_value = "not valid json"

        with patch(
            "backend.orchestration.llm_factory.build_llm_client_from_settings",
            return_value=mock_client,
        ):
            classifier = ExecutionModeClassifier()
            plan = FakePlan(tasks=[FakeTask("Task 1")])
            result = await classifier.classify(plan)
            assert result.mode == "ask_user"
            assert "JSON 解析失败" in result.reasoning


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


class TestClassifyExecutionModeFunction:
    """测试便捷函数 classify_execution_mode()。"""

    @pytest.mark.asyncio()
    async def test_convenience_function_equivalent(self):
        """便捷函数与实例方法等价。"""
        mock_client = AsyncMock()
        mock_client.complete.return_value = json.dumps(
            {
                "mode": "multi",
                "confidence": 0.85,
                "reasoning": "test",
            }
        )

        with patch(
            "backend.orchestration.llm_factory.build_llm_client_from_settings",
            return_value=mock_client,
        ):
            plan = FakePlan(
                tasks=[
                    FakeTask("Task 1"),
                    FakeTask("Task 2"),
                    FakeTask("Task 3"),
                ]
            )
            result = await classify_execution_mode(plan)
            assert result.mode == "multi"
            assert result.confidence == 0.85


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


class TestExecutionModeClassificationToDict:
    """测试 ExecutionModeClassification.to_dict()。"""

    def test_to_dict(self):
        """to_dict() 返回正确结构。"""
        classification = ExecutionModeClassification(
            mode="multi",
            confidence=0.85,
            reasoning="test reasoning",
        )
        result = classification.to_dict()
        assert result == {
            "mode": "multi",
            "confidence": 0.85,
            "reasoning": "test reasoning",
        }
