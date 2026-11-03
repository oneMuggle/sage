"""思考过程参数 (reasoningEffort / thinkingBudget) 校验测试.

2026-11-03: per-endpoint 思考过程参数落地后新增。

覆盖:
- validate_reasoning_effort 值域 (low/medium/high; None/'' = 未设置)
- validate_thinking_budget 值域 (int >= -1; None = 未设置)
- validate_endpoint_payload 集成调用两个校验器
- strip_unknown_fields 保留两键 (后端白名单已登记, 否则静默丢弃)
- to_camel / from_camel snake 往返 (Electron relay camelToSnakeKeys)
- classify_settings_validation_error 把两键归到各自类别
"""

from __future__ import annotations

import pytest

from backend.data.settings_canonicalizer import (
    classify_settings_validation_error,
    from_camel,
    strip_unknown_fields,
    to_camel,
    validate_endpoint_payload,
    validate_reasoning_effort,
    validate_thinking_budget,
)


class TestValidateReasoningEffort:
    """reasoningEffort 对应上游 OpenAI ``reasoning_effort``."""

    @pytest.mark.parametrize("value", ["low", "medium", "high"])
    def test_accepts_legal_values(self, value: str) -> None:
        assert validate_reasoning_effort(value) == value

    @pytest.mark.parametrize("value", [None, ""])
    def test_accepts_unset(self, value: object) -> None:
        """None / 空串 = 未设置 → 不发送该键 (上游不进入思考模式)."""
        assert validate_reasoning_effort(value) == value

    @pytest.mark.parametrize("value", ["LOW", "mediumish", "off", "none"])
    def test_rejects_illegal_string(self, value: str) -> None:
        with pytest.raises(ValueError, match="reasoningEffort"):
            validate_reasoning_effort(value)

    @pytest.mark.parametrize("value", [1, True, ["high"], {"v": "high"}])
    def test_rejects_non_string(self, value: object) -> None:
        with pytest.raises(ValueError, match="reasoningEffort"):
            validate_reasoning_effort(value)


class TestValidateThinkingBudget:
    """thinkingBudget 对应上游 thinking.budget_tokens / thinking_budget."""

    @pytest.mark.parametrize("value", [0, 1, 2048, 32768])
    def test_accepts_non_negative_int(self, value: int) -> None:
        assert validate_thinking_budget(value) == value

    def test_accepts_minus_one_as_dynamic_budget(self) -> None:
        """-1 = 动态预算 (与 LLMConfig.thinking_budget 语义一致)."""
        assert validate_thinking_budget(-1) == -1

    def test_accepts_none_as_unset(self) -> None:
        assert validate_thinking_budget(None) is None

    @pytest.mark.parametrize("value", [-2, -100])
    def test_rejects_less_than_minus_one(self, value: int) -> None:
        with pytest.raises(ValueError, match="thinkingBudget"):
            validate_thinking_budget(value)

    @pytest.mark.parametrize("value", [1.5, "2048", True, [2048]])
    def test_rejects_non_int(self, value: object) -> None:
        """bool 是 int 的子类, 必须显式拒绝 (True 不该当 1 放行)."""
        with pytest.raises(ValueError, match="thinkingBudget"):
            validate_thinking_budget(value)


class TestValidateEndpointPayload:
    """validate_endpoint_payload 必须调用两个新校验器."""

    def test_accepts_endpoint_with_both_params(self) -> None:
        ep = {
            "id": "ep-1",
            "name": "Test",
            "baseUrl": "https://api.example.test/v1",
            "reasoningEffort": "high",
            "thinkingBudget": 4096,
        }
        assert validate_endpoint_payload(ep) is ep

    def test_rejects_bad_reasoning_effort(self) -> None:
        with pytest.raises(ValueError, match="reasoningEffort"):
            validate_endpoint_payload({"reasoningEffort": "ultra"})

    def test_rejects_bad_thinking_budget(self) -> None:
        with pytest.raises(ValueError, match="thinkingBudget"):
            validate_endpoint_payload({"thinkingBudget": -5})


class TestWhitelistRoundTrip:
    """后端白名单 + snake 别名 —— relay 往返后必须原样保留."""

    def test_strip_unknown_fields_keeps_both_params(self) -> None:
        cleaned = strip_unknown_fields(
            {
                "endpoints": [
                    {
                        "id": "ep-1",
                        "reasoningEffort": "medium",
                        "thinkingBudget": 2048,
                        "someLegacyField": "drop-me",
                    }
                ]
            }
        )
        ep = cleaned["endpoints"][0]
        assert ep["reasoningEffort"] == "medium"
        assert ep["thinkingBudget"] == 2048
        assert "someLegacyField" not in ep

    def test_to_camel_translates_snake_params(self) -> None:
        """Electron relay 把 camelCase 转 snake, 后端 to_camel 必须翻回来."""
        translated = to_camel(
            {
                "reasoning_effort": "high",
                "thinking_budget": 4096,
            }
        )
        assert translated["reasoningEffort"] == "high"
        assert translated["thinkingBudget"] == 4096

    def test_from_camel_roundtrip(self) -> None:
        snake = from_camel({"reasoningEffort": "low", "thinkingBudget": 1024})
        assert snake["reasoning_effort"] == "low"
        assert snake["thinking_budget"] == 1024


class TestClassifyValidationError:
    """错误分类不能把用户值回显, 只能给出字段类别."""

    def test_classifies_reasoning_effort(self) -> None:
        with pytest.raises(ValueError, match="reasoningEffort") as excinfo:
            validate_reasoning_effort("ultra")
        assert classify_settings_validation_error(excinfo.value) == "reasoningEffort"

    def test_classifies_thinking_budget(self) -> None:
        with pytest.raises(ValueError, match="thinkingBudget") as excinfo:
            validate_thinking_budget(-5)
        assert classify_settings_validation_error(excinfo.value) == "thinkingBudget"
