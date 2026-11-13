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
- POST /api/v1/design/projects/{id}/export    — export artifact (PDF/PPTX/ZIP/HTML)
- POST /api/v1/design/outline                 — extract Word → markdown outline
- POST /api/v1/design/projects/{id}/source    — bind a data source (xlsx/csv/json)
- GET  /api/v1/design/projects/{id}/source    — read current source binding
- DELETE /api/v1/design/projects/{id}/source  — remove source binding
- POST /api/v1/design/projects/{id}/refresh   — regenerate with current source (SSE)
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from backend.compat.win7.pydantic_compat import ConfigDict
from backend.design import get_design_studio
from backend.design.errors import (
    DesignError,
    DesignGenerationError,
    DesignProjectNotFoundError,
    DesignSystemNotFoundError,
    DesignTemplateKindMismatchError,
    DesignTemplateNotFoundError,
)
from backend.design.export import DesignExporter

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


class ExportRequest(BaseModel):
    """POST /design/projects/{id}/export body."""

    model_config = ConfigDict(extra="forbid")

    format: str = "html"


class OutlineRequest(BaseModel):
    """POST /design/outline body."""

    model_config = ConfigDict(extra="forbid")

    file_path: str


class BindSourceRequest(BaseModel):
    """POST /design/projects/{id}/source body."""

    model_config = ConfigDict(extra="forbid")

    file_path: str
    kind: Optional[str] = None
    name: Optional[str] = None


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
    bad_request = DesignTemplateKindMismatchError
    status = (
        400 if isinstance(exc, bad_request)
        else 404 if isinstance(exc, not_found)
        else 500
    )
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
    try:
        studio.delete_project(project_id)
    except Exception as exc:
        logger.exception("Failed to delete design project %s", project_id)
        return JSONResponse(
            status_code=500, content={"detail": str(exc)},
        )
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
        except DesignTemplateKindMismatchError as exc:
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
        except DesignTemplateKindMismatchError as exc:
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


# ---------------------------------------------------------------------------
# POST /design/projects/:project_id/export
# ---------------------------------------------------------------------------


@router.post("/projects/{project_id}/export")
async def export_artifact(  # noqa: PLR0911 — 每个校验门一个返回是显式设计
    project_id: str, req: ExportRequest,
):
    """Export the latest artifact to PDF, PPTX, ZIP, or HTML.

    Returns:
        - format=html: { ok, format, html_content }
        - format=pdf/pptx/zip: { ok, format, file_path }
    """
    studio = _require_studio()
    try:
        studio.get_project(project_id)
        artifact = studio.get_latest_artifact(project_id)
    except DesignProjectNotFoundError as exc:
        return _map_design_error(exc)
    except Exception as exc:
        logger.exception("Failed to get design project %s", project_id)
        return JSONResponse(
            status_code=500, content={"detail": str(exc)},
        )

    if artifact is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Project {project_id} has no artifacts yet"},
        )

    if req.format not in ("pdf", "zip", "pptx", "html"):
        return JSONResponse(
            status_code=400,
            content={
                "detail": (
                    f"Invalid format {req.format!r}; "
                    "must be 'pdf', 'pptx', 'zip', or 'html'"
                ),
            },
        )

    try:
        # Determine output directory: workspace/design/{project_id}/
        workspace = studio._workspace
        output_dir = workspace / "design" / project_id
        output_dir.mkdir(parents=True, exist_ok=True)

        exporter = DesignExporter()
        result = exporter.export(
            html=artifact.html_content,
            output_dir=output_dir,
            format=req.format,
            filename=f"v{artifact.version}",
        )

        if not result.ok:
            return JSONResponse(
                status_code=500,
                content={"detail": result.error or "Export failed"},
            )

        return result.model_dump()

    except Exception as exc:
        logger.exception("Design export failed for project %s", project_id)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Export failed: {exc}"},
        )


# ---------------------------------------------------------------------------
# POST /design/outline — Word → markdown outline
# ---------------------------------------------------------------------------


@router.post("/outline")
async def extract_outline(req: OutlineRequest):
    """Extract a Word document into a slide-style markdown outline.

    Returns the OutlineResult (title, slide_count, outline_md) so the
    wizard step 4 can feed it into the project brief without a second
    LLM round-trip.
    """
    from pathlib import Path

    from backend.design.outline_extractor import OutlineExtractor

    path = Path(req.file_path)
    if not path.exists():
        return JSONResponse(
            status_code=404,
            content={"detail": f"File not found: {req.file_path}"},
        )
    if path.suffix.lower() not in (".docx",):
        return JSONResponse(
            status_code=400,
            content={
                "detail": (
                    f"Unsupported extension {path.suffix!r}; only .docx is "
                    "supported for outline extraction."
                ),
            },
        )

    try:
        result = OutlineExtractor().extract(path)
        return result.model_dump()
    except Exception as exc:
        logger.exception("Outline extraction failed for %s", req.file_path)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Outline extraction failed: {exc}"},
        )


# ---------------------------------------------------------------------------
# POST/GET/DELETE /design/projects/:project_id/source — data source binding
# ---------------------------------------------------------------------------


@router.post("/projects/{project_id}/source")
async def bind_source(project_id: str, req: BindSourceRequest):
    """Bind a data source (xlsx/csv/json) to a design project."""
    from backend.design.live_artifact import LiveArtifactEngine

    studio = _require_studio()
    try:
        studio.get_project(project_id)
    except DesignProjectNotFoundError as exc:
        return _map_design_error(exc)

    engine = LiveArtifactEngine(studio._workspace)
    try:
        binding = engine.bind(
            project_id,
            req.file_path,
            kind=req.kind,
            name=req.name,
        )
        return binding.model_dump()
    except FileNotFoundError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    except Exception as exc:
        logger.exception("Source binding failed for %s", project_id)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Source binding failed: {exc}"},
        )


@router.get("/projects/{project_id}/source")
async def get_source(project_id: str):
    """Read the current data source binding (or 404 if none is bound)."""
    from backend.design.live_artifact import LiveArtifactEngine

    studio = _require_studio()
    try:
        studio.get_project(project_id)
    except DesignProjectNotFoundError as exc:
        return _map_design_error(exc)

    engine = LiveArtifactEngine(studio._workspace)
    binding = engine.get_binding(project_id)
    if binding is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "No source binding for this project"},
        )
    return binding.model_dump()


@router.delete("/projects/{project_id}/source")
async def unbind_source(project_id: str):
    """Remove the data source binding for a project."""
    from backend.design.live_artifact import LiveArtifactEngine

    studio = _require_studio()
    try:
        studio.get_project(project_id)
    except DesignProjectNotFoundError as exc:
        return _map_design_error(exc)

    engine = LiveArtifactEngine(studio._workspace)
    removed = engine.unbind(project_id)
    if not removed:
        return JSONResponse(
            status_code=404,
            content={"detail": "No source binding to remove"},
        )
    return {"ok": True}


# ---------------------------------------------------------------------------
# POST /design/projects/:project_id/refresh — SSE regenerate with source
# ---------------------------------------------------------------------------


@router.post("/projects/{project_id}/refresh")
async def refresh_artifact(project_id: str):
    """Regenerate the artifact with the bound source data (SSE stream).

    Reuses the same SSE contract as ``/generate`` so the frontend can render
    the same progress bar and completion handler.
    """
    from backend.design.live_artifact import LiveArtifactEngine

    studio = _require_studio()
    try:
        studio.get_project(project_id)
    except DesignProjectNotFoundError as exc:
        return _map_design_error(exc)

    engine = LiveArtifactEngine(studio._workspace)

    async def event_stream():
        try:
            yield _sse_event("progress", {
                "stage": "starting",
                "message": "Re-reading source data",
            })
            artifact = await engine.refresh(studio, project_id)
            yield _sse_event("progress", {
                "stage": "complete",
                "message": "Refresh finished",
            })
            yield _sse_event("complete", {
                "artifact": artifact.model_dump(mode="json"),
            })
        except DesignProjectNotFoundError as exc:
            yield _sse_event("error", {"detail": str(exc)})
        except DesignGenerationError as exc:
            yield _sse_event("error", {"detail": str(exc)})
        except Exception as exc:
            logger.exception("Design refresh failed for %s", project_id)
            yield _sse_event("error", {
                "detail": f"Refresh failed: {exc}",
            })

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
