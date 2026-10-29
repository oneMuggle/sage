"""Unit tests for the smart model routing engine."""
from typing import Dict, List, Optional
from unittest.mock import Mock

import pytest

from backend.model_catalog.resolver import resolve_layers
from backend.model_catalog.schemas import (
    CandidateModel,
    ContextLimits,
    EffectiveModel,
    EndpointKey,
    LayerValues,
    ModelKey,
    Price,
)
from backend.routing.routing_engine import (
    TASK_TYPE_TO_TIER,
    RoutingEngine,
    RoutingPreference,
    RoutingResult,
)


def _make_effective(
    tier: str,
    native_context: int,
    capabilities: Optional[Dict[str, bool]] = None,
    model_id: str = "m",
) -> EffectiveModel:
    """Build an EffectiveModel with the minimal required fields."""
    return EffectiveModel(
        tier=tier,
        model_key=ModelKey(provider="test", model_id=model_id),
        capabilities=capabilities,
        limits=ContextLimits(native=native_context),
        price=Price(),
        provenance={"source": "test"},
    )


@pytest.fixture()
def available_models() -> List[EffectiveModel]:
    """Three models across the three tiers with varying context windows."""
    return [
        _make_effective(tier="fast", native_context=128_000, model_id="fast-model"),
        _make_effective(tier="balanced", native_context=128_000, model_id="balanced-model"),
        _make_effective(tier="powerful", native_context=200_000, model_id="powerful-model"),
    ]


@pytest.fixture()
def mock_repository(available_models) -> Mock:
    """A repository stub returning a fixed set of effective models."""
    repo = Mock()
    repo.list_effective_models.return_value = available_models
    return repo


# ---------------------------------------------------------------------------
# TASK_TYPE_TO_TIER mapping
# ---------------------------------------------------------------------------

class TestTaskTypeToTierMapping:
    def test_simple_chat_maps_to_fast(self):
        assert TASK_TYPE_TO_TIER["simple_chat"] == "fast"

    def test_code_generation_maps_to_balanced(self):
        assert TASK_TYPE_TO_TIER["code_generation"] == "balanced"

    def test_code_review_maps_to_powerful(self):
        assert TASK_TYPE_TO_TIER["code_review"] == "powerful"

    def test_analysis_maps_to_powerful(self):
        assert TASK_TYPE_TO_TIER["analysis"] == "powerful"

    def test_unknown_task_type_defaults_to_balanced(self, mock_repository):
        engine = RoutingEngine(mock_repository)
        result = engine.route(
            task_type="unknown_type", context_length=8000, required_capabilities=[]
        )
        assert result.selected_model.tier == "balanced"


# ---------------------------------------------------------------------------
# Tier-based selection
# ---------------------------------------------------------------------------

class TestTierSelection:
    def test_selects_balanced_for_code_generation(self, mock_repository):
        engine = RoutingEngine(mock_repository)
        result = engine.route(
            task_type="code_generation", context_length=8000, required_capabilities=[]
        )

        assert isinstance(result, RoutingResult)
        assert result.selected_model.tier == "balanced"
        assert "code_generation" in result.reason

    def test_selects_fast_for_simple_chat(self, mock_repository):
        engine = RoutingEngine(mock_repository)
        result = engine.route(
            task_type="simple_chat", context_length=8000, required_capabilities=[]
        )
        assert result.selected_model.tier == "fast"

    def test_selects_powerful_for_analysis(self, mock_repository):
        engine = RoutingEngine(mock_repository)
        result = engine.route(
            task_type="analysis", context_length=8000, required_capabilities=[]
        )
        assert result.selected_model.tier == "powerful"

    def test_selects_powerful_for_code_review(self, mock_repository):
        engine = RoutingEngine(mock_repository)
        result = engine.route(
            task_type="code_review", context_length=8000, required_capabilities=[]
        )
        assert result.selected_model.tier == "powerful"

    def test_engine_reads_models_from_repository(self, mock_repository):
        engine = RoutingEngine(mock_repository)
        engine.route(task_type="analysis", context_length=8000, required_capabilities=[])
        mock_repository.list_effective_models.assert_called_once_with()


# ---------------------------------------------------------------------------
# Context-length filtering
# ---------------------------------------------------------------------------

class TestContextLengthFiltering:
    def test_filters_by_context_length(self, mock_repository):
        engine = RoutingEngine(mock_repository)
        # analysis -> powerful; 150K requires the 200K model
        result = engine.route(
            task_type="analysis", context_length=150_000, required_capabilities=[]
        )

        assert result.selected_model.limits.native >= 150_000
        assert result.selected_model.tier == "powerful"

    def test_falls_back_when_preferred_tier_excluded_by_context(self, mock_repository):
        engine = RoutingEngine(mock_repository)
        # simple_chat -> fast (128K), but 160K excludes both 128K models
        result = engine.route(
            task_type="simple_chat", context_length=160_000, required_capabilities=[]
        )

        assert result.selected_model.limits.native >= 160_000
        assert result.selected_model.tier == "powerful"

    def test_raises_when_no_model_fits_context(self, mock_repository):
        engine = RoutingEngine(mock_repository)
        with pytest.raises(ValueError, match="No models"):
            engine.route(
                task_type="analysis", context_length=999_999, required_capabilities=[]
            )

    def test_raises_when_capability_filters_everything_out(self):
        repo = Mock()
        repo.list_effective_models.return_value = [
            _make_effective(
                tier="balanced", native_context=128_000,
                capabilities={"chat": True}, model_id="balanced-model",
            ),
        ]
        engine = RoutingEngine(repo)
        with pytest.raises(ValueError, match="No models"):
            engine.route(
                task_type="analysis",
                context_length=8000,
                required_capabilities=["nonexistent-capability"],
            )


# ---------------------------------------------------------------------------
# Capability filtering
# ---------------------------------------------------------------------------

class TestCapabilityFiltering:
    def _models_with_capabilities(self) -> List[EffectiveModel]:
        return [
            _make_effective(
                tier="fast", native_context=128_000,
                capabilities={"chat": True}, model_id="fast-model",
            ),
            _make_effective(
                tier="balanced", native_context=128_000,
                capabilities={"chat": True, "vision": True}, model_id="balanced-model",
            ),
            _make_effective(
                tier="powerful", native_context=200_000,
                capabilities={"chat": True, "vision": True}, model_id="powerful-model",
            ),
        ]

    def test_filters_out_models_missing_capability(self):
        repo = Mock()
        repo.list_effective_models.return_value = self._models_with_capabilities()
        engine = RoutingEngine(repo)
        result = engine.route(
            task_type="code_generation", context_length=8000,
            required_capabilities=["vision"],
        )
        # The fast model lacks vision, so a non-fast model is chosen.
        assert result.selected_model.tier != "fast"
        assert result.selected_model.capabilities.get("vision") is True

    def test_capability_marked_false_is_not_supported(self):
        repo = Mock()
        repo.list_effective_models.return_value = [
            _make_effective(
                tier="balanced", native_context=128_000,
                capabilities={"chat": True, "vision": False}, model_id="balanced-model",
            ),
            _make_effective(
                tier="powerful", native_context=200_000,
                capabilities={"chat": True, "vision": True}, model_id="powerful-model",
            ),
        ]
        engine = RoutingEngine(repo)
        result = engine.route(
            task_type="code_generation", context_length=8000,
            required_capabilities=["vision"],
        )
        assert result.selected_model.tier == "powerful"

    def test_missing_capability_metadata_is_permissive(self, mock_repository):
        """Models without capability metadata are not dropped."""
        engine = RoutingEngine(mock_repository)
        result = engine.route(
            task_type="analysis", context_length=8000,
            required_capabilities=["tool_use"],
        )
        # The powerful model has no capability metadata at all -> permissive.
        assert result.selected_model.tier == "powerful"

    def test_empty_capabilities_returns_tier_match(self, mock_repository):
        engine = RoutingEngine(mock_repository)
        result = engine.route(
            task_type="code_generation", context_length=8000, required_capabilities=[]
        )
        assert result.selected_model.tier == "balanced"


# ---------------------------------------------------------------------------
# Tier fallback
# ---------------------------------------------------------------------------

class TestTierFallback:
    def test_falls_back_to_balanced_when_no_fast_models(self):
        repo = Mock()
        repo.list_effective_models.return_value = [
            _make_effective(tier="balanced", native_context=128_000),
            _make_effective(tier="powerful", native_context=200_000),
        ]
        engine = RoutingEngine(repo)
        result = engine.route(
            task_type="simple_chat", context_length=8000, required_capabilities=[]
        )
        assert result.selected_model.tier == "balanced"

    def test_falls_back_through_chain_to_only_available(self):
        repo = Mock()
        repo.list_effective_models.return_value = [
            _make_effective(tier="powerful", native_context=200_000),
        ]
        engine = RoutingEngine(repo)
        result = engine.route(
            task_type="simple_chat", context_length=8000, required_capabilities=[]
        )
        assert result.selected_model.tier == "powerful"


# ---------------------------------------------------------------------------
# User preference
# ---------------------------------------------------------------------------

class TestUserPreference:
    def test_preferred_tier_overrides_task_type_mapping(self, mock_repository):
        engine = RoutingEngine(mock_repository)
        result = engine.route(
            task_type="code_generation",  # would normally pick "balanced"
            context_length=8000,
            required_capabilities=[],
            user_preference=RoutingPreference(preferred_tier="powerful"),
        )
        assert result.selected_model.tier == "powerful"

    def test_locked_model_short_circuits_selection(self, mock_repository):
        locked = _make_effective(
            tier="fast", native_context=8_000, model_id="locked-model"
        )
        engine = RoutingEngine(mock_repository)
        result = engine.route(
            task_type="analysis",  # would normally pick "powerful"
            context_length=8000,
            required_capabilities=[],
            user_preference=RoutingPreference(locked_model=locked),
        )
        assert result.selected_model == locked
        assert result.reason == "用户已锁定模型"

    def test_locked_model_used_even_when_context_is_too_small(self, mock_repository):
        locked = _make_effective(
            tier="fast", native_context=8_000, model_id="locked-model"
        )
        engine = RoutingEngine(mock_repository)
        result = engine.route(
            task_type="analysis",
            context_length=150_000,
            required_capabilities=[],
            user_preference=RoutingPreference(locked_model=locked),
        )
        assert result.selected_model == locked

    def test_preference_without_locked_model_selects_normally(self, mock_repository):
        engine = RoutingEngine(mock_repository)
        result = engine.route(
            task_type="simple_chat",
            context_length=8000,
            required_capabilities=[],
            user_preference=RoutingPreference(preferred_tier=None),
        )
        assert result.selected_model.tier == "fast"


# ---------------------------------------------------------------------------
# Alternatives
# ---------------------------------------------------------------------------

class TestAlternatives:
    def test_returns_alternatives_excluding_selected(self, mock_repository):
        engine = RoutingEngine(mock_repository)
        result = engine.route(
            task_type="code_generation", context_length=8000, required_capabilities=[]
        )
        assert len(result.alternatives) <= 3
        assert result.selected_model not in result.alternatives

    def test_alternatives_count_is_capped(self):
        repo = Mock()
        repo.list_effective_models.return_value = [
            _make_effective(
                tier="fast", native_context=128_000, model_id=f"m{i}"
            )
            for i in range(10)
        ]
        engine = RoutingEngine(repo)
        result = engine.route(
            task_type="simple_chat", context_length=8000, required_capabilities=[]
        )
        assert len(result.alternatives) <= 3


# ---------------------------------------------------------------------------
# RoutingResult shape
# ---------------------------------------------------------------------------

class TestRoutingResultShape:
    def test_result_has_selected_model_reason_alternatives(self, mock_repository):
        engine = RoutingEngine(mock_repository)
        result = engine.route(
            task_type="code_generation", context_length=8000, required_capabilities=[]
        )
        assert hasattr(result, "selected_model")
        assert hasattr(result, "reason")
        assert hasattr(result, "alternatives")
        assert isinstance(result.selected_model, EffectiveModel)
        assert isinstance(result.reason, str)
        assert isinstance(result.alternatives, list)

    def test_result_reason_includes_task_type(self, mock_repository):
        engine = RoutingEngine(mock_repository)
        result = engine.route(
            task_type="code_review", context_length=8000, required_capabilities=[]
        )
        assert "code_review" in result.reason

    def test_routing_preference_defaults(self):
        preference = RoutingPreference()
        assert preference.preferred_tier is None
        assert preference.locked_model is None


# ---------------------------------------------------------------------------
# Tier derivation (model catalog -> resolver)
# ---------------------------------------------------------------------------

class TestTierDerivation:
    def _layer(self, source: str, tier: Optional[str] = None) -> LayerValues:
        return LayerValues(
            limits=ContextLimits(native=128_000),
            price=Price(),
            source=source,
            revision=0,
            tier=tier,
        )

    def test_resolve_layers_derives_tier_from_layers(self):
        layers = [
            self._layer("probe"),
            self._layer("builtin", tier="powerful"),
        ]
        assert resolve_layers(layers).tier == "powerful"

    def test_resolve_layers_prefers_first_layer_carrying_tier(self):
        layers = [
            self._layer("probe", tier="fast"),
            self._layer("builtin", tier="powerful"),
        ]
        assert resolve_layers(layers).tier == "fast"

    def test_resolve_layers_defaults_to_balanced_without_tier(self):
        assert resolve_layers([self._layer("probe")]).tier == "balanced"

    def test_resolve_layers_defaults_to_balanced_for_empty_layers(self):
        assert resolve_layers([]).tier == "balanced"


# ---------------------------------------------------------------------------
# Catalog repository integration (real SQLite)
# ---------------------------------------------------------------------------

@pytest.fixture()
def catalog_repo(tmp_path):
    from backend.data.database import Database
    from backend.model_catalog.repository import CatalogRepository

    db = Database(str(tmp_path / "routing_catalog.db"))
    db.init_db()
    yield CatalogRepository(db)
    db.close()


def _publish(repo, provider, model_id, tier, native, capabilities=None):
    """Stage, apply and bind a catalog model."""
    record = CandidateModel(
        model_key=ModelKey(provider=provider, model_id=model_id),
        tier=tier,
        native=native,
        price=Price(),
        source="builtin",
        pricing_scope="openrouter",
        capabilities=capabilities,
    )
    snapshot = repo.stage([record], record.source)
    item = repo.diff(snapshot)[0]
    repo.apply(
        snapshot, item.id, ["native", "price", "capabilities"], item.base_revision
    )
    repo.bind(
        EndpointKey(endpoint_id=f"ep-{model_id}", model_id=model_id),
        ModelKey(provider=provider, model_id=model_id),
        "openrouter",
    )
    return EndpointKey(endpoint_id=f"ep-{model_id}", model_id=model_id)


class TestCatalogRepositoryIntegration:
    def test_resolve_fills_tier_model_key_and_capabilities(self, catalog_repo):
        endpoint = _publish(
            catalog_repo, "openai", "gpt-4o-mini", "fast", 128_000,
            capabilities={"chat": True, "vision": False},
        )
        effective = catalog_repo.resolve(endpoint)

        assert effective.tier == "fast"
        assert effective.model_key == ModelKey(provider="openai", model_id="gpt-4o-mini")
        assert effective.capabilities == {"chat": True, "vision": False}
        assert effective.limits.native == 128_000

    def test_list_effective_models_returns_bound_models(self, catalog_repo):
        _publish(catalog_repo, "openai", "gpt-4o-mini", "fast", 128_000)
        _publish(catalog_repo, "anthropic", "claude-3-opus", "powerful", 200_000)

        models = catalog_repo.list_effective_models()

        assert len(models) == 2
        assert {m.tier for m in models} == {"fast", "powerful"}
        assert {m.model_key.model_id for m in models} == {"gpt-4o-mini", "claude-3-opus"}

    def test_list_effective_models_dedupes_by_model_key(self, catalog_repo):
        model_key = ModelKey(provider="openai", model_id="gpt-4o-mini")
        record = CandidateModel(
            model_key=model_key,
            tier="fast",
            native=128_000,
            price=Price(),
            source="builtin",
            pricing_scope="openrouter",
        )
        snapshot = catalog_repo.stage([record], record.source)
        item = catalog_repo.diff(snapshot)[0]
        catalog_repo.apply(
            snapshot, item.id, ["native", "price"], item.base_revision
        )
        # Same catalog model bound to two endpoints.
        catalog_repo.bind(
            EndpointKey(endpoint_id="ep-a", model_id="gpt-4o-mini"), model_key, "openrouter"
        )
        catalog_repo.bind(
            EndpointKey(endpoint_id="ep-b", model_id="gpt-4o-mini"), model_key, "openrouter"
        )

        models = catalog_repo.list_effective_models()

        assert len(models) == 1
        assert models[0].model_key == model_key

    def test_engine_routes_over_real_catalog(self, catalog_repo):
        _publish(catalog_repo, "openai", "gpt-4o-mini", "fast", 128_000)
        _publish(catalog_repo, "anthropic", "claude-3-opus", "powerful", 200_000)

        engine = RoutingEngine(catalog_repo)
        result = engine.route(
            task_type="analysis", context_length=8000, required_capabilities=[]
        )

        assert result.selected_model.tier == "powerful"
        assert result.selected_model.model_key.model_id == "claude-3-opus"
