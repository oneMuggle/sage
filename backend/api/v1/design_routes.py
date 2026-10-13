"""Design studio API routes.

Endpoints:
- GET  /api/v1/design/systems              — list design systems
- GET  /api/v1/design/templates            — list design templates
- GET  /api/v1/design/projects             — list design projects
- POST /api/v1/design/projects             — create a design project
- GET  /api/v1/design/projects/{id}        — get a design project
- DELETE /api/v1/design/projects/{id}      — delete a design project
- POST /api/v1/design/projects/{id}/generate  — generate first artifact (SSE)
- POST /api/v1/design/projects/{id}/iterate   — iterate on artifact (SSE)
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict

from backend.design import get_design_studio
from backend.design.errors import (
    DesignError,
    DesignGenerationError,
    DesignProjectNotFoundError,
    DesignSystemNotFoundError,
    DesignTemplateNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/design", tags=["design"])


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class CreateProjectRequest(BaseModel):
    """POST /design/projects body."""

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: str
    system_id: str
    template_id: str
    brief: str


class GenerateRequest(BaseModel):
    """POST /design/projects/{id}/generate body."""

    model_config = ConfigDict(extra="forbid")

    brief: Optional[str] = None


class IterateRequest(BaseModel):
    """POST /design/projects/{id}/iterate body."""

    model_config = ConfigDict(extra="forbid")

    feedback: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_studio():
    """Return the global DesignStudio or raise 404."""
    studio = get_design_studio()
    if studio is None:
        raise HTTPException(
            status_code=404,
            detail="Design studio not initialised",
        )
    return studio


def _map_design_error(exc: DesignError) -> JSONResponse:
    """Convert a DesignError into the appropriate HTTP JSON response."""
    not_found = (
        DesignProjectNotFoundError,
        DesignSystemNotFoundError,
        DesignTemplateNotFoundError,
    )
    status = 404 if isinstance(exc, not_found) else 500
    return JSONResponse(status_code=status, content={"detail": str(exc)})


def _sse_event(event_type: str, payload: dict) -> str:
    """Format a single SSE event frame."""
    return f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"


# ---------------------------------------------------------------------------
# GET /design/systems
# ---------------------------------------------------------------------------


@router.get("/systems")
async def list_systems(
    category: Optional[str] = Query(None, description="Filter by category"),
):
    """Return all registered design systems, optionally filtered by category."""
    studio = _require_studio()
    try:
        systems = studio.list_systems()
    except Exception as exc:
        logger.exception("Failed to list design systems")
        return JSONResponse(
            status_code=500,
            content={"detail": f"Registry error: {exc}"},
        )
    if category is not None:
        systems = [s for s in systems if s.category == category]
    return systems


# ---------------------------------------------------------------------------
# GET /design/templates
# ---------------------------------------------------------------------------


@router.get("/templates")
async def list_templates(
    kind: Optional[str] = Query(
        None, description="Filter by kind: prototype | deck",
    ),
):
    """Return all registered design templates, optionally filtered by kind."""
    studio = _require_studio()
    try:
        templates = studio.list_templates(kind=kind)
    except Exception as exc:
        logger.exception("Failed to list design templates")
        return JSONResponse(
            status_code=500,
            content={"detail": f"Registry error: {exc}"},
        )
    return templates


# ---------------------------------------------------------------------------
# GET /design/projects
# ---------------------------------------------------------------------------


@router.get("/projects")
async def list_projects(
    kind: Optional[str] = Query(None, description="Filter by kind"),
):
    """Return all design projects, optionally filtered by kind."""
    studio = _require_studio()
    return studio.list_projects(kind=kind)


# ---------------------------------------------------------------------------
# POST /design/projects
# ---------------------------------------------------------------------------


@router.post("/projects", status_code=201)
async def create_project(req: CreateProjectRequest):
    """Create a new design project."""
    studio = _require_studio()
    if req.kind not in ("prototype", "deck"):
        return JSONResponse(
            status_code=400,
            content={
                "detail": (
                    f"Invalid kind {req.kind!r}; "
                    "must be 'prototype' or 'deck'"
                ),
            },
        )
    try:
        project = studio.create_project(
            name=req.name,
            kind=req.kind,
            system_id=req.system_id,
            template_id=req.template_id,
            brief=req.brief,
        )
    except (DesignSystemNotFoundError, DesignTemplateNotFoundError) as exc:
        return _map_design_error(exc)
    except DesignError as exc:
        return _map_design_error(exc)
    return project


# ---------------------------------------------------------------------------
# GET /design/projects/:project_id
# ---------------------------------------------------------------------------


@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    """Return a design project with its latest artifact (if any)."""
    studio = _require_studio()
    try:
        project = studio.get_project(project_id)
        artifact = studio.get_latest_artifact(project_id)
    except DesignProjectNotFoundError as exc:
        return _map_design_error(exc)
    except Exception as exc:
        logger.exception("Failed to get design project %s", project_id)
        return JSONResponse(
            status_code=500, content={"detail": str(exc)},
        )
    return {
        **project.model_dump(),
        "latest_artifact": (
            artifact.model_dump() if artifact is not None else None
        ),
    }


# ---------------------------------------------------------------------------
# DELETE /design/projects/:project_id
# ---------------------------------------------------------------------------


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    """Delete a design project and its artifacts."""
    studio = _require_studio()
    try:
        studio.get_project(project_id)
    except DesignProjectNotFoundError as exc:
        return _map_design_error(exc)
    studio.delete_project(project_id)
    return {"success": True}


# ---------------------------------------------------------------------------
# POST /design/projects/:project_id/generate (SSE)
# ---------------------------------------------------------------------------


@router.post("/projects/{project_id}/generate")
async def generate_artifact(project_id: str, req: GenerateRequest):
    """Generate the first artifact for a project (SSE stream)."""
    studio = _require_studio()
    try:
        studio.get_project(project_id)
    except DesignProjectNotFoundError as exc:
        return _map_design_error(exc)

    async def event_stream():
        try:
            yield _sse_event("progress", {
                "stage": "starting",
                "message": "Initialising generation",
            })
            artifact = await studio.generate(
                project_id, brief=req.brief,
            )
            yield _sse_event("progress", {
                "stage": "complete",
                "message": "Generation finished",
            })
            yield _sse_event("complete", {
                "artifact": artifact.model_dump(mode="json"),
            })
        except DesignProjectNotFoundError as exc:
            yield _sse_event("error", {"detail": str(exc)})
        except DesignGenerationError as exc:
            yield _sse_event("error", {"detail": str(exc)})
        except Exception as exc:
            logger.exception("Design generation failed")
            yield _sse_event("error", {
                "detail": f"Generation failed: {exc}",
            })

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# POST /design/projects/:project_id/iterate (SSE)
# ---------------------------------------------------------------------------


@router.post("/projects/{project_id}/iterate")
async def iterate_artifact(project_id: str, req: IterateRequest):
    """Iterate on the latest artifact using user feedback (SSE stream)."""
    studio = _require_studio()
    try:
        studio.get_project(project_id)
    except DesignProjectNotFoundError as exc:
        return _map_design_error(exc)

    async def event_stream():
        try:
            yield _sse_event("progress", {
                "stage": "starting",
                "message": "Initialising iteration",
            })
            artifact = await studio.iterate(
                project_id, feedback=req.feedback,
            )
            yield _sse_event("progress", {
                "stage": "complete",
                "message": "Iteration finished",
            })
            yield _sse_event("complete", {
                "artifact": artifact.model_dump(mode="json"),
            })
        except DesignProjectNotFoundError as exc:
            yield _sse_event("error", {"detail": str(exc)})
        except DesignGenerationError as exc:
            yield _sse_event("error", {"detail": str(exc)})
        except Exception as exc:
            logger.exception("Design iteration failed")
            yield _sse_event("error", {
                "detail": f"Iteration failed: {exc}",
            })

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
