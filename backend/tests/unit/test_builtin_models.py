"""Builtin model catalog structure tests.

Verifies that backend/builtin.json:
- Contains at least 50 models with tier information
- Every model has provider, model_id, and tier fields
- Tier values are valid (fast/balanced/powerful)
- Tier distribution has at least 10 models per tier
"""

import json
from pathlib import Path

import pytest

_BUILTIN_JSON_PATH = Path(__file__).parent.parent.parent / "builtin.json"
_VALID_TIERS = {"fast", "balanced", "powerful"}


@pytest.fixture
def builtin_models():
    """Load models from builtin.json."""
    with open(_BUILTIN_JSON_PATH) as f:
        data = json.load(f)
    assert isinstance(data, dict), "builtin.json root must be a dict"
    models = data.get("models")
    assert isinstance(models, list), "builtin.json 'models' must be a list"
    return models


class TestBuiltinJsonStructure:
    """Verify builtin.json has required fields and structure."""

    def test_builtin_json_has_at_least_50_models(self, builtin_models):
        assert len(builtin_models) >= 50, (
            f"builtin.json should have at least 50 models, got {len(builtin_models)}"
        )

    def test_every_model_has_provider(self, builtin_models):
        for model in builtin_models:
            assert "provider" in model, (
                f"Model entry missing 'provider': {model}"
            )
            assert isinstance(model["provider"], str) and model["provider"].strip(), (
                f"Model provider must be a non-blank string: {model}"
            )

    def test_every_model_has_model_id(self, builtin_models):
        for model in builtin_models:
            assert "model_id" in model, (
                f"Model entry missing 'model_id': {model}"
            )
            assert isinstance(model["model_id"], str) and model["model_id"].strip(), (
                f"Model model_id must be a non-blank string: {model}"
            )

    def test_builtin_json_has_tier_field(self, builtin_models):
        for model in builtin_models:
            assert "tier" in model, (
                f"Model {model.get('model_id', '?')} missing tier field"
            )

    def test_tier_values_are_valid(self, builtin_models):
        for model in builtin_models:
            tier = model.get("tier")
            assert tier in _VALID_TIERS, (
                f"Model {model.get('model_id', '?')} has invalid tier: {tier!r}. "
                f"Must be one of {_VALID_TIERS}"
            )


class TestBuiltinJsonTierDistribution:
    """Ensure reasonable tier distribution for smart routing."""

    def test_tier_distribution_minimum(self, builtin_models):
        tier_counts = {"fast": 0, "balanced": 0, "powerful": 0}
        for model in builtin_models:
            tier = model.get("tier")
            if tier in tier_counts:
                tier_counts[tier] += 1

        for tier_name, count in tier_counts.items():
            assert count >= 10, (
                f"Tier '{tier_name}' has only {count} models; need at least 10"
            )

    def test_tier_distribution_report(self, builtin_models):
        """Informational: verify tier counts sum to total."""
        tier_counts = {"fast": 0, "balanced": 0, "powerful": 0}
        for model in builtin_models:
            tier = model.get("tier")
            if tier in tier_counts:
                tier_counts[tier] += 1

        total = sum(tier_counts.values())
        assert total == len(builtin_models), (
            f"Tier counts ({total}) don't match total models ({len(builtin_models)})"
        )


class TestBuiltinJsonUniqueness:
    """Ensure no duplicate provider/model_id combinations."""

    def test_no_duplicate_models(self, builtin_models):
        seen = set()
        duplicates = []
        for model in builtin_models:
            key = (model.get("provider"), model.get("model_id"))
            if key in seen:
                duplicates.append(key)
            seen.add(key)
        assert not duplicates, f"Duplicate models found: {duplicates}"
