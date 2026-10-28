"""Tests for tier field on CandidateModel and EffectiveModel."""
import pytest

from backend.model_catalog.schemas import (
    CandidateModel,
    ContextLimits,
    EffectiveModel,
    ModelKey,
    Price,
)


def test_candidate_model_accepts_tier():
    model = CandidateModel(
        model_key=ModelKey(provider="openai", model_id="gpt-4o"),
        tier="balanced",
        native=128000,
        source="seed",
        pricing_scope="global",
    )
    assert model.tier == "balanced"


def test_candidate_model_tier_optional():
    model = CandidateModel(
        model_key=ModelKey(provider="openai", model_id="gpt-4o"),
        native=128000,
        source="seed",
        pricing_scope="global",
    )
    assert model.tier is None


def test_effective_model_requires_tier():
    model = EffectiveModel(
        tier="balanced",
        limits=ContextLimits(native=128000, service=128000),
        price=Price(),
        provenance={"source": "seed"},
    )
    assert model.tier == "balanced"


def test_effective_model_without_tier_raises():
    with pytest.raises(ValueError):
        EffectiveModel(
            limits=ContextLimits(native=128000, service=128000),
            price=Price(),
            provenance={"source": "seed"},
        )
