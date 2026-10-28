"""Integration tests for the routing API endpoint.

Tests run against an ephemeral SQLite database with the routing router
mounted on a FastAPI app. Each test gets a fresh client + repo pair.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.local_auth import get_local_auth_token
from backend.data.database import Database
from backend.model_catalog.repository import CatalogRepository
from backend.model_catalog.schemas import (
    CandidateModel,
    EndpointKey,
    ModelKey,
    Price,
)


@pytest.fixture()
def repo(tmp_path):
    db = Database(str(tmp_path / "routing_test.db"))
    db.init_db()
    yield CatalogRepository(db)
    db.close()


def _candidate(provider, model_id, tier, native, capabilities=None):
    return CandidateModel(
        model_key=ModelKey(provider=provider, model_id=model_id),
        tier=tier,
        native=native,
        price=Price(),
        source="builtin",
        pricing_scope="openrouter",
        capabilities=capabilities,
    )


def _publish(repo, provider, model_id, tier, native, capabilities=None):
    """Stage, apply and bind a catalog model."""
    record = _candidate(provider, model_id, tier, native, capabilities)
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


@pytest.fixture()
def seeded_repo(repo):
    """A repo pre-loaded with three models across the three tiers."""
    _publish(repo, "openai", "gpt-4o-mini", "fast", 128_000, {"chat": True})
    _publish(repo, "anthropic", "claude-3-sonnet", "balanced", 128_000, {"chat": True})
    _publish(repo, "anthropic", "claude-3-opus", "powerful", 200_000, {"chat": True})
    return repo


@pytest.fixture()
def client(seeded_repo):
    from backend.api.routing_routes import build_router

    app = FastAPI()
    app.include_router(build_router(seeded_repo))
    token = get_local_auth_token()
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


class TestRoutingApi:
    def test_route_returns_selected_model_reason_alternatives(self, client):
        """POST /api/v1/routing/route returns a valid routing decision."""
        response = client.post(
            "/api/v1/routing/route",
            json={
                "task_type": "code_generation",
                "context_length": 8000,
                "required_capabilities": ["chat"],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "selected_model" in data
        assert "reason" in data
        assert "alternatives" in data
        assert data["selected_model"]["tier"] in ["fast", "balanced", "powerful"]

    def test_route_with_user_preference_powerful(self, client):
        """User preference for 'powerful' tier overrides the task-type mapping."""
        response = client.post(
            "/api/v1/routing/route",
            json={
                "task_type": "code_generation",
                "context_length": 8000,
                "required_capabilities": ["chat"],
                "user_preference": {
                    "preferred_tier": "powerful",
                },
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["selected_model"]["tier"] == "powerful"

    def test_route_selects_correct_tier_for_task_type(self, client):
        """code_generation maps to balanced tier by default."""
        response = client.post(
            "/api/v1/routing/route",
            json={
                "task_type": "code_generation",
                "context_length": 8000,
                "required_capabilities": [],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["selected_model"]["tier"] == "balanced"

    def test_route_returns_alternatives_excluding_selected(self, client):
        """Alternatives do not include the selected model."""
        response = client.post(
            "/api/v1/routing/route",
            json={
                "task_type": "analysis",
                "context_length": 8000,
                "required_capabilities": [],
            },
        )

        assert response.status_code == 200
        data = response.json()
        selected_id = data["selected_model"]["model_key"]["model_id"]
        for alt in data["alternatives"]:
            assert alt["model_key"]["model_id"] != selected_id

    def test_route_422_on_missing_fields(self, client):
        """Missing required fields returns 422."""
        response = client.post(
            "/api/v1/routing/route",
            json={"task_type": "chat"},
        )
        assert response.status_code == 422

    def test_route_422_when_no_model_matches(self, client):
        """An unsatisfiable context length is a client error, not a 500."""
        response = client.post(
            "/api/v1/routing/route",
            json={
                "task_type": "code_generation",
                "context_length": 999_999,
                "required_capabilities": [],
            },
        )

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert isinstance(detail, str)
        assert detail


class TestAuthorization:
    def test_route_rejects_wrong_token(self, seeded_repo):
        """The handler enforces local auth itself (a bare app has no middleware)."""
        from backend.api.routing_routes import build_router

        app = FastAPI()
        app.include_router(build_router(seeded_repo))
        wrong_token_client = TestClient(
            app, headers={"Authorization": "Bearer wrong-token"}
        )

        response = wrong_token_client.post(
            "/api/v1/routing/route",
            json={
                "task_type": "code_generation",
                "context_length": 8000,
                "required_capabilities": [],
            },
        )

        assert response.status_code == 401


def test_routing_route_registered_on_app():
    """The routing endpoint is wired into the production app."""
    from backend.main import app

    paths = {(r.path, m) for r in app.routes for m in getattr(r, "methods", set())}
    assert ("/api/v1/routing/route", "POST") in paths
