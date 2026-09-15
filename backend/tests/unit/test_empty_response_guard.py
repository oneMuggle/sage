"""双栈收敛切片 B：空响应守卫共享件单元测试。"""

from __future__ import annotations

import pytest

from backend.chat.empty_response_guard import (
    DEFAULT_MAX_RETRIES,
    EMPTY_RESPONSE_ENV,
    EMPTY_RESPONSE_FALLBACK_TEXT,
    EMPTY_RESPONSE_SYSTEM_PROMPT,
    empty_response_max_retries,
    is_blank_response,
)

pytestmark = pytest.mark.unit


class TestEmptyResponseMaxRetries:
    def test_default_is_two(self, monkeypatch):
        monkeypatch.delenv(EMPTY_RESPONSE_ENV, raising=False)
        assert empty_response_max_retries() == DEFAULT_MAX_RETRIES == 2

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv(EMPTY_RESPONSE_ENV, "5")
        assert empty_response_max_retries() == 5

    def test_invalid_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv(EMPTY_RESPONSE_ENV, "not-a-number")
        assert empty_response_max_retries() == DEFAULT_MAX_RETRIES

    def test_zero_disables_guard(self, monkeypatch):
        monkeypatch.setenv(EMPTY_RESPONSE_ENV, "0")
        assert empty_response_max_retries() == 0


class TestIsBlankResponse:
    def test_no_tools_and_blank_content_is_blank(self):
        assert is_blank_response(None, "") is True
        assert is_blank_response(None, "   \n ") is True
        assert is_blank_response([], None) is True

    def test_with_content_is_not_blank(self):
        assert is_blank_response(None, "回复") is False

    def test_with_tool_calls_is_not_blank(self):
        assert is_blank_response([object()], "") is False


class TestSharedConstants:
    def test_prompt_shared_between_stacks(self):
        # 两栈注入文案必须逐字一致（对齐验收标准）
        assert "响应内容为空" in EMPTY_RESPONSE_SYSTEM_PROMPT

    def test_fallback_text_nonempty(self):
        assert "空响应" in EMPTY_RESPONSE_FALLBACK_TEXT
