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
        async def complete(self, prompt):
            raise RuntimeError("bad request")

    with pytest.raises(RuntimeError):
        asyncio.run(llm_factory.complete_utility("x", llm_client=_Boom()))


def test_complete_utility_without_client_raises(monkeypatch):
    monkeypatch.setattr(
        llm_factory, "build_utility_llm_client", lambda task_type="classification": None
    )
    with pytest.raises(RuntimeError):
        asyncio.run(llm_factory.complete_utility("x"))
