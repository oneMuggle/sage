"""网关配置双源测试（Round 19: settings 持久化 + env 覆盖）"""

from __future__ import annotations

import tempfile
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.gateway_routes import router as gateway_router
from backend.gateway.telegram import TelegramConfig

pytestmark = pytest.mark.unit


@pytest.fixture()
def tmp_db(monkeypatch):
    from backend.data.database import Database

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = Database(f.name)
        db.init_db()
    import backend.data.database as db_mod

    monkeypatch.setattr(db_mod, "_db", db)
    yield db
    db.close()


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(gateway_router)
    return TestClient(app, headers={"Authorization": "Bearer test-local-auth-token"})


def _seed_settings(monkeypatch, telegram_node):
    """把 app_settings.telegram 固定为给定节点（绕过真库）"""
    import backend.data.settings_repo as sr_mod

    repo = SimpleNamespace()
    repo.get_json = lambda key: (
        {"telegram": telegram_node} if key == "app_settings" else {}
    )

    def set_json(self, key, value, category="general"):
        repo.saved = (key, value)

    repo.set_json = set_json
    monkeypatch.setattr(sr_mod.SettingsRepository, "get_json", lambda self, key: repo.get_json(key))
    monkeypatch.setattr(sr_mod.SettingsRepository, "set_json", set_json)
    return repo


class TestConfigLoad:
    def test_none_without_any_config(self, monkeypatch, tmp_db):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        _seed_settings(monkeypatch, None)
        assert TelegramConfig.load() is None

    def test_settings_source(self, monkeypatch, tmp_db):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        _seed_settings(
            monkeypatch,
            {"bot_token": "set-tok", "allowed_chat_ids": ["1", "2"], "enabled": True},
        )
        cfg = TelegramConfig.load()
        assert cfg is not None
        assert cfg.bot_token == "set-tok"
        assert cfg.allowed_chat_ids == ["1", "2"]

    def test_env_overrides_settings(self, monkeypatch, tmp_db):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-tok")
        _seed_settings(
            monkeypatch, {"bot_token": "set-tok", "allowed_chat_ids": ["1"]}
        )
        cfg = TelegramConfig.load()
        assert cfg is not None
        assert cfg.bot_token == "env-tok"

    def test_settings_disabled_wins_over_env(self, monkeypatch, tmp_db):
        """settings.enabled=False → 显式关闭（即使 env 有 token）"""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-tok")
        _seed_settings(
            monkeypatch, {"bot_token": "set-tok", "enabled": False}
        )
        assert TelegramConfig.load() is None

    def test_settings_string_chat_ids(self, monkeypatch, tmp_db):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        _seed_settings(
            monkeypatch,
            {"bot_token": "set-tok", "allowed_chat_ids": "1, 2,3"},
        )
        cfg = TelegramConfig.load()
        assert cfg.allowed_chat_ids == ["1", "2", "3"]


class TestConfigEndpoints:
    def test_get_config_masked_from_settings(self, monkeypatch, client, tmp_db):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        _seed_settings(
            monkeypatch,
            {"bot_token": "1234567890:ABCDEF", "allowed_chat_ids": ["42"]},
        )
        resp = client.get("/gateway/telegram/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "settings"
        assert data["bot_token_masked"].startswith("****")
        assert "ABCDEF" not in data["bot_token_masked"]

    def test_put_config_saves_settings(self, monkeypatch, client, tmp_db):
        repo = _seed_settings(monkeypatch, None)
        resp = client.put(
            "/gateway/telegram/config",
            json={"bot_token": "new-tok", "allowed_chat_ids": ["7"], "enabled": True},
        )
        assert resp.status_code == 200
        assert resp.json()["saved"] is True
        key, value = repo.saved
        assert key == "app_settings"
        assert value["telegram"]["bot_token"] == "new-tok"

    def test_put_config_disabled(self, monkeypatch, client, tmp_db):
        repo = _seed_settings(monkeypatch, None)
        resp = client.put(
            "/gateway/telegram/config",
            json={"bot_token": "new-tok", "allowed_chat_ids": [], "enabled": False},
        )
        assert resp.status_code == 200
        key, value = repo.saved
        assert value["telegram"]["enabled"] is False
