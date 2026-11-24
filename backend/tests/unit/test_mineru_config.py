from __future__ import annotations

import json

import pytest

from backend.domain.document_parse import MineruSettings
from backend.services.document_parse import config as config_mod
from backend.services.secret_box import (
    is_wrapped,
    unwrap_mineru_service_json,
    wrap_mineru_service_json,
)

pytestmark = [pytest.mark.unit]

_ENV_KEYS = (
    "SAGE_MINERU_BASE_URL",
    "SAGE_MINERU_API_KEY",
    "SAGE_MINERU_TIER",
    "SAGE_MINERU_TIMEOUT_SECONDS",
)


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch):
    # 强制 SecretBox 测试 scheme（CI 与本地均确定性加密），并清空外部 MinerU env。
    monkeypatch.setenv("SAGE_SECRET_SCHEME", "test")
    for name in _ENV_KEYS:
        monkeypatch.delenv(name, raising=False)


def test_secret_box_wraps_api_key_only() -> None:
    raw = json.dumps({"enabled": True, "baseUrl": "http://m:8000", "apiKey": "sk-synthetic"})
    wrapped = json.loads(wrap_mineru_service_json(raw))
    assert wrapped["enabled"] is True
    assert wrapped["baseUrl"] == "http://m:8000"
    assert is_wrapped(wrapped["apiKey"]) is True
    assert unwrap_mineru_service_json(json.dumps(wrapped)) == raw


def test_secret_box_is_idempotent() -> None:
    raw = json.dumps({"apiKey": "sk-synthetic"})
    once = wrap_mineru_service_json(raw)
    assert wrap_mineru_service_json(once) == once


def test_load_settings_prefers_env(monkeypatch) -> None:
    monkeypatch.setattr(config_mod, "_read_preference", lambda: {"apiKey": "pref"})
    monkeypatch.setenv("SAGE_MINERU_BASE_URL", "http://env:8000")
    monkeypatch.setenv("SAGE_MINERU_API_KEY", "sk-synthetic-env")
    monkeypatch.setenv("SAGE_MINERU_TIER", "advanced")
    settings = config_mod.load_mineru_settings()
    assert isinstance(settings, MineruSettings)
    assert settings.base_url == "http://env:8000"
    assert settings.api_key == "sk-synthetic-env"
    assert settings.default_tier == "advanced"


def test_load_settings_falls_back_to_defaults(monkeypatch) -> None:
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(config_mod, "_read_preference", boom)
    settings = config_mod.load_mineru_settings()
    assert settings.enabled is False
    assert settings.base_url == ""
    assert settings.default_tier == "standard"
    assert settings.timeout_seconds == 300.0
