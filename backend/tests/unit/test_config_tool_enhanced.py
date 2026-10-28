"""Tests for enhanced config_tool: endpoint CRUD and model_selection update.

2026-10-28: 增强 LLM 配置能力，支持 endpoints 和 modelSelections 完整 CRUD。
"""
from __future__ import annotations

import pytest

from backend.tools.config_tool import (
    ReadSageConfigTool,
    UpdateSageConfigTool,
    _validate_endpoint_updates,
    _validate_model_selection_updates,
)


class TestValidateEndpointUpdates:
    """测试 endpoint 字段验证函数。"""

    def test_valid_protocol(self):
        """有效 protocol 应通过验证。"""
        for protocol in ["openai-compatible", "anthropic", "gemini", "ollama"]:
            result = _validate_endpoint_updates({"protocol": protocol})
            assert result is None

    def test_invalid_protocol(self):
        """无效 protocol 应返回错误。"""
        result = _validate_endpoint_updates({"protocol": "invalid"})
        assert result is not None
        assert "protocol 必须是" in result

    def test_valid_base_url(self):
        """有效 baseUrl 应通过验证。"""
        result = _validate_endpoint_updates({"baseUrl": "https://api.openai.com/v1"})
        assert result is None

    def test_invalid_base_url_empty(self):
        """空 baseUrl 应返回错误。"""
        result = _validate_endpoint_updates({"baseUrl": ""})
        assert result is not None
        assert "baseUrl 必须是" in result

    def test_invalid_base_url_no_scheme(self):
        """没有 http/https 前缀的 baseUrl 应返回错误。"""
        result = _validate_endpoint_updates({"baseUrl": "api.openai.com"})
        assert result is not None
        assert "http://" in result or "https://" in result

    def test_valid_api_key(self):
        """有效 apiKey 应通过验证。"""
        result = _validate_endpoint_updates({"apiKey": "sk-test123"})
        assert result is None

    def test_null_api_key(self):
        """null apiKey 应通过验证（允许清空）。"""
        result = _validate_endpoint_updates({"apiKey": None})
        assert result is None

    def test_invalid_api_key_type(self):
        """非字符串 apiKey 应返回错误。"""
        result = _validate_endpoint_updates({"apiKey": 12345})
        assert result is not None
        assert "apiKey 必须是字符串" in result


class TestValidateModelSelectionUpdates:
    """测试 model_selection 字段验证函数。"""

    def test_valid_task_type(self):
        """有效 task_type 应通过验证。"""
        for task_type in ["chatModel", "visionModel", "embeddingModel", "ttsModel", "asrModel", "imageGenModel"]:
            result = _validate_model_selection_updates(task_type, {"endpointId": "ep_test"})
            assert result is None

    def test_invalid_task_type(self):
        """无效 task_type 应返回错误。"""
        result = _validate_model_selection_updates("invalidType", {"endpointId": "ep_test"})
        assert result is not None
        assert "task_type 必须是" in result

    def test_valid_endpoint_id(self):
        """有效 endpointId 应通过验证。"""
        result = _validate_model_selection_updates("chatModel", {"endpointId": "ep_test123"})
        assert result is None

    def test_null_endpoint_id(self):
        """null endpointId 应通过验证（允许清空绑定）。"""
        result = _validate_model_selection_updates("chatModel", {"endpointId": None})
        assert result is None

    def test_invalid_endpoint_id_type(self):
        """非字符串 endpointId 应返回错误。"""
        result = _validate_model_selection_updates("chatModel", {"endpointId": 123})
        assert result is not None
        assert "endpointId 必须是字符串" in result


class TestReadSageConfigToolEndpoints:
    """测试 ReadSageConfigTool 的 endpoints section。"""

    def test_read_endpoints_section(self, monkeypatch):
        """section='endpoints' 应返回 endpoints 列表。"""
        mock_settings = {
            "endpoints": [
                {"id": "ep_1", "name": "OpenAI", "baseUrl": "https://api.openai.com", "apiKey": "sk-secret"},
                {"id": "ep_2", "name": "Anthropic", "baseUrl": "https://api.anthropic.com", "apiKey": "sk-secret2"},
            ]
        }

        from backend.data import settings_repo
        monkeypatch.setattr(settings_repo.SettingsRepository, "get_json", lambda self, key: mock_settings if key == "app_settings" else None)

        tool = ReadSageConfigTool()
        result = tool.execute(section="endpoints")

        assert result.success is True
        assert "endpoints" in result.content["data"]
        assert len(result.content["data"]["endpoints"]) == 2
        # apiKey 应被脱敏
        assert result.content["data"]["endpoints"][0]["apiKey"] == "***"

    def test_read_all_includes_endpoints(self, monkeypatch):
        """section='all' 应包含 endpoints。"""
        mock_settings = {
            "endpoints": [{"id": "ep_1", "name": "Test", "apiKey": "sk-secret"}],
            "orch": {"maxRetries": 2},
        }

        from backend.data import settings_repo
        monkeypatch.setattr(settings_repo.SettingsRepository, "get_json", lambda self, key: mock_settings if key == "app_settings" else None)

        tool = ReadSageConfigTool()
        result = tool.execute(section="all")

        assert result.success is True
        assert "endpoints" in result.content["data"]
        assert len(result.content["data"]["endpoints"]) == 1


class TestUpdateSageConfigToolEndpointCRUD:
    """测试 UpdateSageConfigTool 的 endpoint CRUD 操作。"""

    def test_create_endpoint(self, monkeypatch):
        """创建 endpoint 应成功。"""
        stored_settings = {}

        from backend.data import settings_repo

        def mock_get_json(self, key):
            return stored_settings.get(key)

        def mock_set_json(self, key, value, category="general"):
            stored_settings[key] = value

        monkeypatch.setattr(settings_repo.SettingsRepository, "get_json", mock_get_json)
        monkeypatch.setattr(settings_repo.SettingsRepository, "set_json", mock_set_json)

        tool = UpdateSageConfigTool()
        result = tool.execute(
            target="endpoint",
            action="create",
            updates={"name": "Test", "baseUrl": "https://api.test.com", "apiKey": "sk-test"},
        )

        assert result.success is True
        assert "endpoint_id" in result.content
        # 验证已保存
        assert "endpoints" in stored_settings["app_settings"]
        assert len(stored_settings["app_settings"]["endpoints"]) == 1

    def test_create_endpoint_missing_base_url(self, monkeypatch):
        """创建 endpoint 缺少 baseUrl 应失败。"""
        from backend.data import settings_repo
        monkeypatch.setattr(settings_repo.SettingsRepository, "get_json", lambda self, key: {} if key == "app_settings" else None)

        tool = UpdateSageConfigTool()
        result = tool.execute(
            target="endpoint",
            action="create",
            updates={"name": "Test"},
        )

        assert result.success is False
        assert "baseUrl 为必填" in result.error

    def test_update_endpoint(self, monkeypatch):
        """更新 endpoint 应成功。"""
        stored_settings = {
            "app_settings": {
                "endpoints": [
                    {"id": "ep_1", "name": "Old Name", "baseUrl": "https://old.com"},
                ]
            }
        }

        from backend.data import settings_repo
        monkeypatch.setattr(settings_repo.SettingsRepository, "get_json", lambda self, key: stored_settings.get(key))
        monkeypatch.setattr(settings_repo.SettingsRepository, "set_json", lambda self, key, value, category="general": stored_settings.update({key: value}))

        tool = UpdateSageConfigTool()
        result = tool.execute(
            target="endpoint",
            action="update",
            endpoint_id="ep_1",
            updates={"name": "New Name"},
        )

        assert result.success is True
        assert stored_settings["app_settings"]["endpoints"][0]["name"] == "New Name"

    def test_delete_endpoint(self, monkeypatch):
        """删除 endpoint 应成功。"""
        stored_settings = {
            "app_settings": {
                "endpoints": [
                    {"id": "ep_1", "name": "Test 1"},
                    {"id": "ep_2", "name": "Test 2"},
                ]
            }
        }

        from backend.data import settings_repo
        monkeypatch.setattr(settings_repo.SettingsRepository, "get_json", lambda self, key: stored_settings.get(key))
        monkeypatch.setattr(settings_repo.SettingsRepository, "set_json", lambda self, key, value, category="general": stored_settings.update({key: value}))

        tool = UpdateSageConfigTool()
        result = tool.execute(
            target="endpoint",
            action="delete",
            endpoint_id="ep_1",
        )

        assert result.success is True
        assert len(stored_settings["app_settings"]["endpoints"]) == 1
        assert stored_settings["app_settings"]["endpoints"][0]["id"] == "ep_2"

    def test_list_endpoints(self, monkeypatch):
        """列出 endpoints 应返回脱敏后的列表。"""
        stored_settings = {
            "app_settings": {
                "endpoints": [
                    {"id": "ep_1", "name": "Test", "apiKey": "sk-secret"},
                ]
            }
        }

        from backend.data import settings_repo
        monkeypatch.setattr(settings_repo.SettingsRepository, "get_json", lambda self, key: stored_settings.get(key))

        tool = UpdateSageConfigTool()
        result = tool.execute(target="endpoint", action="list")

        assert result.success is True
        assert result.content["count"] == 1
        # apiKey 应被脱敏
        assert result.content["endpoints"][0]["apiKey"] == "***"


class TestUpdateSageConfigToolModelSelection:
    """测试 UpdateSageConfigTool 的 model_selection 更新。"""

    def test_update_model_selection(self, monkeypatch):
        """更新 model_selection 应成功。"""
        stored_settings = {
            "app_settings": {
                "endpoints": [{"id": "ep_1", "name": "Test"}],
                "modelSelections": {},
            }
        }

        from backend.data import settings_repo
        monkeypatch.setattr(settings_repo.SettingsRepository, "get_json", lambda self, key: stored_settings.get(key))
        monkeypatch.setattr(settings_repo.SettingsRepository, "set_json", lambda self, key, value, category="general": stored_settings.update({key: value}))

        tool = UpdateSageConfigTool()
        result = tool.execute(
            target="model_selection",
            task_type="chatModel",
            updates={"endpointId": "ep_1", "modelId": "gpt-4"},
        )

        assert result.success is True
        assert stored_settings["app_settings"]["modelSelections"]["chatModel"]["endpointId"] == "ep_1"

    def test_update_model_selection_invalid_endpoint(self, monkeypatch):
        """引用不存在的 endpoint 应失败。"""
        stored_settings = {
            "app_settings": {
                "endpoints": [],  # 空的 endpoints
                "modelSelections": {},
            }
        }

        from backend.data import settings_repo
        monkeypatch.setattr(settings_repo.SettingsRepository, "get_json", lambda self, key: stored_settings.get(key))

        tool = UpdateSageConfigTool()
        result = tool.execute(
            target="model_selection",
            task_type="chatModel",
            updates={"endpointId": "ep_nonexistent"},
        )

        assert result.success is False
        assert "不存在" in result.error

    def test_update_model_selection_missing_task_type(self, monkeypatch):
        """缺少 task_type 应失败。"""
        from backend.data import settings_repo
        monkeypatch.setattr(settings_repo.SettingsRepository, "get_json", lambda self, key: {} if key == "app_settings" else None)

        tool = UpdateSageConfigTool()
        result = tool.execute(
            target="model_selection",
            updates={"endpointId": "ep_1"},
        )

        assert result.success is False
        assert "task_type" in result.error
