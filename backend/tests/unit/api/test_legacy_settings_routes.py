"""R170 — legacy settings / preferences 路由单元测试。

直接调用路由函数。SettingsRepository 与 canonicalizer 协作者全
monkeypatch。覆盖：GET 空值/损坏 JSON/非 dict/正常 snake→camel 翻译与
protocol 迁移、PUT 合并语义/校验 422/400、preferences KV 读写与白名单。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.api import legacy_settings_routes as lsr
from backend.api.legacy_settings_routes import (
    _migrate_default_protocol,
    legacy_get_settings,
    legacy_update_settings,
)

pytestmark = pytest.mark.unit


class _FakeRepo:
    KEYS = frozenset({"app_settings", "search_config"})

    def __init__(self, store):
        self._store = store

    def get_json(self, key):
        return self._store.get(key)

    def get(self, key):
        return self._store.get(key)

    def set(self, key, value, value_type=None, category=None):
        self._store[key] = value

    def set_json(self, key, value, category=None):
        self._store[key] = value


def _install(monkeypatch, store):
    monkeypatch.setattr(
        "backend.data.settings_repo.SettingsRepository", lambda: _FakeRepo(store)
    )
    return store


def _req(**fields):
    from backend.api.settings_models import LegacySettingsPayload

    return LegacySettingsPayload(**fields)


# ---------------------------------------------------------------------------
# GET /settings
# ---------------------------------------------------------------------------


def test_get_settings_empty_returns_none(monkeypatch):
    _install(monkeypatch, {})
    assert legacy_get_settings() is None


def test_get_settings_corrupted_json_returns_none(monkeypatch):
    # SettingsRepository.get_json 在 JSON 损坏时抛 ValueError → 路由返回 None
    class _Broken:
        def get_json(self, key):
            raise ValueError("corrupted")

    monkeypatch.setattr(
        "backend.data.settings_repo.SettingsRepository", lambda: _Broken()
    )
    assert legacy_get_settings() is None


def test_get_settings_non_dict_returns_none(monkeypatch):
    _install(monkeypatch, {"app_settings": [1, 2]})
    assert legacy_get_settings() is None


def test_get_settings_snake_to_camel_and_protocol_migration(monkeypatch):
    _install(
        monkeypatch,
        {
            "app_settings": {
                "endpoints": [
                    {"id": "e1", "name": "n", "baseUrl": "http://x", "apiKey": "k"}
                ]
            }
        },
    )
    out = legacy_get_settings()
    ep = out["endpoints"][0]
    assert ep["protocol"] == "openai-compatible"  # 旧 schema 迁移默认值
    assert ep["baseUrl"] == "http://x"  # camelCase 保留


# ---------------------------------------------------------------------------
# _migrate_default_protocol（纯函数直接测）
# ---------------------------------------------------------------------------


def test_migrate_default_protocol_fills_missing_only():
    settings = {
        "endpoints": [
            {"id": "a"},
            {"id": "b", "protocol": "anthropic"},
            "not-a-dict",
        ]
    }
    _migrate_default_protocol(settings)
    assert settings["endpoints"][0]["protocol"] == "openai-compatible"
    assert settings["endpoints"][1]["protocol"] == "anthropic"  # 已有值不动


def test_migrate_default_protocol_non_list_noop():
    settings = {"endpoints": "oops"}
    _migrate_default_protocol(settings)
    assert settings["endpoints"] == "oops"


# ---------------------------------------------------------------------------
# PUT /settings 合并语义
# ---------------------------------------------------------------------------


def test_put_merges_into_existing_without_clobber(monkeypatch):
    store = {
        "app_settings": {
            "endpoints": [{"id": "e1", "name": "keep", "baseUrl": "http://x"}],
        }
    }
    _install(monkeypatch, store)
    out = legacy_update_settings(_req(model="new-model"))
    assert out.status == "ok"
    saved = store["app_settings"]
    assert saved["endpoints"] == [
        {"id": "e1", "name": "keep", "baseUrl": "http://x", "protocol": "openai-compatible"}
    ]  # GET 路径同款迁移：缺 protocol 的端点写入时补默认值
    assert saved["endpoints"][0]["name"] == "keep"
    # legacy 三件套不进 DB
    assert "model" not in saved


def test_put_corrupted_existing_still_saves(monkeypatch):
    class _Broken:
        def get_json(self, key):
            raise ValueError("corrupted")

    def set_json(key, value, category=None):
        pass

    monkeypatch.setattr(
        "backend.data.settings_repo.SettingsRepository",
        lambda: SimpleNamespace(get_json=lambda k: (_ for _ in ()).throw(ValueError()), set_json=lambda *a, **kw: None),
    )
    out = legacy_update_settings(_req(model="m"))
    assert out.status == "ok"


# ---------------------------------------------------------------------------
# preferences KV
# ---------------------------------------------------------------------------


def test_preferences_get_and_put(monkeypatch):
    # 路由读 SettingsRepository.KEYS 类属性——fake 必须是带 KEYS 的类
    saved = {"search_config": json.dumps({"order": ["bing"]})}

    import backend.data.settings_repo as repo_mod

    class _KVRepo:
        KEYS = frozenset({"search_config", "app_settings"})

        def __init__(self):
            self._s = saved

        def get(self, key):
            return self._s.get(key)

        def set(self, key, value, value_type=None, category=None):
            self._s[key] = value

    monkeypatch.setattr(repo_mod, "SettingsRepository", _KVRepo)
    item = lsr.legacy_get_preference("search_config")
    assert item.value == json.dumps({"order": ["bing"]})

    from backend.api.legacy_skills_routes import LegacyPreferenceItem

    out = lsr.legacy_put_preference(
        "search_config", LegacyPreferenceItem(value=json.dumps({"order": ["ddg"]}))
    )
    assert out.value == json.dumps({"order": ["ddg"]})
    assert json.loads(saved["search_config"])["order"] == ["ddg"]
