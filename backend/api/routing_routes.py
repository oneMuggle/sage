"""Routing API endpoints.

Provides a single POST endpoint that delegates to the RoutingEngine
to select the best model for a given task.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from backend.model_catalog.schemas import EffectiveModel
from backend.routing.routing_engine import (
    RoutingEngine,
    RoutingPreference,
    RoutingResult,
)


class RoutingRequest(BaseModel):
    """Request body for the routing endpoint."""

    task_type: str
    context_length: int
    required_capabilities: List[str]
    user_preference: Optional[RoutingPreference] = None


class RoutingResponse(BaseModel):
    """Response body returned by the routing endpoint."""

    selected_model: EffectiveModel
    reason: str
    alternatives: List[EffectiveModel]


def build_router(catalog_repository=None) -> APIRouter:
    """Build a routing API router.

    Args:
        catalog_repository: A ``CatalogRepository`` instance.  When *None*
            the repository is resolved lazily via ``get_database()`` on each
            request (production path).  Tests pass an explicit repository
            to avoid touching the global database singleton.
    """
    router = APIRouter(prefix="/api/v1/routing", tags=["routing"])

    @router.post("/route", response_model=RoutingResponse)
    def route(request: RoutingRequest) -> RoutingResponse:
        """Route to the best model based on task requirements."""
        repo = catalog_repository
        if repo is None:
            from backend.data.database import get_database
            from backend.model_catalog.repository import CatalogRepository

            repo = CatalogRepository(get_database())

        engine = RoutingEngine(repo)
        result: RoutingResult = engine.route(
            task_type=request.task_type,
            context_length=request.context_length,
            required_capabilities=request.required_capabilities,
            user_preference=request.user_preference,
        )

        return RoutingResponse(
            selected_model=result.selected_model,
            reason=result.reason,
            alternatives=result.alternatives,
        )

    return router
