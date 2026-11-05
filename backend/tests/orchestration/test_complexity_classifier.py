"""``test_complexity_classifier`` — 复杂度分类器单元测试。

测试策略：
1. 响应解析（_parse_response）：覆盖正常/畸形/非法值场景
2. 降级策略：无 LLM 配置 / LLM 调用失败 / 响应解析失败 → medium 默认
3. 便捷函数：classify_complexity() 与 ComplexityClassifier().classify() 等价

不测试 LLM 调用本身（由 integration test 覆盖），只测试解析逻辑和降级纪律。
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from backend.orchestration.complexity_classifier import (
    ComplexityClassification,
    ComplexityClassifier,
    classify_complexity,
)


class TestComplexityClassifierParseResponse:
    """测试 _parse_response() 方法。"""

    def setup_method(self):
        self.classifier = ComplexityClassifier()

    def test_parse_simple_response(self):
        """正常 simple 响应。"""
        raw = json.dumps(
            {
                "complexity": "simple",
                "research_needed": False,
                "reasoning": "单文件局部修改",
            }
        )
        result = self.classifier._parse_response(raw)
        assert result.complexity == "simple"
        assert result.research_needed is False
        assert result.reasoning == "单文件局部修改"

    def test_parse_medium_response(self):
        """正常 medium 响应。"""
        raw = json.dumps(
            {
                "complexity": "medium",
                "research_needed": False,
                "reasoning": "多文件但逻辑清晰",
            }
        )
        result = self.classifier._parse_response(raw)
        assert result.complexity == "medium"
        assert result.research_needed is False

    def test_parse_complex_response(self):
        """正常 complex 响应。"""
        raw = json.dumps(
            {
                "complexity": "complex",
                "research_needed": True,
                "reasoning": "架构决策 + 需要外部最佳实践",
            }
        )
        result = self.classifier._parse_response(raw)
        assert result.complexity == "complex"
        assert result.research_needed is True

    def test_parse_with_markdown_fence(self):
        """LLM 输出带 markdown 围栏 → 正常解析。"""
        raw = '```json\n{"complexity": "simple", "research_needed": false, "reasoning": "test"}\n```'
        result = self.classifier._parse_response(raw)
        assert result.complexity == "simple"

    def test_parse_empty_response(self):
        """空响应 → 降级为 medium。"""
        result = self.classifier._parse_response("")
        assert result.complexity == "medium"
        assert "空响应" in result.reasoning

    def test_parse_none_response(self):
        """None 响应 → 降级为 medium。"""
        result = self.classifier._parse_response(None)
        assert result.complexity == "medium"

    def test_parse_invalid_json(self):
        """非法 JSON → 降级为 medium。"""
        result = self.classifier._parse_response("not a json")
        assert result.complexity == "medium"
        assert "JSON 解析失败" in result.reasoning

    def test_parse_non_dict_response(self):
        """JSON 但非 dict → 降级为 medium。"""
        result = self.classifier._parse_response('["not", "a", "dict"]')
        assert result.complexity == "medium"
        assert "响应非 dict" in result.reasoning

    def test_parse_invalid_complexity_value(self):
        """非法 complexity 值 → 降级为 medium。"""
        raw = json.dumps(
            {
                "complexity": "invalid",
                "research_needed": False,
                "reasoning": "test",
            }
        )
        result = self.classifier._parse_response(raw)
        assert result.complexity == "medium"
        assert "非法 complexity" in result.reasoning

    def test_parse_missing_research_needed(self):
        """缺失 research_needed → 根据 complexity 推断。"""
        raw = json.dumps({"complexity": "complex", "reasoning": "test"})
        result = self.classifier._parse_response(raw)
        assert result.complexity == "complex"
        assert result.research_needed is True  # complex → True

        raw = json.dumps({"complexity": "simple", "reasoning": "test"})
        result = self.classifier._parse_response(raw)
        assert result.complexity == "simple"
        assert result.research_needed is False  # simple → False

    def test_parse_missing_reasoning(self):
        """缺失 reasoning → 空字符串。"""
        raw = json.dumps({"complexity": "medium", "research_needed": False})
        result = self.classifier._parse_response(raw)
        assert result.complexity == "medium"
        assert result.reasoning == ""


class TestComplexityClassifierDegradation:
    """测试降级策略。"""

    @pytest.mark.asyncio()
    async def test_no_llm_config(self):
        """无 LLM 配置 → 降级为 medium。"""
        with patch(
            "backend.orchestration.llm_factory.build_llm_client_from_settings",
            return_value=None,
        ):
            classifier = ComplexityClassifier()
            result = await classifier.classify("test message")
            assert result.complexity == "medium"
            assert "无 LLM 配置" in result.reasoning

    @pytest.mark.asyncio()
    async def test_llm_call_failure(self):
        """LLM 调用失败 → 降级为 medium。"""
        mock_client = AsyncMock()
        mock_client.complete.side_effect = Exception("LLM error")

        with patch(
            "backend.orchestration.llm_factory.build_llm_client_from_settings",
            return_value=mock_client,
        ):
            classifier = ComplexityClassifier()
            result = await classifier.classify("test message")
            assert result.complexity == "medium"
            assert "LLM 调用失败" in result.reasoning

    @pytest.mark.asyncio()
    async def test_successful_classification(self):
        """正常 LLM 调用 → 返回分类结果。"""
        mock_client = AsyncMock()
        mock_client.complete.return_value = json.dumps(
            {
                "complexity": "simple",
                "research_needed": False,
                "reasoning": "test",
            }
        )

        with patch(
            "backend.orchestration.llm_factory.build_llm_client_from_settings",
            return_value=mock_client,
        ):
            classifier = ComplexityClassifier()
            result = await classifier.classify("test message")
            assert result.complexity == "simple"


class TestClassifyComplexityFunction:
    """测试便捷函数 classify_complexity()。"""

    @pytest.mark.asyncio()
    async def test_convenience_function_equivalent(self):
        """便捷函数与实例方法等价。"""
        mock_client = AsyncMock()
        mock_client.complete.return_value = json.dumps(
            {
                "complexity": "complex",
                "research_needed": True,
                "reasoning": "test",
            }
        )

        with patch(
            "backend.orchestration.llm_factory.build_llm_client_from_settings",
            return_value=mock_client,
        ):
            result = await classify_complexity("test message")
            assert result.complexity == "complex"
            assert result.research_needed is True


class TestComplexityClassificationToDict:
    """测试 ComplexityClassification.to_dict()。"""

    def test_to_dict(self):
        """to_dict() 返回正确结构。"""
        classification = ComplexityClassification(
            complexity="medium",
            research_needed=False,
            reasoning="test reasoning",
        )
        result = classification.to_dict()
        assert result == {
            "complexity": "medium",
            "research_needed": False,
            "reasoning": "test reasoning",
        }


# ---------------------------------------------------------------------------
# M4 · W4: estimate_budget_level
# ---------------------------------------------------------------------------


class TestEstimateBudgetLevel:
    """测试 estimate_budget_level() —— LLM 预算分级。"""

    @pytest.mark.asyncio()
    async def test_llm_success_simple(self):
        """LLM 返回 simple → 正确解析。"""
        from backend.orchestration.complexity_classifier import estimate_budget_level

        mock_client = AsyncMock()
        mock_client.complete = AsyncMock(
            return_value=json.dumps({"level": "simple", "reasoning": "单文件小改"})
        )
        with patch(
            "backend.orchestration.llm_factory.build_llm_client_from_settings",
            return_value=mock_client,
        ):
            result = await estimate_budget_level("修复 typo")
            assert result is not None
            assert result[0] == "simple"
            assert "单文件小改" in result[1]

    @pytest.mark.asyncio()
    async def test_llm_success_long(self):
        """LLM 返回 long → 正确解析。"""
        from backend.orchestration.complexity_classifier import estimate_budget_level

        mock_client = AsyncMock()
        mock_client.complete = AsyncMock(
            return_value=json.dumps({"level": "long", "reasoning": "端到端迁移"})
        )
        with patch(
            "backend.orchestration.llm_factory.build_llm_client_from_settings",
            return_value=mock_client,
        ):
            result = await estimate_budget_level("批量迁移 100 个文件")
            assert result is not None
            assert result[0] == "long"

    @pytest.mark.asyncio()
    async def test_no_llm_config_returns_none(self):
        """无 LLM 配置 → 返回 None（回落启发式）。"""
        from backend.orchestration.complexity_classifier import estimate_budget_level

        with patch(
            "backend.orchestration.llm_factory.build_llm_client_from_settings",
            return_value=None,
        ):
            result = await estimate_budget_level("test")
            assert result is None

    @pytest.mark.asyncio()
    async def test_llm_timeout_returns_none(self):
        """LLM 超时 → 返回 None。"""
        import asyncio

        from backend.orchestration.complexity_classifier import estimate_budget_level

        mock_client = AsyncMock()

        async def slow_complete(prompt):
            await asyncio.sleep(10)
            return '{"level": "medium", "reasoning": "test"}'

        mock_client.complete = slow_complete
        with patch(
            "backend.orchestration.llm_factory.build_llm_client_from_settings",
            return_value=mock_client,
        ):
            result = await estimate_budget_level("test", timeout_s=0.1)
            assert result is None

    @pytest.mark.asyncio()
    async def test_llm_exception_returns_none(self):
        """LLM 调用异常 → 返回 None。"""
        from backend.orchestration.complexity_classifier import estimate_budget_level

        mock_client = AsyncMock()
        mock_client.complete = AsyncMock(side_effect=RuntimeError("网络错误"))
        with patch(
            "backend.orchestration.llm_factory.build_llm_client_from_settings",
            return_value=mock_client,
        ):
            result = await estimate_budget_level("test")
            assert result is None

    @pytest.mark.asyncio()
    async def test_invalid_json_returns_none(self):
        """JSON 解析失败 → 返回 None。"""
        from backend.orchestration.complexity_classifier import estimate_budget_level

        mock_client = AsyncMock()
        mock_client.complete = AsyncMock(return_value="not json")
        with patch(
            "backend.orchestration.llm_factory.build_llm_client_from_settings",
            return_value=mock_client,
        ):
            result = await estimate_budget_level("test")
            assert result is None

    @pytest.mark.asyncio()
    async def test_invalid_level_returns_none(self):
        """非法 level 值 → 返回 None。"""
        from backend.orchestration.complexity_classifier import estimate_budget_level

        mock_client = AsyncMock()
        mock_client.complete = AsyncMock(
            return_value=json.dumps({"level": "invalid", "reasoning": "test"})
        )
        with patch(
            "backend.orchestration.llm_factory.build_llm_client_from_settings",
            return_value=mock_client,
        ):
            result = await estimate_budget_level("test")
            assert result is None

    @pytest.mark.asyncio()
    async def test_empty_response_returns_none(self):
        """空响应 → 返回 None。"""
        from backend.orchestration.complexity_classifier import estimate_budget_level

        mock_client = AsyncMock()
        mock_client.complete = AsyncMock(return_value="")
        with patch(
            "backend.orchestration.llm_factory.build_llm_client_from_settings",
            return_value=mock_client,
        ):
            result = await estimate_budget_level("test")
            assert result is None

    @pytest.mark.asyncio()
    async def test_context_signals_passed_to_prompt(self):
        """context_signals 被正确替换到 prompt。"""
        from backend.orchestration.complexity_classifier import estimate_budget_level

        mock_client = AsyncMock()
        mock_client.complete = AsyncMock(
            return_value=json.dumps({"level": "complex", "reasoning": "test"})
        )
        with patch(
            "backend.orchestration.llm_factory.build_llm_client_from_settings",
            return_value=mock_client,
        ):
            result = await estimate_budget_level(
                "重构认证系统",
                context_signals="- 已绑定到项目工作区\n- 用户提供了附件",
            )
            assert result is not None
            assert result[0] == "complex"
            # 验证 prompt 里包含了 context_signals
            call_args = mock_client.complete.call_args
            prompt = call_args[0][0]
            assert "已绑定到项目工作区" in prompt
            assert "用户提供了附件" in prompt
