"""Shared helpers for design route modules."""
from __future__ import annotations

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from backend.design import get_design_studio
from backend.design.errors import (
    DesignError,
    DesignProjectNotFoundError,
    DesignSystemNotFoundError,
    DesignTemplateKindMismatchError,
    DesignTemplateNotFoundError,
)


def require_studio():
    """Return the global DesignStudio or raise 404."""
    studio = get_design_studio()
    if studio is None:
        raise HTTPException(
            status_code=404,
            detail="Design studio not initialised",
        )
    return studio


def map_design_error(exc: DesignError) -> JSONResponse:
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
