"""G5 会话级模型覆盖单元测试（docs/plans §2.1）。

覆盖：resolve_chat_model 三级优先级、load_session_model_overrides 的
fail-safe 与畸形条目过滤、load_llm_config_for_chat 的端点恒定 + 模型覆盖。
"""

from __future__ import annotations

import json

import pytest

from backend.orchestration import llm_factory
from backend.orchestration.llm_factory import (
    SESSION_MODEL_OVERRIDES_KEY,
    load_session_model_overrides,
    resolve_chat_model,
)

pytestmark = [pytest.mark.unit]


def _set_overrides(raw, monkeypatch):
    """注入 overrides：dict 直接落 KV；None 模拟 KV 空。"""
    class _Repo:
        def get_json(self, key):
            assert key == SESSION_MODEL_OVERRIDES_KEY
            return raw

    monkeypatch.setattr(
        "backend.data.settings_repo.SettingsRepository", lambda: _Repo()
    )


def _stub_settings_endpoint(monkeypatch, model="global-model"):
    """让 load_llm_config_from_settings 返回固定端点配置（隔离全局设置）。"""

    def _fake():
        return {
            "provider": "custom",
            "api_key": "sk-test",
            "base_url": "https://ep.example/v1",
            "model": model,
            "temperature": 0.3,
        }

    monkeypatch.setattr(llm_factory, "load_llm_config_from_settings", _fake)


# ---------------------------------------------------------------------------
# resolve_chat_model 优先级
# ---------------------------------------------------------------------------


def test_session_override_beats_profile_and_global(monkeypatch):
    _set_overrides({"sess-1": "session-model"}, monkeypatch)
    assert (
        resolve_chat_model("sess-1", profile_model="profile-model")
        == "session-model"
    )


def test_profile_model_used_when_no_session_override(monkeypatch):
    _set_overrides({}, monkeypatch)
    assert resolve_chat_model("sess-1", profile_model="qwen-max") == "qwen-max"


def test_none_when_only_global(monkeypatch):
    _set_overrides({}, monkeypatch)
    assert resolve_chat_model("sess-1", profile_model="gpt-4") is None
    assert resolve_chat_model(None, profile_model="gpt-4") is None


def test_placeholder_profile_models_ignored(monkeypatch):
    """种子默认 model（gpt-4 等）视为未设置，不参与路由。"""
    _set_overrides({}, monkeypatch)
    for placeholder in ("gpt-4", "gpt-3.5-turbo", "gpt-4-turbo-preview"):
        assert resolve_chat_model("sess-1", profile_model=placeholder) is None


# ---------------------------------------------------------------------------
# load_session_model_overrides fail-safe
# ---------------------------------------------------------------------------


def test_overrides_missing_or_corrupt_returns_empty(monkeypatch):
    _set_overrides(None, monkeypatch)
    assert load_session_model_overrides() == {}
    _set_overrides(["not", "a", "dict"], monkeypatch)
    assert load_session_model_overrides() == {}


def test_overrides_filters_malformed_entries(monkeypatch):
    _set_overrides(
        {"ok": "model-a", "": "model-b", 42: "model-c", "bad": 123, "blank": "  "},
        monkeypatch,
    )
    assert load_session_model_overrides() == {"ok": "model-a"}


# ---------------------------------------------------------------------------
# load_llm_config_for_chat
# ---------------------------------------------------------------------------


def test_chat_config_keeps_endpoint_overrides_model(monkeypatch):
    _stub_settings_endpoint(monkeypatch, model="global-model")
    _set_overrides({"sess-1": "qwen-max"}, monkeypatch)
    cfg = llm_factory.load_llm_config_for_chat(session_id="sess-1")
    assert cfg is not None
    assert cfg["model"] == "qwen-max"
    assert cfg["base_url"] == "https://ep.example/v1"  # 端点恒取全局


def test_chat_config_no_override_uses_global(monkeypatch):
    _stub_settings_endpoint(monkeypatch, model="global-model")
    _set_overrides({}, monkeypatch)
    cfg = llm_factory.load_llm_config_for_chat(session_id="sess-1")
    assert cfg["model"] == "global-model"


def test_chat_config_without_endpoint_returns_none(monkeypatch):
    monkeypatch.setattr(
        llm_factory, "load_llm_config_from_settings", lambda: None
    )
    _set_overrides({"sess-1": "x"}, monkeypatch)
    assert llm_factory.load_llm_config_for_chat(session_id="sess-1") is None


# ---------------------------------------------------------------------------
# REST 端点（legacy_routes）
# ---------------------------------------------------------------------------


def test_session_model_rest_roundtrip(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import backend.api.legacy_routes as legacy

    app = FastAPI()
    app.include_router(legacy.router)
    client = TestClient(app)

    # 未设置 → null
    assert client.get("/sessions/s1/model").json()["model"] is None

    # 设置
    response = client.put(
        "/sessions/s1/model", json={"model": " deepseek-chat "}
    )
    assert response.status_code == 200
    assert response.json()["model"] == "deepseek-chat"  # strip 落库
    # 真实 KV 读写（conftest tmp DB）
    stored = json.loads(
        __import__(
            "backend.data.settings_repo", fromlist=["SettingsRepository"]
        ).SettingsRepository().get(SESSION_MODEL_OVERRIDES_KEY)
    )
    assert stored == {"s1": "deepseek-chat"}

    # 清除
    assert (
        client.put("/sessions/s1/model", json={"model": ""}).json()["model"]
        is None
    )
    assert load_session_model_overrides() == {}
