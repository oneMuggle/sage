"""Design resource routes — Word outline extraction and chart embedding.

Split out of ``design_routes.py`` to keep that module under the 800-line
architecture ratchet. Shares the ``/design`` prefix and path contract with
the main design router.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.compat.win7.pydantic_compat import ConfigDict
from backend.design import get_design_studio
from backend.design.errors import (
    DesignError,
    DesignProjectNotFoundError,
    DesignSystemNotFoundError,
    DesignTemplateKindMismatchError,
    DesignTemplateNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/design", tags=["design"])


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class OutlineRequest(BaseModel):
    """POST /design/outline body."""

    model_config = ConfigDict(extra="forbid")

    file_path: str


class EmbedChartRequest(BaseModel):
    """POST /design/projects/{id}/chart body."""

    model_config = ConfigDict(extra="forbid")

    chart: dict
    slot: str = "{{CHART}}"


class SourcePreviewRequest(BaseModel):
    """POST /design/source/preview body."""

    model_config = ConfigDict(extra="forbid")

    file_path: str


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
# POST /design/source/preview — inspect a data source before binding
# ---------------------------------------------------------------------------


@router.post("/source/preview")
async def preview_source(req: SourcePreviewRequest):  # noqa: PLR0911
    """Parse an xlsx/csv/json file and return a compact preview.

    Lets the UI show columns and row counts before the user commits to a
    data-source binding (avoids a wasted refresh on the wrong file).
    """
    from pathlib import Path

    path = Path(req.file_path)
    if not path.exists():
        return JSONResponse(
            status_code=404,
            content={"detail": f"File not found: {req.file_path}"},
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
        logger.exception("Source preview failed for %s", req.file_path)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Source preview failed: {exc}"},
        )


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
