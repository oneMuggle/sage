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

import base64
import logging
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict

from backend.api.v1.design_shared import map_design_error as _map_design_error
from backend.api.v1.design_source_models import BindSourceRequest
from backend.api.v1.design_streaming import (
    sse_event as _sse_event,
    stream_studio_call as _stream_studio_call,
)
from backend.data.database import get_database

# Re-exported symbol: route tests patch `design_routes.get_design_studio`.
from backend.design import get_design_studio  # noqa: F401
from backend.design.errors import (
    DesignError,
    DesignGenerationError,
    DesignProjectNotFoundError,
    DesignSystemNotFoundError,
    DesignTemplateNotFoundError,
)
from backend.design.export import DesignExporter
from backend.design.office_sources import (
    OfficeSourceNotFoundError,
    resolve_source_input,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/design", tags=["design"])


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class CreateProjectRequest(BaseModel):
    """POST /design/projects body.

    Only ``brief`` is required; the studio resolves missing name, kind,
    system and template from defaults.
    """

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    kind: str = "deck"
    system_id: Optional[str] = None
    template_id: Optional[str] = None
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
    inline: bool = False


class TweaksRequest(BaseModel):
    """PUT /design/projects/{id}/tweaks body.

    ``replace=True`` writes the exact field set (nulls clear overrides);
    otherwise fields are merged and nulls are ignored.
    """

    model_config = ConfigDict(extra="forbid")

    accent: Optional[str] = None
    radius: Optional[float] = None
    font_size: Optional[float] = None
    density: Optional[float] = None
    font_family: Optional[str] = None
    replace: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# _map_design_error comes from design_shared; _require_studio stays local so
# tests keep patching `design_routes.get_design_studio`.
def _require_studio():
    """Return the global DesignStudio or raise 404."""
    from fastapi import HTTPException

    studio = get_design_studio()
    if studio is None:
        raise HTTPException(
            status_code=404,
            detail="Design studio not initialised",
        )
    return studio


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
# GET /design/projects/:project_id/artifacts — version history
# ---------------------------------------------------------------------------


@router.get("/projects/{project_id}/artifacts")
async def list_artifacts(project_id: str):
    """Return artifact version summaries (no HTML payload), oldest first."""
    studio = _require_studio()
    try:
        artifacts = studio.list_artifacts(project_id)
    except DesignProjectNotFoundError as exc:
        return _map_design_error(exc)
    return [
        {
            "id": a.id,
            "project_id": a.project_id,
            "version": a.version,
            "title": a.title,
            "kind": a.kind,
            "created_at": a.created_at.isoformat(),
        }
        for a in artifacts
    ]


@router.get("/projects/{project_id}/artifacts/{artifact_id}")
async def get_artifact(project_id: str, artifact_id: str):
    """Return one artifact with its full HTML content."""
    studio = _require_studio()
    try:
        studio.get_project(project_id)
        artifact = studio.get_artifact(artifact_id)
    except DesignProjectNotFoundError as exc:
        return _map_design_error(exc)
    if artifact.project_id != project_id:
        return JSONResponse(
            status_code=404,
            content={
                "detail": (
                    f"Artifact {artifact_id} does not belong to project "
                    f"{project_id}"
                ),
            },
        )
    return artifact.model_dump()


@router.post("/projects/{project_id}/artifacts/{artifact_id}/restore")
async def restore_artifact(project_id: str, artifact_id: str):
    """Restore an old artifact by appending it as a new version."""
    studio = _require_studio()
    try:
        artifact = studio.restore_artifact(project_id, artifact_id)
    except DesignProjectNotFoundError as exc:
        return _map_design_error(exc)
    return artifact.model_dump()


# ---------------------------------------------------------------------------
# GET /design/projects/:project_id/messages — iteration history
# ---------------------------------------------------------------------------


@router.get("/projects/{project_id}/messages")
async def list_messages(project_id: str):
    """Return persisted iteration messages, oldest first."""
    studio = _require_studio()
    try:
        messages = studio.list_messages(project_id)
    except DesignProjectNotFoundError as exc:
        return _map_design_error(exc)
    return [m.model_dump() for m in messages]


# ---------------------------------------------------------------------------
# GET/PUT /design/projects/:project_id/tweaks — design parameter overrides
# ---------------------------------------------------------------------------


@router.get("/projects/{project_id}/tweaks")
async def get_tweaks(project_id: str):
    """Return the project's tweaks (empty defaults when never set)."""
    studio = _require_studio()
    try:
        tweaks = studio.get_tweaks(project_id)
    except DesignProjectNotFoundError as exc:
        return _map_design_error(exc)
    return tweaks.model_dump()


@router.put("/projects/{project_id}/tweaks")
async def update_tweaks(project_id: str, req: TweaksRequest):
    """Merge partial tweaks into the project's tweak overrides.

    A request with every field omitted/null is treated as a full reset
    (the UI's "restore system defaults" button sends exactly that shape).
    """
    studio = _require_studio()
    try:
        if req.replace:
            tweaks = studio.set_tweaks(
                project_id,
                accent=req.accent,
                radius=req.radius,
                font_size=req.font_size,
                density=req.density,
                font_family=req.font_family,
            )
        elif all(
            value is None
            for value in (
                req.accent,
                req.radius,
                req.font_size,
                req.density,
                req.font_family,
            )
        ):
            tweaks = studio.clear_tweaks(project_id)
        else:
            tweaks = studio.update_tweaks(
                project_id,
                accent=req.accent,
                radius=req.radius,
                font_size=req.font_size,
                density=req.density,
                font_family=req.font_family,
            )
    except DesignProjectNotFoundError as exc:
        return _map_design_error(exc)
    return tweaks.model_dump()


# ---------------------------------------------------------------------------
# GET /design/projects/:project_id/review — lint latest artifact (no LLM)
# ---------------------------------------------------------------------------


@router.get("/projects/{project_id}/review")
async def review_artifact(project_id: str):
    """Run the design linter against the latest artifact.

    Reuses ``DesignLinter`` (the same P0/P1 rules used during generation)
    so users can re-check the current artifact after manual tweaks or
    historical restores. No LLM call.
    """
    from backend.design.lint import DesignLinter

    studio = _require_studio()
    try:
        studio.get_project(project_id)
        latest = studio.get_latest_artifact(project_id)
    except DesignProjectNotFoundError as exc:
        return _map_design_error(exc)
    if latest is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Project {project_id} has no artifacts yet"},
        )

    report = DesignLinter().lint(latest.html_content)
    return {
        "ok": report.ok,
        "error_count": report.error_count,
        "warning_count": report.warning_count,
        "issues": [
            {
                "rule_id": issue.rule_id,
                "severity": issue.severity.value,
                "message": issue.message,
                "line": issue.line,
            }
            for issue in report.issues
        ],
    }


# ---------------------------------------------------------------------------
# POST /design/projects/:project_id/generate (SSE)
# ---------------------------------------------------------------------------


@router.post("/projects/{project_id}/generate")
async def generate_artifact(project_id: str, req: GenerateRequest):
    """Generate the first artifact for a project (SSE stream).

    Progress events are pushed by the studio at each stage
    (starting → composing → generating → linting → saving → complete) and
    relayed immediately as SSE ``progress`` frames, followed by a single
    ``complete`` or ``error`` frame.
    """
    studio = _require_studio()
    try:
        studio.get_project(project_id)
    except DesignProjectNotFoundError as exc:
        return _map_design_error(exc)

    async def event_stream():
        async for frame in _stream_studio_call(
            lambda queue: studio.generate(
                project_id,
                brief=req.brief,
                progress_queue=queue,
            ),
            "Generation",
        ):
            yield frame

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
    """Iterate on the latest artifact using user feedback (SSE stream).

    Emits progress stages (starting → composing → generating → linting →
    saving → complete) followed by a single ``complete`` or ``error`` frame.
    """
    studio = _require_studio()
    try:
        studio.get_project(project_id)
    except DesignProjectNotFoundError as exc:
        return _map_design_error(exc)

    async def event_stream():
        async for frame in _stream_studio_call(
            lambda queue: studio.iterate(
                project_id,
                feedback=req.feedback,
                progress_queue=queue,
            ),
            "Iteration",
        ):
            yield frame

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

        if req.inline and req.format != "html" and result.file_path:
            from pathlib import Path as _Path

            path = _Path(result.file_path)
            return {
                "ok": True,
                "format": result.format,
                "filename": path.name,
                "content_base64": base64.b64encode(
                    path.read_bytes()
                ).decode("ascii"),
            }

        return result.model_dump()

    except Exception as exc:
        logger.exception("Design export failed for project %s", project_id)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Export failed: {exc}"},
        )


# ---------------------------------------------------------------------------
# POST/GET/DELETE /design/projects/:project_id/source — data source binding
# ---------------------------------------------------------------------------


@router.post("/projects/{project_id}/source")
async def bind_source(project_id: str, req: BindSourceRequest):  # noqa: PLR0911
    """Bind a data source (xlsx/csv/json) to a design project."""
    from backend.design.live_artifact import LiveArtifactEngine

    studio = _require_studio()
    try:
        studio.get_project(project_id)
    except DesignProjectNotFoundError as exc:
        return _map_design_error(exc)

    try:
        conn = get_database().get_connection()
        source_path = resolve_source_input(conn, req.file_path, req.doc_id)
    except OfficeSourceNotFoundError as exc:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Office document not found: {exc.doc_id}"},
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    engine = LiveArtifactEngine(studio._workspace)
    try:
        binding = engine.bind(
            project_id,
            str(source_path),
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
