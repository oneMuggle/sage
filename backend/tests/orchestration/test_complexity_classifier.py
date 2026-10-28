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
