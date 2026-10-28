"""Unit tests for endpoint-scoped smart routing integration.

Covers the repository endpoint filter, the engine's additive endpoint scope,
and the fail-safe ``resolve_routed_chat_model`` helper.
"""
from __future__ import annotations

import pytest

from backend.data.database import Database
from backend.model_catalog.repository import CatalogRepository
from backend.model_catalog.schemas import (
    CandidateModel,
    EndpointKey,
    ModelKey,
    Price,
)
from backend.orchestration.llm_factory import resolve_routed_chat_model
from backend.routing.routing_engine import RoutingEngine


@pytest.fixture()
def repo(tmp_path):
    db = Database(str(tmp_path / "routing_helper.db"))
    db.init_db()
    yield CatalogRepository(db)
    db.close()


def _publish(repo, endpoint_id, provider, model_id, tier, native):
    record = CandidateModel(
        model_key=ModelKey(provider=provider, model_id=model_id),
        tier=tier,
        native=native,
        price=Price(),
        source="builtin",
        pricing_scope="openrouter",
    )
    snapshot = repo.stage([record], record.source)
    item = repo.diff(snapshot)[0]
    repo.apply(snapshot, item.id, ["native", "price"], item.base_revision)
    repo.bind(
        EndpointKey(endpoint_id=endpoint_id, model_id=model_id),
        ModelKey(provider=provider, model_id=model_id),
        "openrouter",
    )


@pytest.fixture()
def two_endpoint_repo(repo):
    """ep-a owns fast+powerful; ep-b owns balanced only."""
    _publish(repo, "ep-a", "openai", "gpt-4o-mini", "fast", 128_000)
    _publish(repo, "ep-a", "anthropic", "claude-3-opus", "powerful", 200_000)
    _publish(repo, "ep-b", "anthropic", "claude-3-sonnet", "balanced", 128_000)
    return repo


def _ids(models):
    return sorted(m.model_key.model_id for m in models)


class TestListEffectiveModelsEndpointFilter:
    def test_unscoped_returns_every_bound_model(self, two_endpoint_repo):
        assert _ids(two_endpoint_repo.list_effective_models()) == [
            "claude-3-opus",
            "claude-3-sonnet",
            "gpt-4o-mini",
        ]

    def test_scoped_returns_only_that_endpoint(self, two_endpoint_repo):
        assert _ids(two_endpoint_repo.list_effective_models(endpoint_id="ep-a")) == [
            "claude-3-opus",
            "gpt-4o-mini",
        ]
        assert _ids(two_endpoint_repo.list_effective_models(endpoint_id="ep-b")) == [
            "claude-3-sonnet",
        ]

    def test_unknown_endpoint_returns_empty(self, two_endpoint_repo):
        assert two_endpoint_repo.list_effective_models(endpoint_id="ep-missing") == []


class TestRoutingEngineEndpointScope:
    def test_route_scoped_to_endpoint(self, two_endpoint_repo):
        """code_generation wants balanced; only ep-b has one."""
        result = RoutingEngine(two_endpoint_repo).route(
            task_type="code_generation",
            context_length=8000,
            endpoint_id="ep-b",
        )
        assert result.selected_model.model_key.model_id == "claude-3-sonnet"

    def test_route_unscoped_unchanged(self, two_endpoint_repo):
        """Default endpoint_id=None keeps whole-catalog behavior."""
        result = RoutingEngine(two_endpoint_repo).route(
            task_type="code_generation",
            context_length=8000,
        )
        assert result.selected_model.tier == "balanced"

    def test_route_scoped_no_match_raises_value_error(self, two_endpoint_repo):
        """An endpoint with no bound models yields no candidates at all."""
        with pytest.raises(ValueError, match="No models match"):
            RoutingEngine(two_endpoint_repo).route(
                task_type="simple_chat",
                context_length=8000,
                endpoint_id="ep-missing",
            )


class TestResolveRoutedChatModel:
    def test_returns_selected_model_id(self, two_endpoint_repo):
        model_id = resolve_routed_chat_model(
            task_type="code_generation",
            context_length=8000,
            endpoint_id="ep-b",
            catalog_repository=two_endpoint_repo,
        )
        assert model_id == "claude-3-sonnet"

    def test_returns_none_when_no_model_matches(self, two_endpoint_repo):
        """Fail-safe: unsatisfiable request never raises."""
        model_id = resolve_routed_chat_model(
            task_type="code_generation",
            context_length=999_999,
            endpoint_id="ep-b",
            catalog_repository=two_endpoint_repo,
        )
        assert model_id is None

    def test_returns_none_when_repository_raises(self):
        class BrokenRepo:
            def list_effective_models(self, endpoint_id=None):
                raise RuntimeError("catalog unavailable")

        assert (
            resolve_routed_chat_model(
                task_type="chat",
                catalog_repository=BrokenRepo(),
            )
            is None
        )
