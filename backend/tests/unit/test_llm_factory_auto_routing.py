"""Auto-routing overlay: settings key -> model override, fail-safe by design."""
from __future__ import annotations

from backend.orchestration.llm_factory import (
    apply_auto_routing_overlay,
    load_llm_config_for_chat,
    load_routing_config,
)

CFG = {
    "provider": "custom",
    "api_key": "sk-test",
    "base_url": "https://example.invalid/v1",
    "model": "global-model",
    "temperature": 0.3,
    "endpoint_id": "ep-1",
}


def _settings(monkeypatch, payload):
    """Make SettingsRepository().get_json('app_settings') return payload."""
    class FakeRepo:
        def get_json(self, key):
            assert key == "app_settings"
            return payload

    monkeypatch.setattr(
        "backend.data.settings_repo.SettingsRepository", lambda: FakeRepo()
    )


class TestLoadRoutingConfig:
    def test_absent_key_is_manual_4096(self, monkeypatch):
        _settings(monkeypatch, {})
        assert load_routing_config() == ("manual", 4096)

    def test_auto_mode_reads_max_context(self, monkeypatch):
        _settings(monkeypatch, {"routing": {"mode": "auto"}, "maxContext": 32000})
        assert load_routing_config() == ("auto", 32000)

    def test_unknown_mode_is_manual(self, monkeypatch):
        _settings(monkeypatch, {"routing": {"mode": "turbo"}})
        assert load_routing_config()[0] == "manual"

    def test_repository_error_is_manual(self, monkeypatch):
        class Boom:
            def get_json(self, key):
                raise RuntimeError("db down")

        monkeypatch.setattr("backend.data.settings_repo.SettingsRepository", lambda: Boom())
        assert load_routing_config() == ("manual", 4096)


class TestApplyAutoRoutingOverlay:
    def test_manual_returns_config_untouched(self, monkeypatch):
        _settings(monkeypatch, {})
        called = []
        monkeypatch.setattr(
            "backend.orchestration.llm_factory.resolve_routed_chat_model",
            lambda **kw: called.append(kw) or "routed",
        )
        assert apply_auto_routing_overlay(CFG, task_type="chat") is CFG
        assert called == []

    def test_auto_overrides_model_and_scopes_to_endpoint(self, monkeypatch):
        _settings(monkeypatch, {"routing": {"mode": "auto"}, "maxContext": 16000})
        seen = {}

        def fake_route(**kwargs):
            seen.update(kwargs)
            return "routed-model"

        monkeypatch.setattr(
            "backend.orchestration.llm_factory.resolve_routed_chat_model", fake_route
        )
        out = apply_auto_routing_overlay(CFG, task_type="code_generation")
        assert out is not CFG
        assert out["model"] == "routed-model"
        assert out["api_key"] == "sk-test"
        assert out["endpoint_id"] == "ep-1"
        assert seen == {
            "task_type": "code_generation",
            "context_length": 16000,
            "endpoint_id": "ep-1",
        }

    def test_auto_defaults_task_type_to_chat(self, monkeypatch):
        _settings(monkeypatch, {"routing": {"mode": "auto"}})
        seen = {}
        monkeypatch.setattr(
            "backend.orchestration.llm_factory.resolve_routed_chat_model",
            lambda **kw: seen.update(kw) or "routed-model",
        )
        apply_auto_routing_overlay(CFG)
        assert seen["task_type"] == "chat"

    def test_no_route_result_keeps_config(self, monkeypatch):
        _settings(monkeypatch, {"routing": {"mode": "auto"}})
        monkeypatch.setattr(
            "backend.orchestration.llm_factory.resolve_routed_chat_model",
            lambda **kw: None,
        )
        assert apply_auto_routing_overlay(CFG) is CFG

    def test_explicit_session_override_wins(self, monkeypatch):
        """R23: a user pick beats automation."""
        _settings(monkeypatch, {"routing": {"mode": "auto"}})
        monkeypatch.setattr(
            "backend.orchestration.llm_factory.resolve_chat_model",
            lambda session_id, profile_model=None: "user-picked",
        )
        called = []
        monkeypatch.setattr(
            "backend.orchestration.llm_factory.resolve_routed_chat_model",
            lambda **kw: called.append(kw) or "routed-model",
        )
        assert apply_auto_routing_overlay(CFG, session_id="s1") is CFG
        assert called == []

    def test_none_config_is_passthrough(self, monkeypatch):
        _settings(monkeypatch, {"routing": {"mode": "auto"}})
        assert apply_auto_routing_overlay(None) is None


class TestLoadLlmConfigForChatAppliesOverlay:
    def test_task_type_is_forwarded_to_overlay(self, monkeypatch):
        monkeypatch.setattr(
            "backend.orchestration.llm_factory.load_llm_config_from_settings",
            lambda: dict(CFG),
        )
        seen = {}

        def fake_overlay(cfg, task_type=None, session_id=None, profile_model=None):
            seen["task_type"] = task_type
            return {**cfg, "model": "routed-model"}

        monkeypatch.setattr(
            "backend.orchestration.llm_factory.apply_auto_routing_overlay", fake_overlay
        )
        cfg = load_llm_config_for_chat(session_id="s1", task_type="analysis")
        assert cfg["model"] == "routed-model"
        assert seen["task_type"] == "analysis"
