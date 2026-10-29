"""Default workspace endpoints (2026-10-29, P1).

Session-scoped workspace binding lives in :mod:`backend.api.workspace_routes`
(``/sessions/{session_id}/workspace``). This module covers the *default*
workspace: which directory a new session should work in, and the user's
remembered preference for it.

Endpoints:

- ``GET    /workspace/default``    resolve the default workspace (read-only)
- ``POST   /workspace/preference`` remember an explicitly chosen directory
- ``DELETE /workspace/preference`` forget the remembered directory
- ``POST   /workspace/migrate``    import a legacy localStorage value

The decision chain itself lives in
:mod:`backend.services.default_workspace` — this module is a thin HTTP shell
around it, so the renderer never re-derives the answer on its own.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.data.database import make_with_db_lock
from backend.office.errors import OfficePathError
from backend.services.default_workspace import DefaultWorkspaceResolver
from backend.services.workspace_health import WorkspaceHealthChecker
from backend.services.workspace_migration import migrate_last_workspace

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspace", tags=["workspace-default"])

with_db_lock = make_with_db_lock(globals())


class WorkspaceDefaultResponse(BaseModel):
    """Resolved default workspace plus its provenance."""

    path: Optional[str] = None
    source: Optional[str] = None
    is_fallback: bool = False


class WorkspacePreferenceRequest(BaseModel):
    """Body of ``POST /workspace/preference``."""

    path: str = Field(min_length=1)


class WorkspacePreferenceResponse(BaseModel):
    """Result of a preference write/forget."""

    path: Optional[str] = None
    stored: bool = False


class WorkspaceMigrateRequest(BaseModel):
    """Body of ``POST /workspace/migrate`` — the legacy localStorage value."""

    path: Optional[str] = None


class WorkspaceMigrateResponse(BaseModel):
    """Outcome of a legacy-value migration."""

    outcome: str
    path: Optional[str] = None
    reason: Optional[str] = None


class WorkspaceHealthResponse(BaseModel):
    """Whether a workspace directory is still usable."""

    path: Optional[str] = None
    health: Optional[str] = None
    detail: Optional[str] = None
    writable: bool = False
    is_usable: bool = False


@router.get("/default", response_model=WorkspaceDefaultResponse)
@with_db_lock
def get_default_workspace(
    session_id: Optional[str] = Query(default=None),
    detected_root: Optional[str] = Query(default=None),
) -> WorkspaceDefaultResponse:
    """Resolve the default workspace without binding anything."""
    resolver = DefaultWorkspaceResolver()
    resolution = resolver.resolve_default_workspace(
        session_id=session_id,
        detected_root=detected_root,
    )
    if resolution is None:
        return WorkspaceDefaultResponse()
    return WorkspaceDefaultResponse(
        path=resolution.path,
        source=resolution.source.value,
        is_fallback=resolution.is_fallback,
    )


@router.post("/preference", response_model=WorkspacePreferenceResponse)
@with_db_lock
def set_workspace_preference(
    request: WorkspacePreferenceRequest,
) -> WorkspacePreferenceResponse:
    """Remember an explicitly chosen directory as the user's preference."""
    resolver = DefaultWorkspaceResolver()
    try:
        canonical = resolver.remember_workspace(request.path)
    except OfficePathError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_workspace_path", "message": str(exc)},
        ) from exc
    return WorkspacePreferenceResponse(path=canonical, stored=True)


@router.delete("/preference", response_model=WorkspacePreferenceResponse)
@with_db_lock
def clear_workspace_preference() -> WorkspacePreferenceResponse:
    """Forget the remembered directory so the next resolution falls back."""
    DefaultWorkspaceResolver().forget_workspace()
    return WorkspacePreferenceResponse(stored=False)


@router.post("/migrate", response_model=WorkspaceMigrateResponse)
@with_db_lock
def migrate_workspace_preference(
    request: WorkspaceMigrateRequest,
) -> WorkspaceMigrateResponse:
    """Import a legacy localStorage value into the preferences table.

    The renderer reads localStorage (the backend cannot) and calls this once
    per startup, then drops the legacy key when the outcome is ``migrated``
    or ``already_present``.
    """
    result = migrate_last_workspace(request.path)
    return WorkspaceMigrateResponse(
        outcome=result.outcome.value,
        path=result.path,
        reason=result.reason,
    )


@router.get("/health", response_model=WorkspaceHealthResponse)
def get_workspace_health(
    path: str = Query(..., min_length=1),
) -> WorkspaceHealthResponse:
    """Report whether a workspace directory is still usable.

    Read-only probe — it never creates or repairs anything, so the UI can
    surface the verdict without changing the user's filesystem.
    """
    status = WorkspaceHealthChecker().check(path)
    return WorkspaceHealthResponse(
        path=status.path,
        health=status.health.value,
        detail=status.detail,
        writable=status.writable,
        is_usable=status.is_usable,
    )
