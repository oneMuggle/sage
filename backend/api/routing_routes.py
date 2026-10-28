"""Routing API endpoints.

Provides a single POST endpoint that delegates to the RoutingEngine
to select the best model for a given task.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.api.local_auth import require_local_auth
from backend.model_catalog.schemas import EffectiveModel
from backend.routing.routing_engine import (
    RoutingEngine,
    RoutingPreference,
    RoutingResult,
)


class RoutingRequest(BaseModel):
    """Request body for the routing endpoint."""

    task_type: str
    context_length: int = Field(ge=0)
    required_capabilities: List[str]
    user_preference: Optional[RoutingPreference] = None
    endpoint_id: Optional[str] = None


class RoutingResponse(BaseModel):
    """Response body returned by the routing endpoint."""

    selected_model: EffectiveModel
    reason: str
    alternatives: List[EffectiveModel]


def build_router(catalog_repository=None) -> APIRouter:
    """Build a routing API router.

    Repository resolution order: the injected ``catalog_repository`` (tests),
    then ``request.app.state.catalog_repo`` (production, set during lifespan
    startup in ``backend.main``), then a repository over the global database.
    """
    router = APIRouter(prefix="/api/v1/routing", tags=["routing"])

    @router.post("/route", response_model=RoutingResponse)
    def route(request: Request, payload: RoutingRequest) -> RoutingResponse:
        """Route to the best model based on task requirements."""
        require_local_auth(request)

        repo = catalog_repository
        if repo is None:
            repo = getattr(request.app.state, "catalog_repo", None)
        if repo is None:
            from backend.data.database import get_database
            from backend.model_catalog.repository import CatalogRepository

            repo = CatalogRepository(get_database())

        engine = RoutingEngine(repo)
        try:
            result: RoutingResult = engine.route(
                task_type=payload.task_type,
                context_length=payload.context_length,
                required_capabilities=payload.required_capabilities,
                user_preference=payload.user_preference,
                endpoint_id=payload.endpoint_id,
            )
        except ValueError as exc:
            # No model can satisfy the requested constraints: a client-actionable
            # condition, not a server error.
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        return RoutingResponse(
            selected_model=result.selected_model,
            reason=result.reason,
            alternatives=result.alternatives,
        )

    return router
