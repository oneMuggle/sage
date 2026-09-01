"""
M5 — orchestration LLM factory unit tests.

Resolves an LLMConfig from persisted app_settings (endpoints +
modelSelections.chatModel) with defensive fallbacks.
"""

from __future__ import annotations

from backend.data.settings_repo import SettingsRepository
from backend.orchestration.llm_factory import (
    DEFAULT_MODEL,
    build_llm_client_from_settings,
    build_provider_client_from_settings,
    load_llm_config_from_settings,
    resolve_provider_and_model_from_settings,
)


def _seed_settings(settings: dict) -> None:
    SettingsRepository().set_json("app_settings", settings, category="general")


class TestLoadLLMConfig:
    def test_no_settings_returns_none(self):
        assert load_llm_config_from_settings() is None

    def test_no_endpoints_returns_none(self):
        _seed_settings({"streaming": True})
        assert load_llm_config_from_settings() is None

    def test_endpoint_without_api_key_returns_none(self):
        _seed_settings({"endpoints": [{"id": "e1", "name": "n", "baseUrl": "http://x"}]})
        assert load_llm_config_from_settings() is None

    def test_chat_model_selection_wins(self):
        _seed_settings(
            {
                "endpoints": [
                    {"id": "e1", "name": "first", "baseUrl": "http://a", "apiKey": "k1"},
                    {
                        "id": "e2",
                        "name": "second",
                        "baseUrl": "http://b",
                        "apiKey": "k2",
                        "discoveredModels": [{"id": "model-b"}],
                    },
                ],
                "modelSelections": {"chatModel": {"endpointId": "e2", "modelId": "model-x"}},
            }
        )
        cfg = load_llm_config_from_settings()
        assert cfg is not None
        assert cfg["api_key"] == "k2"
        assert cfg["base_url"] == "http://b"
        assert cfg["model"] == "model-x"

    def test_first_usable_endpoint_fallback_with_discovered_model(self):
        _seed_settings(
            {
                "endpoints": [
                    {"id": "e1", "name": "no-key", "baseUrl": "http://a"},
                    {
                        "id": "e2",
                        "name": "usable",
                        "baseUrl": "http://b",
                        "apiKey": "k2",
                        "discoveredModels": [{"id": "model-b"}],
                    },
                ]
            }
        )
        cfg = load_llm_config_from_settings()
        assert cfg["api_key"] == "k2"
        assert cfg["model"] == "model-b"

    def test_default_model_when_no_discovery(self):
        _seed_settings(
            {"endpoints": [{"id": "e1", "name": "x", "baseUrl": "http://a", "apiKey": "k"}]}
        )
        cfg = load_llm_config_from_settings()
        assert cfg["model"] == DEFAULT_MODEL

    def test_legacy_snake_case_settings_normalized(self):
        """Legacy snake_case residue (base_url/api_key) still resolves."""
        _seed_settings(
            {
                "endpoints": [
                    {"id": "e1", "name": "legacy", "base_url": "http://l", "api_key": "kl"}
                ]
            }
        )
        cfg = load_llm_config_from_settings()
        assert cfg is not None
        assert cfg["base_url"] == "http://l"
        assert cfg["api_key"] == "kl"

    def test_corrupted_top_level_returns_none(self):
        _seed_settings(["not", "a", "dict"])
        assert load_llm_config_from_settings() is None


    def test_discovered_model_is_resolved_with_provider(self):
        _seed_settings(
            {
                "endpoints": [
                    {
                        "id": "local",
                        "protocol": "ollama",
                        "baseUrl": "http://localhost:11434/v1",
                        "apiKey": "",
                        "discoveredModels": [{"id": "discovered-model"}],
                    }
                ],
                "modelSelections": {"chatModel": {"endpointId": "local"}},
            }
        )

        resolved = resolve_provider_and_model_from_settings()

        assert resolved is not None
        assert resolved[1] == "discovered-model"

    def test_unknown_protocol_fails_closed(self):
        _seed_settings(
            {
                "endpoints": [
                    {
                        "id": "unknown",
                        "protocol": "not-supported",
                        "baseUrl": "https://api.example.test/v1",
                        "apiKey": "key",
                    }
                ],
                "modelSelections": {"chatModel": {"endpointId": "unknown"}},
            }
        )

        assert resolve_provider_and_model_from_settings() is None

        _seed_settings(
            {
                "endpoints": [
                    {
                        "id": "local",
                        "protocol": "ollama",
                        "baseUrl": "http://localhost:11434/v1",
                        "apiKey": "",
                    },
                    {
                        "id": "remote",
                        "protocol": "openai-compatible",
                        "baseUrl": "https://api.example.test/v1",
                        "apiKey": "remote-key",
                    },
                ],
                "modelSelections": {"chatModel": {"endpointId": "local", "modelId": "llama3"}},
            }
        )

        client = build_provider_client_from_settings(model="llama3")

        from backend.adapters.out.llm.ollama import OllamaProvider

        assert isinstance(client, OllamaProvider)
        assert client._api_key == ""
        assert client._base_url == "http://localhost:11434/v1"

    def test_selected_openai_compatible_endpoint_allows_empty_api_key(self):
        _seed_settings(
            {
                "endpoints": [
                    {
                        "id": "local-compatible",
                        "protocol": "openai-compatible",
                        "baseUrl": "http://localhost:8080/v1",
                        "apiKey": "",
                    },
                    {
                        "id": "remote",
                        "protocol": "openai-compatible",
                        "baseUrl": "https://api.example.test/v1",
                        "apiKey": "remote-key",
                    },
                ],
                "modelSelections": {
                    "chatModel": {"endpointId": "local-compatible", "modelId": "local-model"}
                },
            }
        )

        client = build_provider_client_from_settings(model="local-model")

        from backend.adapters.out.llm.openai import OpenAIProvider

        assert isinstance(client, OpenAIProvider)
        assert client._api_key == ""
        assert client._base_url == "http://localhost:8080/v1"

    def test_selected_endpoint_without_base_url_does_not_fallback(self):
        _seed_settings(
            {
                "endpoints": [
                    {"id": "selected", "protocol": "ollama", "apiKey": ""},
                    {
                        "id": "fallback",
                        "protocol": "openai-compatible",
                        "baseUrl": "https://api.example.test/v1",
                        "apiKey": "fallback-key",
                    },
                ],
                "modelSelections": {"chatModel": {"endpointId": "selected", "modelId": "local-model"}},
            }
        )

        assert build_provider_client_from_settings(model="local-model") is None


class TestBuildClient:
    def test_builds_real_client_when_configured(self):
        _seed_settings(
            {"endpoints": [{"id": "e1", "name": "x", "baseUrl": "http://a", "apiKey": "k"}]}
        )
        client = build_llm_client_from_settings()
        assert client is not None
        assert hasattr(client, "complete")

    def test_none_when_unconfigured(self):
        assert build_llm_client_from_settings() is None
