"""Design resource routes — Word outline extraction and chart embedding.

Split out of ``design_routes.py`` to keep that module under the 800-line
architecture ratchet. Shares the ``/design`` prefix and path contract with
the main design router.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from backend.api.v1.design_source_models import (
    OutlineRequest,
    SourcePreviewRequest,
)
from backend.data.database import get_database
from backend.design import get_design_studio
from backend.design.errors import (
    DesignError,
    DesignProjectNotFoundError,
    DesignSystemNotFoundError,
    DesignTemplateKindMismatchError,
    DesignTemplateNotFoundError,
)
from backend.design.office_sources import (
    OfficeSourceNotFoundError,
    list_office_sources,
    resolve_source_input,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/design", tags=["design"])


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class EmbedChartRequest(BaseModel):
    """POST /design/projects/{id}/chart body."""

    model_config = ConfigDict(extra="forbid")

    chart: dict
    slot: str = "{{CHART}}"


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
    status = (
        400 if isinstance(exc, DesignTemplateKindMismatchError)
        else 404 if isinstance(exc, not_found)  # noqa: UP038 — py38 兼容
        else 500
    )
    return JSONResponse(status_code=status, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# POST /design/outline — Word → markdown outline
# ---------------------------------------------------------------------------


@router.post("/outline")
async def extract_outline(req: OutlineRequest):
    """Extract a Word document into a slide-style markdown outline.

    Returns the OutlineResult (title, slide_count, outline_md) so the
    create composer can feed it into the project brief without a second
    LLM round-trip.
    """

    from backend.design.outline_extractor import OutlineExtractor

    try:
        conn = get_database().get_connection()
        path = resolve_source_input(conn, req.file_path, req.doc_id)
    except OfficeSourceNotFoundError as exc:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Office document not found: {exc.doc_id}"},
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    if not path.is_file():
        return JSONResponse(
            status_code=404,
            content={"detail": f"File not found: {path}"},
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
        logger.exception("Outline extraction failed for %s", path)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Outline extraction failed: {exc}"},
        )


# ---------------------------------------------------------------------------
# POST /design/source/preview — inspect a data source before binding
# ---------------------------------------------------------------------------


@router.post("/source/preview")
async def preview_source(req: SourcePreviewRequest):  # noqa: PLR0911
    """Parse an xlsx/csv/json file and return a compact preview.

    Lets the UI show columns and row counts before the user commits to a
    data-source binding (avoids a wasted refresh on the wrong file).
    """

    try:
        conn = get_database().get_connection()
        path = resolve_source_input(conn, req.file_path, req.doc_id)
    except OfficeSourceNotFoundError as exc:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Office document not found: {exc.doc_id}"},
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    if not path.is_file():
        return JSONResponse(
            status_code=404,
            content={"detail": f"File not found: {path}"},
        )

    ext = path.suffix.lower()
    try:
        if ext in (".xlsx", ".xls", ".csv"):
            if ext == ".csv":
                from backend.office.excel import read_csv

                result = read_csv(path)
            else:
                from backend.office.excel import read_xlsx

                result = read_xlsx(path)
            sheets = []
            for sheet in result.sheets:
                rows = sheet.rows or []
                header_row = rows[0] if rows else []
                headers = [
                    str(cell).strip() or f"col{index}"
                    for index, cell in enumerate(header_row, 1)
                ]
                sheets.append({
                    "name": sheet.name,
                    "row_count": max(len(rows) - 1, 0),
                    "columns": headers,
                    "sample": [
                        [str(cell) for cell in (row or [])]
                        for row in rows[1:6]
                    ],
                })
            return {"ok": True, "kind": ext.lstrip("."), "sheets": sheets}

        if ext == ".json":
            import json as _json

            data = _json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                columns = sorted({
                    key for item in data[:50]
                    if isinstance(item, dict)
                    for key in item
                })
                return {
                    "ok": True,
                    "kind": "json",
                    "sheets": [{
                        "name": "items",
                        "row_count": len(data),
                        "columns": columns,
                        "sample": [
                            list(item.values()) if isinstance(item, dict)
                            else [str(item)]
                            for item in data[:5]
                        ],
                    }],
                }
            if isinstance(data, dict):
                return {
                    "ok": True,
                    "kind": "json",
                    "sheets": [{
                        "name": "object",
                        "row_count": 1,
                        "columns": list(data.keys())[:20],
                        "sample": [],
                    }],
                }
            return JSONResponse(
                status_code=400,
                content={"detail": "Unsupported JSON shape"},
            )

        return JSONResponse(
            status_code=400,
            content={
                "detail": (
                    f"Unsupported extension {ext!r}; "
                    "use .xlsx/.csv/.json"
                ),
            },
        )
    except Exception as exc:
        logger.exception("Source preview failed for %s", path)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Source preview failed: {exc}"},
        )


# ---------------------------------------------------------------------------
# GET /design/office-sources — list Office docs available as design sources
# ---------------------------------------------------------------------------


@router.get("/office-sources")
async def get_office_sources(doc_type: Optional[str] = None):
    """List Office documents that can be referenced as design sources.

    Frontend uses this to populate the "从文档库选择" picker in the
    create composer (Word → outline) and resources panel (Excel → data
    source). Restricted to ``word`` / ``excel`` doc_types; other values
    yield an empty list.
    """
    if doc_type is not None and doc_type not in ("word", "excel"):
        return {"items": []}
    try:
        conn = get_database().get_connection()
        items = list_office_sources(conn, doc_type=doc_type)
    except Exception as exc:
        logger.exception("Listing office sources failed")
        return JSONResponse(
            status_code=500,
            content={"detail": f"Listing office sources failed: {exc}"},
        )
    return {"items": [item.model_dump() for item in items]}


# ---------------------------------------------------------------------------
# POST /design/projects/:project_id/chart — embed a chart (no LLM)
# ---------------------------------------------------------------------------


@router.post("/projects/{project_id}/chart")
async def embed_chart(project_id: str, req: EmbedChartRequest):
    """Render a chart and inject it into the latest artifact.

    Mirrors the ``design_embed_chart`` tool: renders the ChartSpec via
    matplotlib, injects a data-URL image at ``slot`` (or before ``</body>``),
    and appends a new artifact version without calling the LLM.
    """
    from backend.design.chart_embedder import DEFAULT_SLOT, ChartEmbedder
    from backend.office.models import ChartSpec

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

    try:
        spec = ChartSpec(**req.chart)
        embedder = ChartEmbedder()
        data_url = embedder.spec_to_data_url(spec)
        embedded = embedder.embed(
            latest.html_content, data_url, slot=req.slot or DEFAULT_SLOT,
        )
        artifact = studio.add_artifact(
            project_id, embedded.html, title=latest.title,
        )
        return {
            "ok": True,
            "artifact_id": artifact.id,
            "version": artifact.version,
            "title": artifact.title,
            "injected_at_slot": embedded.injected_at_slot,
        }
    except (ValueError, TypeError) as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    except Exception as exc:
        logger.exception("Chart embedding failed for %s", project_id)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Chart embedding failed: {exc}"},
        )
