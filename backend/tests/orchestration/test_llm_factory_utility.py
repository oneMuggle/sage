import asyncio

import pytest

from backend.orchestration import llm_factory


def test_apply_utility_overrides_does_not_mutate_input():
    cfg = {"model": "m", "reasoning_effort": "high"}
    out = llm_factory._apply_utility_overrides(cfg)
    assert cfg == {"model": "m", "reasoning_effort": "high"}
    assert out["reasoning_effort"] == "low"
    assert out["thinking_budget"] == 0
    assert out["model"] == "m"


def test_complete_utility_uses_injected_client():
    calls = []

    class _Client:
        async def complete(self, prompt):
            calls.append(prompt)
            return "multi"

    result = asyncio.run(llm_factory.complete_utility("classify", llm_client=_Client()))
    assert result == "multi"
    assert calls == ["classify"]


def test_complete_utility_does_not_retry_injected_client():
    class _Boom:
        def __init__(self):
            self.calls = 0

        async def complete(self, prompt):
            self.calls += 1
            raise RuntimeError("bad request")

    boom = _Boom()
    with pytest.raises(RuntimeError):
        asyncio.run(llm_factory.complete_utility("x", llm_client=boom))
    assert boom.calls == 1


def test_complete_utility_falls_back_when_utility_client_fails(monkeypatch):
    class _UtilityBoom:
        async def complete(self, prompt):
            raise RuntimeError("unsupported reasoning_effort")

    calls = []

    class _Plain:
        async def complete(self, prompt):
            calls.append(prompt)
            return "ok"

    monkeypatch.setattr(
        llm_factory,
        "build_utility_llm_client",
        lambda task_type="classification": _UtilityBoom(),
    )
    monkeypatch.setattr(
        llm_factory, "build_llm_client_from_settings", lambda: _Plain()
    )

    result = asyncio.run(llm_factory.complete_utility("x"))
    assert result == "ok"
    assert calls == ["x"]


def test_complete_utility_reraises_original_when_fallback_unavailable(monkeypatch):
    class _UtilityBoom:
        async def complete(self, prompt):
            raise RuntimeError("orig")

    monkeypatch.setattr(
        llm_factory,
        "build_utility_llm_client",
        lambda task_type="classification": _UtilityBoom(),
    )
    monkeypatch.setattr(llm_factory, "build_llm_client_from_settings", lambda: None)

    with pytest.raises(RuntimeError, match="orig"):
        asyncio.run(llm_factory.complete_utility("x"))


def test_complete_utility_without_client_raises(monkeypatch):
    monkeypatch.setattr(
        llm_factory, "build_utility_llm_client", lambda task_type="classification": None
    )
    with pytest.raises(RuntimeError):
        asyncio.run(llm_factory.complete_utility("x"))


def test_build_utility_llm_client_without_task_type_skips_routing(monkeypatch):
    overlay_calls = []

    def _spy_overlay(cfg, task_type=None, **_kw):
        overlay_calls.append(task_type)
        return cfg

    monkeypatch.setattr(
        llm_factory, "load_llm_config_from_settings", lambda: {"model": "m"}
    )
    monkeypatch.setattr(llm_factory, "apply_auto_routing_overlay", _spy_overlay)
    import backend.core.legacy.llm_client as legacy

    monkeypatch.setattr(legacy, "LLMConfig", dict)
    monkeypatch.setattr(legacy, "LLMClient", lambda cfg: cfg)

    client = llm_factory.build_utility_llm_client()
    assert client is not None
    assert overlay_calls == []


def test_build_utility_llm_client_with_task_type_routes(monkeypatch):
    overlay_calls = []

    def _spy_overlay(cfg, task_type=None, **_kw):
        overlay_calls.append(task_type)
        return cfg

    monkeypatch.setattr(
        llm_factory, "load_llm_config_from_settings", lambda: {"model": "m"}
    )
    monkeypatch.setattr(llm_factory, "apply_auto_routing_overlay", _spy_overlay)
    import backend.core.legacy.llm_client as legacy

    monkeypatch.setattr(legacy, "LLMConfig", dict)
    monkeypatch.setattr(legacy, "LLMClient", lambda cfg: cfg)

    client = llm_factory.build_utility_llm_client(task_type="classification")
    assert client is not None
    assert overlay_calls == ["classification"]
