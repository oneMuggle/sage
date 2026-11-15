"""
M5 — orchestration LLM factory unit tests.

Resolves an LLMConfig from persisted app_settings (endpoints +
modelSelections.chatModel) with defensive fallbacks.
"""

from __future__ import annotations

from unittest.mock import patch

from backend.data.settings_repo import SettingsRepository
from backend.orchestration.llm_factory import (
    DEFAULT_MODEL,
    build_httpx_adapter_from_settings,
    build_llm_client_from_settings,
    find_endpoint_for_model,
    load_llm_config_for_chat,
    load_llm_config_from_settings,
    resolve_model_from_settings,
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


    def test_discovered_model_is_resolved(self):
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

        assert resolve_model_from_settings() == "discovered-model"

    def test_selected_ollama_endpoint_resolves_selected_model(self):
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

        # L3: ProviderClient 家族删除后, ollama 协议仅做白名单校验,
        # 解析结果为模型名 (不再构造客户端实例)。
        assert resolve_model_from_settings() == "llama3"

    def test_openai_compatible_allows_empty_api_key_in_config(self):
        """openai-compatible 协议允许空 apiKey，应返回有效配置而非 None。"""
        _seed_settings(
            {
                "endpoints": [
                    {
                        "id": "proxy",
                        "protocol": "openai-compatible",
                        "baseUrl": "http://internal-proxy.local/v1",
                        "apiKey": "",  # 空字符串 - 内网代理不需要密钥
                        "discoveredModels": [{"id": "internal-model"}],
                    }
                ],
                "modelSelections": {
                    "chatModel": {"endpointId": "proxy", "modelId": "internal-model"}
                },
            }
        )
        cfg = load_llm_config_from_settings()
        assert cfg is not None, "openai-compatible 协议应允许空 apiKey"
        assert cfg["api_key"] == ""
        assert cfg["base_url"] == "http://internal-proxy.local/v1"
        assert cfg["model"] == "internal-model"

    def test_ollama_allows_empty_api_key_in_config(self):
        """ollama 协议允许空 apiKey，应返回有效配置而非 None。"""
        _seed_settings(
            {
                "endpoints": [
                    {
                        "id": "local",
                        "protocol": "ollama",
                        "baseUrl": "http://localhost:11434/v1",
                        "apiKey": "",
                        "discoveredModels": [{"id": "llama3"}],
                    }
                ],
                "modelSelections": {
                    "chatModel": {"endpointId": "local", "modelId": "llama3"}
                },
            }
        )
        cfg = load_llm_config_from_settings()
        assert cfg is not None, "ollama 协议应允许空 apiKey"
        assert cfg["api_key"] == ""
        assert cfg["base_url"] == "http://localhost:11434/v1"
        assert cfg["model"] == "llama3"

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

        assert resolve_model_from_settings() == "local-model"

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

        assert resolve_model_from_settings() is None


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


class TestBuildHttpxAdapter:
    """Background memory extraction must never fall back to a default
    ``api.openai.com`` adapter with an empty key — that stalled chat
    completion for 136s (three 60s timeouts) before DONE was queued."""

    def test_none_when_unconfigured(self):
        assert build_httpx_adapter_from_settings() is None

    def test_binds_persisted_endpoint(self):
        _seed_settings(
            {
                "endpoints": [
                    {
                        "id": "e1",
                        "name": "local",
                        "protocol": "openai-compatible",
                        "baseUrl": "http://127.0.0.1:1234/v1",
                        "apiKey": "k",
                        "discoveredModels": [{"id": "local-model"}],
                    }
                ],
                "modelSelections": {"chatModel": {"endpointId": "e1", "modelId": "local-model"}},
            }
        )

        adapter = build_httpx_adapter_from_settings()
        assert adapter is not None
        assert adapter._client.config.base_url == "http://127.0.0.1:1234/v1"
        assert adapter._client.config.api_key == "k"
        assert adapter._client.config.model == "local-model"

    def test_endpoint_without_api_key_yields_none(self):
        # protocol 缺失（默认 openai-compatible 只在 protocol 字段存在时被
        # 显式放行）→ 无法确定端点可用，降级关键词抽取。
        _seed_settings(
            {"endpoints": [{"id": "e1", "name": "x", "baseUrl": "http://a"}]}
        )
        assert build_httpx_adapter_from_settings() is None

    def test_keyless_local_endpoint_builds_adapter(self):
        # ollama / 本地 openai-compatible 允许无 apiKey；此前 ``endpoint["apiKey"]``
        # 直接下标会在启动期抛 KeyError，让后端 lifespan 起不来。
        _seed_settings(
            {
                "endpoints": [
                    {
                        "id": "e1",
                        "name": "ollama",
                        "protocol": "ollama",
                        "baseUrl": "http://127.0.0.1:11434",
                    }
                ],
                "modelSelections": {"chatModel": {"endpointId": "e1", "modelId": "qwen3"}},
            }
        )

        adapter = build_httpx_adapter_from_settings()
        assert adapter is not None
        assert adapter._client.config.api_key == ""
        assert adapter._client.config.base_url == "http://127.0.0.1:11434"


class TestFindEndpointForModel:
    """2026-11-15: 会话模型覆盖路由修复 — 辅助函数单元测试。"""

    def test_returns_none_when_settings_unavailable(self, monkeypatch):
        """数据库不可用时返回 None（不抛异常）。"""
        # 清空所有设置
        SettingsRepository().set_json("app_settings", {}, category="general")
        result = find_endpoint_for_model("nonexistent-model")
        assert result is None

    def test_returns_none_when_model_not_found(self):
        """模型在所有端点都不存在时返回 None。"""
        _seed_settings(
            {
                "endpoints": [
                    {
                        "id": "e1",
                        "name": "first",
                        "baseUrl": "http://a",
                        "apiKey": "k1",
                        "discoveredModels": [{"id": "model-a"}],
                    }
                ]
            }
        )
        result = find_endpoint_for_model("nonexistent-model")
        assert result is None

    def test_returns_endpoint_with_api_key_preference(self):
        """同一模型出现在多个端点时，优先选择有 apiKey 的端点。"""
        _seed_settings(
            {
                "endpoints": [
                    {
                        "id": "e1",
                        "name": "no-key",
                        "baseUrl": "http://a",
                        "discoveredModels": [{"id": "shared-model"}],
                    },
                    {
                        "id": "e2",
                        "name": "with-key",
                        "baseUrl": "http://b",
                        "apiKey": "k2",
                        "discoveredModels": [{"id": "shared-model"}],
                    },
                ]
            }
        )
        result = find_endpoint_for_model("shared-model")
        assert result is not None
        assert result["id"] == "e2"
        assert result["apiKey"] == "k2"

    def test_returns_first_endpoint_when_no_key(self):
        """所有端点都无 apiKey 时返回第一个匹配端点。"""
        _seed_settings(
            {
                "endpoints": [
                    {
                        "id": "e1",
                        "name": "first",
                        "baseUrl": "http://a",
                        "discoveredModels": [{"id": "model-x"}],
                    },
                    {
                        "id": "e2",
                        "name": "second",
                        "baseUrl": "http://b",
                        "discoveredModels": [{"id": "model-x"}],
                    },
                ]
            }
        )
        result = find_endpoint_for_model("model-x")
        assert result is not None
        assert result["id"] == "e1"

    def test_ignores_endpoints_without_discovered_models(self):
        """discoveredModels 为空或不存在时跳过该端点。"""
        _seed_settings(
            {
                "endpoints": [
                    {"id": "e1", "name": "no-models", "baseUrl": "http://a"},
                    {
                        "id": "e2",
                        "name": "with-model",
                        "baseUrl": "http://b",
                        "apiKey": "k2",
                        "discoveredModels": [{"id": "target-model"}],
                    },
                ]
            }
        )
        result = find_endpoint_for_model("target-model")
        assert result is not None
        assert result["id"] == "e2"


class TestLoadLLMConfigForChatWithSessionOverride:
    """2026-11-15: 会话模型覆盖路由修复 — 端到端测试。"""

    def test_session_override_switches_endpoint_credentials(self, monkeypatch):
        """会话覆盖到不同端点的模型时，必须切换凭据。"""
        _seed_settings(
            {
                "endpoints": [
                    {
                        "id": "deepseek",
                        "name": "DeepSeek",
                        "baseUrl": "https://api.deepseek.com/v1",
                        "apiKey": "sk-deepseek-key",
                        "protocol": "openai-compatible",
                        "discoveredModels": [{"id": "deepseek-chat"}],
                    },
                    {
                        "id": "minimax",
                        "name": "MiniMax",
                        "baseUrl": "https://api.minimax.chat/v1",
                        "apiKey": "sk-minimax-key",
                        "protocol": "openai-compatible",
                        "discoveredModels": [{"id": "MiniMax-M3.1-Flash"}],
                    },
                ],
                "modelSelections": {
                    "chatModel": {"endpointId": "deepseek", "modelId": "deepseek-chat"}
                },
            }
        )

        # Mock session_model_overrides
        with patch(
            "backend.orchestration.llm_factory.resolve_chat_model",
            return_value="MiniMax-M3.1-Flash",
        ):
            cfg = load_llm_config_for_chat(session_id="test-session")

        assert cfg is not None
        # 必须切换到 MiniMax 端点的凭据，而非 DeepSeek
        assert cfg["api_key"] == "sk-minimax-key"
        assert cfg["base_url"] == "https://api.minimax.chat/v1"
        assert cfg["model"] == "MiniMax-M3.1-Flash"
        assert cfg["endpoint_id"] == "minimax"

    def test_session_override_same_endpoint_no_switch(self, monkeypatch):
        """会话覆盖到同一端点的模型时，不切换凭据。"""
        _seed_settings(
            {
                "endpoints": [
                    {
                        "id": "deepseek",
                        "name": "DeepSeek",
                        "baseUrl": "https://api.deepseek.com/v1",
                        "apiKey": "sk-deepseek-key",
                        "protocol": "openai-compatible",
                        "discoveredModels": [{"id": "deepseek-chat"}, {"id": "deepseek-coder"}],
                    }
                ],
                "modelSelections": {
                    "chatModel": {"endpointId": "deepseek", "modelId": "deepseek-chat"}
                },
            }
        )

        with patch(
            "backend.orchestration.llm_factory.resolve_chat_model",
            return_value="deepseek-coder",
        ):
            cfg = load_llm_config_for_chat(session_id="test-session")

        assert cfg is not None
        # 同一端点，凭据不变
        assert cfg["api_key"] == "sk-deepseek-key"
        assert cfg["base_url"] == "https://api.deepseek.com/v1"
        assert cfg["model"] == "deepseek-coder"

    def test_session_override_model_not_found_keeps_base(self, monkeypatch):
        """会话覆盖的模型在所有端点都找不到时，保留基础配置（fail-open）。"""
        _seed_settings(
            {
                "endpoints": [
                    {
                        "id": "deepseek",
                        "name": "DeepSeek",
                        "baseUrl": "https://api.deepseek.com/v1",
                        "apiKey": "sk-deepseek-key",
                        "protocol": "openai-compatible",
                        "discoveredModels": [{"id": "deepseek-chat"}],
                    }
                ],
                "modelSelections": {
                    "chatModel": {"endpointId": "deepseek", "modelId": "deepseek-chat"}
                },
            }
        )

        with patch(
            "backend.orchestration.llm_factory.resolve_chat_model",
            return_value="nonexistent-model",
        ):
            cfg = load_llm_config_for_chat(session_id="test-session")

        assert cfg is not None
        # 找不到对应端点，保留基础配置（只改 model 名）
        assert cfg["api_key"] == "sk-deepseek-key"
        assert cfg["base_url"] == "https://api.deepseek.com/v1"
        assert cfg["model"] == "nonexistent-model"

    def test_no_session_override_uses_global(self):
        """无会话覆盖时，使用全局选择的模型和端点。"""
        _seed_settings(
            {
                "endpoints": [
                    {
                        "id": "deepseek",
                        "name": "DeepSeek",
                        "baseUrl": "https://api.deepseek.com/v1",
                        "apiKey": "sk-deepseek-key",
                        "protocol": "openai-compatible",
                        "discoveredModels": [{"id": "deepseek-chat"}],
                    }
                ],
                "modelSelections": {
                    "chatModel": {"endpointId": "deepseek", "modelId": "deepseek-chat"}
                },
            }
        )

        cfg = load_llm_config_for_chat(session_id="no-override-session")
        assert cfg is not None
        assert cfg["api_key"] == "sk-deepseek-key"
        assert cfg["base_url"] == "https://api.deepseek.com/v1"
        assert cfg["model"] == "deepseek-chat"
