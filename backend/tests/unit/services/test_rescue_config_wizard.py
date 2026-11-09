"""Rescue config wizard — pure merge/validation + DB write roundtrip."""
from __future__ import annotations

import json

import pytest

from backend.data.settings_repo import SettingsRepository
from backend.services.rescue import config_wizard as cw
from backend.services.rescue.paths import resolve_db_path, resolve_user_data_dir


class TestPaths:
    def test_user_data_dir_honors_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SAGE_USER_DATA_DIR", str(tmp_path / "ud"))
        assert resolve_user_data_dir() == tmp_path / "ud"

    def test_db_path_honors_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SAGE_DB_PATH", str(tmp_path / "sage.db"))
        assert resolve_db_path() == tmp_path / "sage.db"

    def test_db_path_defaults_under_user_data(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SAGE_DB_PATH", raising=False)
        monkeypatch.setenv("SAGE_USER_DATA_DIR", str(tmp_path / "ud"))
        assert resolve_db_path() == tmp_path / "ud" / "sage.db"


class TestMask:
    def test_masks_middle_keeps_prefix_suffix(self):
        assert cw.mask_secret("sk-1234567890abcd") == "sk-***abcd"

    def test_empty_stays_empty(self):
        assert cw.mask_secret("") == ""
        assert cw.mask_secret(None) == ""

    def test_short_value_fully_hidden(self):
        assert cw.mask_secret("abcd") == "***"


class TestMergeEndpoint:
    def _settings(self):
        return {"version": 1, "endpoints": [], "modelSelections": {}}

    def test_create_generates_id_and_defaults(self):
        settings = self._settings()
        merged, mode = cw.merge_endpoint(
            settings,
            {
                "baseUrl": "http://10.0.0.5:8000/v1",
                "apiKey": "sk-test-key",
                "modelId": "qwen2.5-7b",
            },
        )
        assert mode == "created"
        assert len(merged["endpoints"]) == 1
        ep = merged["endpoints"][0]
        assert ep["id"].startswith("ep_")
        assert ep["protocol"] == "openai-compatible"
        assert ep["name"]
        assert ep["apiKey"] == "sk-test-key"
        assert ep["apiKeyUpdatedAt"] > 0
        assert ep["discoveredModels"] == []
        # 不可变：原 settings 不被修改
        assert settings["endpoints"] == []

    def test_update_preserves_id_and_bumps_timestamp(self):
        settings = {
            "version": 1,
            "endpoints": [
                {
                    "id": "ep-keep",
                    "name": "内网网关",
                    "baseUrl": "http://10.0.0.5:8000/v1",
                    "apiKey": "old-key",
                    "protocol": "openai-compatible",
                    "modelId": "old-model",
                    "apiKeyUpdatedAt": 1000,
                    "discoveredModels": [],
                }
            ],
            "modelSelections": {},
        }
        merged, mode = cw.merge_endpoint(
            settings,
            {"id": "ep-keep", "apiKey": "new-key", "modelId": "new-model"},
        )
        assert mode == "updated"
        ep = merged["endpoints"][0]
        assert ep["id"] == "ep-keep"
        assert ep["name"] == "内网网关"
        assert ep["baseUrl"] == "http://10.0.0.5:8000/v1"
        assert ep["apiKey"] == "new-key"
        assert ep["modelId"] == "new-model"
        assert ep["apiKeyUpdatedAt"] > 1000

    def test_update_without_api_key_keeps_old_key(self):
        settings = {
            "version": 1,
            "endpoints": [
                {
                    "id": "ep-keep",
                    "name": "n",
                    "baseUrl": "http://x/v1",
                    "apiKey": "old-key",
                    "protocol": "openai-compatible",
                    "apiKeyUpdatedAt": 1000,
                    "discoveredModels": [],
                }
            ],
            "modelSelections": {},
        }
        merged, _ = cw.merge_endpoint(settings, {"id": "ep-keep", "modelId": "m2"})
        ep = merged["endpoints"][0]
        assert ep["apiKey"] == "old-key"
        assert ep["apiKeyUpdatedAt"] == 1000

    def test_rejects_duplicate_create(self):
        settings = {
            "version": 1,
            "endpoints": [{"id": "dup", "baseUrl": "http://x/v1"}],
            "modelSelections": {},
        }
        with pytest.raises(cw.RescueConfigError):
            cw.merge_endpoint(settings, {"id": "dup", "baseUrl": "http://y/v1"}, mode="create")

    @pytest.mark.parametrize("bad", ["ftp://x", "x", ""])
    def test_rejects_bad_base_url(self, bad):
        with pytest.raises(cw.RescueConfigError):
            cw.merge_endpoint(
                {"version": 1, "endpoints": [], "modelSelections": {}},
                {"baseUrl": bad},
            )

    def test_rejects_bad_protocol(self):
        with pytest.raises(cw.RescueConfigError):
            cw.merge_endpoint(
                {"version": 1, "endpoints": [], "modelSelections": {}},
                {"baseUrl": "http://x/v1", "protocol": "bogus"},
            )

    def test_new_endpoints_do_not_share_discovered_models_list(self):
        settings = {"version": 1, "endpoints": [], "modelSelections": {}}
        merged, _ = cw.merge_endpoint(settings, {"baseUrl": "http://a/v1"})
        merged, _ = cw.merge_endpoint(merged, {"baseUrl": "http://b/v1"})
        first, second = merged["endpoints"]
        assert first["discoveredModels"] == []
        assert second["discoveredModels"] == []
        assert first["discoveredModels"] is not second["discoveredModels"]


class TestModelSelection:
    def test_sets_chat_model(self):
        settings = {
            "version": 1,
            "endpoints": [
                {"id": "ep1", "baseUrl": "http://x/v1", "discoveredModels": []}
            ],
            "modelSelections": {},
        }
        merged = cw.merge_model_selection(settings, "chatModel", "ep1", "m1")
        assert merged["modelSelections"]["chatModel"] == {
            "endpointId": "ep1",
            "modelId": "m1",
        }
        assert settings["modelSelections"] == {}

    def test_rejects_unknown_endpoint(self):
        with pytest.raises(cw.RescueConfigError):
            cw.merge_model_selection(
                {"version": 1, "endpoints": [], "modelSelections": {}},
                "chatModel",
                "nope",
                "m1",
            )


class TestSaveEndpoint:
    def test_writes_encrypted_and_creates_backup(self, monkeypatch):
        monkeypatch.setenv("SAGE_SECRET_SCHEME", "test")
        calls = []

        def fake_backup(reason="manual", db_path=None):
            calls.append((reason, db_path))
            return {"name": "sage-backup-test.db"}

        monkeypatch.setattr(cw, "create_backup", fake_backup)

        result = cw.save_endpoint(
            {
                "baseUrl": "http://10.0.0.5:8000/v1",
                "apiKey": "sk-very-secret",
                "modelId": "qwen2.5-7b",
            }
        )
        assert result["mode"] == "created"
        assert calls
        assert calls[0][0] == "rescue"

        repo = SettingsRepository()
        settings = repo.get_json("app_settings")
        assert settings["endpoints"][0]["apiKey"] == "sk-very-secret"
        assert settings["endpoints"][0]["apiKeyUpdatedAt"] > 0

        # 原始落库值必须加密，不能出现明文 key
        from backend.data.database import get_database

        row = (
            get_database()
            .get_connection()
            .execute("SELECT value FROM preferences WHERE key='app_settings'")
            .fetchone()
        )
        assert row is not None
        assert "sk-very-secret" not in row["value"]
        assert "enc:test:v1:" in row["value"]

    def test_update_missing_endpoint_raises(self):
        with pytest.raises(cw.RescueConfigError):
            cw.save_endpoint(
                {"id": "missing", "baseUrl": "http://x/v1"},
                mode="update",
                backup=False,
            )

    def test_aborts_when_backup_fails(self, monkeypatch):
        monkeypatch.setattr(cw, "create_backup", lambda *a, **k: None)
        with pytest.raises(cw.RescueConfigError, match="备份失败"):
            cw.save_endpoint({"baseUrl": "http://x/v1", "apiKey": "sk-x"})
        # 中止时不得写入配置
        settings = SettingsRepository().get_json("app_settings")
        assert settings is None or not settings.get("endpoints")


class TestProbeConnectivity:
    class _Sock:
        def close(self):
            pass

    class _Resp:
        status = 200

        def __init__(self, body: bytes):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def _patch_network(self, monkeypatch, body: bytes, calls: list):
        import socket
        import urllib.request

        monkeypatch.setattr(socket, "create_connection", lambda *a, **k: self._Sock())
        monkeypatch.setattr(
            urllib.request,
            "urlopen",
            lambda req, timeout: (calls.append(req.full_url) or self._Resp(body)),
        )

    def test_base_url_with_v1_does_not_duplicate_prefix(self, monkeypatch):
        calls = []
        self._patch_network(monkeypatch, b'{"data":[{"id":"m1"}]}', calls)
        result = cw.probe_connectivity(
            {"baseUrl": "http://10.0.0.5:8000/v1", "protocol": "openai-compatible"}
        )
        assert result["ok"] is True
        assert result["models"] == ["m1"]
        assert calls == ["http://10.0.0.5:8000/v1/models"]

    def test_base_url_without_v1_appends_v1_models(self, monkeypatch):
        calls = []
        self._patch_network(monkeypatch, b'{"data":[]}', calls)
        cw.probe_connectivity({"baseUrl": "http://10.0.0.5:8000"})
        assert calls == ["http://10.0.0.5:8000/v1/models"]

    def test_ollama_uses_api_tags(self, monkeypatch):
        calls = []
        self._patch_network(monkeypatch, b'{"models":[{"name":"qwen"}]}', calls)
        result = cw.probe_connectivity(
            {"baseUrl": "http://127.0.0.1:11434", "protocol": "ollama"}
        )
        assert calls == ["http://127.0.0.1:11434/api/tags"]
        assert result["models"] == ["qwen"]

    def test_gemini_uses_v1beta_models(self, monkeypatch):
        calls = []
        self._patch_network(monkeypatch, b'{"models":[{"name":"models/gemini"}]}', calls)
        result = cw.probe_connectivity(
            {"baseUrl": "https://generativelanguage.googleapis.com", "protocol": "gemini"}
        )
        assert calls == ["https://generativelanguage.googleapis.com/v1beta/models"]
        assert result["models"] == ["models/gemini"]


class TestBundleIO:
    def test_export_then_import_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SAGE_SECRET_SCHEME", "test")
        cw.save_endpoint(
            {
                "baseUrl": "http://10.0.0.5:8000/v1",
                "apiKey": "sk-roundtrip",
                "modelId": "m1",
            },
            backup=False,
        )
        out = tmp_path / "bundle.json"
        cw.export_bundle(out, include_secrets=True)
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["schema"] == 1
        assert data["endpoints"][0]["apiKey"] == "sk-roundtrip"

        # 导入到空库
        from backend.data.database import get_database

        repo = SettingsRepository()
        repo.set_json("app_settings", {"version": 1, "endpoints": [], "modelSelections": {}})
        summary = cw.import_bundle(out, include_secrets=True)
        assert summary["endpoints_imported"] == 1
        settings = repo.get_json("app_settings")
        assert settings["endpoints"][0]["apiKey"] == "sk-roundtrip"
        assert get_database().get_connection()  # DB 仍可用

    def test_import_multiple_endpoints_keeps_all(self, tmp_path):
        bundle = {
            "schema": 1,
            "endpoints": [
                {"id": "e1", "name": "a", "baseUrl": "http://a/v1"},
                {"id": "e2", "name": "b", "baseUrl": "http://b/v1"},
            ],
            "modelSelections": {},
        }
        path = tmp_path / "bundle.json"
        path.write_text(json.dumps(bundle), encoding="utf-8")
        repo = SettingsRepository()
        repo.set_json(
            "app_settings", {"version": 1, "endpoints": [], "modelSelections": {}}
        )
        summary = cw.import_bundle(path, include_secrets=False, backup=False)
        assert summary["endpoints_imported"] == 2
        settings = repo.get_json("app_settings")
        assert [ep["id"] for ep in settings["endpoints"]] == ["e1", "e2"]

    def test_import_without_secrets_ignores_masked_key_and_hasapikey(self, tmp_path):
        bundle = {
            "schema": 1,
            "endpoints": [
                {
                    "id": "e1",
                    "name": "a",
                    "baseUrl": "http://a/v1",
                    "apiKey": "***",
                    "hasApiKey": True,
                }
            ],
            "modelSelections": {},
        }
        path = tmp_path / "bundle.json"
        path.write_text(json.dumps(bundle), encoding="utf-8")
        repo = SettingsRepository()
        repo.set_json(
            "app_settings",
            {
                "version": 1,
                "endpoints": [
                    {"id": "e1", "name": "a", "baseUrl": "http://a/v1", "apiKey": "sk-existing"}
                ],
                "modelSelections": {},
            },
        )
        cw.import_bundle(path, include_secrets=False, backup=False)
        settings = repo.get_json("app_settings")
        ep = settings["endpoints"][0]
        assert ep["apiKey"] == "sk-existing"
        assert "hasApiKey" not in ep

    def test_masked_bundle_cannot_import_key_even_if_requested(self, tmp_path):
        bundle = {
            "schema": 1,
            "includeSecrets": False,
            "endpoints": [
                {
                    "id": "e1",
                    "name": "a",
                    "baseUrl": "http://a/v1",
                    "apiKey": "sk-***wxyz",
                    "hasApiKey": True,
                    "apiKeyUpdatedAt": 9999999999999,
                }
            ],
            "modelSelections": {},
        }
        path = tmp_path / "bundle.json"
        path.write_text(json.dumps(bundle), encoding="utf-8")
        repo = SettingsRepository()
        repo.set_json(
            "app_settings",
            {
                "version": 1,
                "endpoints": [
                    {
                        "id": "e1",
                        "name": "a",
                        "baseUrl": "http://a/v1",
                        "apiKey": "sk-real",
                        "apiKeyUpdatedAt": 1000,
                    }
                ],
                "modelSelections": {},
            },
        )
        cw.import_bundle(path, include_secrets=True, backup=False)
        ep = repo.get_json("app_settings")["endpoints"][0]
        assert ep["apiKey"] == "sk-real"
        assert ep["apiKeyUpdatedAt"] == 1000
