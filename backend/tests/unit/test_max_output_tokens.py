"""输出长度上限（maxOutputTokens）解析与优先级单测。

优先级（高 → 低）：ChatRequest > profile.model_config.max_tokens（非占位 4096）
> 全局 app_settings.maxOutputTokens > LLMConfig 默认 4096。
"""

from __future__ import annotations

from backend.core.legacy.llm_client import LLMConfig
from backend.data.settings_repo import SettingsRepository
from backend.orchestration.llm_factory import (
    load_llm_config_for_chat,
    load_llm_config_from_settings,
    load_max_output_tokens_from_settings,
    resolve_max_output_tokens,
)

_ENDPOINT = {
    "id": "e1",
    "name": "test",
    "baseUrl": "http://localhost/v1",
    "apiKey": "k",
    "protocol": "openai-compatible",
}


def _seed(settings: dict) -> None:
    SettingsRepository().set_json("app_settings", settings, category="general")


class TestSettingsLevel:
    def test_missing_setting_returns_none(self):
        _seed({"endpoints": [_ENDPOINT]})
        assert load_max_output_tokens_from_settings() is None

    def test_valid_setting_is_read(self):
        _seed({"endpoints": [_ENDPOINT], "maxOutputTokens": 8192})
        assert load_max_output_tokens_from_settings() == 8192

    def test_out_of_range_is_clamped(self):
        _seed({"endpoints": [_ENDPOINT], "maxOutputTokens": 100})
        assert load_max_output_tokens_from_settings() == 512
        _seed({"endpoints": [_ENDPOINT], "maxOutputTokens": 999_999})
        assert load_max_output_tokens_from_settings() == 32768

    def test_invalid_types_are_ignored(self):
        for bad in (0, -1, True, "8192", 8192.5):
            _seed({"endpoints": [_ENDPOINT], "maxOutputTokens": bad})
            assert load_max_output_tokens_from_settings() is None, bad

    def test_llm_config_carries_max_tokens(self):
        _seed({"endpoints": [_ENDPOINT], "maxOutputTokens": 12288})
        cfg = load_llm_config_from_settings()
        assert cfg is not None
        assert cfg["max_tokens"] == 12288
        assert LLMConfig(**cfg).max_tokens == 12288

    def test_llm_config_omits_max_tokens_when_unset(self):
        _seed({"endpoints": [_ENDPOINT]})
        cfg = load_llm_config_from_settings()
        assert cfg is not None
        assert "max_tokens" not in cfg
        assert LLMConfig(**cfg).max_tokens == 4096


class TestResolvePriority:
    def test_request_wins_over_all(self):
        _seed({"endpoints": [_ENDPOINT], "maxOutputTokens": 8192})
        assert resolve_max_output_tokens(
            profile_max_tokens=16384, request_max_tokens=2048
        ) == 2048

    def test_profile_wins_over_global(self):
        _seed({"endpoints": [_ENDPOINT], "maxOutputTokens": 8192})
        assert resolve_max_output_tokens(profile_max_tokens=16384) == 16384

    def test_profile_placeholder_falls_back_to_global(self):
        _seed({"endpoints": [_ENDPOINT], "maxOutputTokens": 8192})
        assert resolve_max_output_tokens(profile_max_tokens=4096) == 8192

    def test_nothing_configured_returns_none(self):
        _seed({"endpoints": [_ENDPOINT]})
        assert resolve_max_output_tokens() is None
        assert resolve_max_output_tokens(profile_max_tokens=4096) is None


class TestLoadForChat:
    def test_profile_max_tokens_overrides_global(self):
        _seed({"endpoints": [_ENDPOINT], "maxOutputTokens": 8192})
        cfg = load_llm_config_for_chat(profile_max_tokens=16384)
        assert cfg is not None
        assert cfg["max_tokens"] == 16384

    def test_global_applies_without_profile_value(self):
        _seed({"endpoints": [_ENDPOINT], "maxOutputTokens": 8192})
        cfg = load_llm_config_for_chat(profile_max_tokens=4096)
        assert cfg is not None
        assert cfg["max_tokens"] == 8192

    def test_profile_value_is_clamped(self):
        _seed({"endpoints": [_ENDPOINT], "maxOutputTokens": 8192})
        cfg = load_llm_config_for_chat(profile_max_tokens=1_000_000)
        assert cfg is not None
        assert cfg["max_tokens"] == 32768
