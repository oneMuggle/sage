"""Provider 推理模式适配。"""

from __future__ import annotations

import pytest

from backend.wiki.reasoning import (
    CHAT_DEFAULT_MODE,
    INGEST_DEFAULT_MODE,
    apply_reasoning_to_request,
    get_supported_modes,
    is_mode_supported,
    normalize_mode,
)

pytestmark = pytest.mark.unit


def test_default_modes() -> None:
    assert CHAT_DEFAULT_MODE == "auto"
    assert INGEST_DEFAULT_MODE == "off"


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("openai", ["auto", "low", "medium", "high"]),
        ("anthropic", ["auto", "low", "medium", "high", "max"]),
        ("google", ["auto", "low", "medium", "high", "max"]),
        ("deepseek", ["auto", "high", "max"]),
        ("ollama", ["auto", "low", "medium", "high", "max"]),
    ],
)
def test_supported_modes_per_provider(provider: str, expected: list) -> None:
    assert get_supported_modes(provider) == expected


def test_unknown_provider_only_supports_auto() -> None:
    assert get_supported_modes("custom") == ["auto"]
    assert is_mode_supported("custom", "high") is False


def test_normalize_unsupported_degrades_to_auto() -> None:
    assert normalize_mode("openai", "max") == "auto"
    assert normalize_mode("openai", "high") == "high"


@pytest.mark.parametrize("mode", ["off", "auto"])
def test_off_and_auto_leave_body_untouched(mode: str) -> None:
    body = {"model": "m"}
    assert apply_reasoning_to_request(body, "openai", mode) == {"model": "m"}


def test_openai_uses_reasoning_effort() -> None:
    assert apply_reasoning_to_request({}, "openai", "high") == {"reasoning_effort": "high"}


def test_anthropic_uses_thinking_budget() -> None:
    body = apply_reasoning_to_request({}, "anthropic", "medium")
    assert body == {"thinking": {"type": "enabled", "budget_tokens": 4096}}


def test_google_uses_thinking_config() -> None:
    body = apply_reasoning_to_request({}, "google", "low")
    assert body == {"thinking_config": {"thinking_budget": 1024}}


def test_max_mode_uses_largest_budget() -> None:
    body = apply_reasoning_to_request({}, "anthropic", "max")
    assert body["thinking"]["budget_tokens"] == 20000


def test_unsupported_mode_is_normalized_before_injection() -> None:
    # deepseek 不支持 low → 归一化为 auto → 不注入任何参数
    assert apply_reasoning_to_request({}, "deepseek", "low") == {}


def test_unknown_provider_mode_is_noop() -> None:
    assert apply_reasoning_to_request({}, "custom", "high") == {}


def test_existing_body_keys_are_preserved() -> None:
    body = apply_reasoning_to_request({"model": "m", "temperature": 0}, "openai", "low")
    assert body == {"model": "m", "temperature": 0, "reasoning_effort": "low"}
