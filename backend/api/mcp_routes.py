"""
MCP multi-server management REST API (M3).

Endpoints (mounted under ``/api/v1``):

- ``GET    /mcp/status``            — degraded-mode status report (always 200)
- ``GET    /mcp/servers``           — effective configs (env secrets redacted)
- ``POST   /mcp/servers``           — add user server + discover it
- ``PATCH  /mcp/servers/{name}``    — merge-patch enabled/timeout_seconds
- ``DELETE /mcp/servers/{name}``    — remove user entry (built-ins guarded)

pydantic models use the dual v1/v2 ``class Config`` style because the
release/win7 LTS branch pins pydantic 1.10 while main pins 2.x.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.mcp.client import McpClientError
from backend.mcp.config import McpConfigError, ServerConfig, validate_server_config
from backend.mcp.pool import McpServerPool, get_pool

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mcp"])

#: env keys containing any of these substrings (case-insensitive) are
#: redacted in GET responses — never echo secrets to the renderer.
#: Note "pat" also masks keys containing "path" (e.g. CHROME_PATH) —
#: acceptable: over-redaction of a non-secret beats leaking a PAT.
REDACT_KEY_MARKERS = (
    "key",
    "token",
    "secret",
    "password",
    "auth",
    "credential",
    "pat",
    "private",
)
REDACTED = "***"


# ---------- request / response models (pydantic v1/v2 dual-compat) ----------


class ServerConfigIn(BaseModel):
    """POST /mcp/servers body — full user server definition."""

    name: str = Field(min_length=1, max_length=64)
    command: str = Field(min_length=1, max_length=512)
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    required: bool = False
    timeout_seconds: float = Field(default=30.0, gt=0, le=600)

    class Config:
        extra = "forbid"


class ServerUpdateIn(BaseModel):
    """PATCH /mcp/servers/{name} body — merge-patch, all fields optional."""

    enabled: Optional[bool] = None
    timeout_seconds: Optional[float] = Field(default=None, gt=0, le=600)

    class Config:
        extra = "forbid"


# ---------- helpers -----------------------------------------------------------


def redact_env(env: Dict[str, str]) -> Dict[str, str]:
    """Mask env values whose key names look secret-bearing."""
    redacted: Dict[str, str] = {}
    for key, value in env.items():
        lowered = key.lower()
        if any(marker in lowered for marker in REDACT_KEY_MARKERS):
            redacted[key] = REDACTED
        else:
            redacted[key] = value
    return redacted


def _config_to_dict(config: ServerConfig, builtin: bool) -> Dict[str, Any]:
    data = config.to_dict()
    data["env"] = redact_env(config.env)
    # UI uses this to disable the delete button for built-in servers
    data["builtin"] = builtin
    return data


def _pool() -> McpServerPool:
    """Route entry: process-wide pool, lazily config-synced."""
    pool = get_pool()
    pool.ensure_synced()
    return pool


# ---------- routes ------------------------------------------------------------


@router.get("/mcp/status")
def mcp_status() -> Dict[str, Any]:
    """Status report across all configured servers. Always 200 — state
    travels in the body (degraded mode is not an HTTP error)."""
    return _pool().status_report().to_dict()


@router.get("/mcp/servers")
def list_mcp_servers() -> Dict[str, Any]:
    """Effective (built-in + user merged) configs, env secrets redacted."""
    from backend.mcp.config import builtin_names

    pool = _pool()
    builtins = set(builtin_names())
    servers = [
        _config_to_dict(c, builtin=c.name in builtins) for c in pool.effective_configs()
    ]
    return {"servers": servers}


@router.post("/mcp/servers")
def add_mcp_server(payload: ServerConfigIn) -> Dict[str, Any]:
    """Validate + persist a user server, then trigger discovery for it."""
    try:
        config = validate_server_config(
            name=payload.name,
            command=payload.command,
            args=tuple(payload.args),
            env=dict(payload.env),
            enabled=payload.enabled,
            required=payload.required,
            timeout_seconds=payload.timeout_seconds,
        )
        record = _pool().add_server(config)
    except (McpConfigError, McpClientError) as exc:
        # Contract: 400 {"error": ...} for semantic validation failures
        # (schema-level violations arrive as FastAPI's standard 422).
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except OSError as exc:
        logger.error("MCP config persistence failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"config save failed: {exc}")
    return {"ok": True, "name": config.name, "state": record.state.value}


@router.patch("/mcp/servers/{name}")
def update_mcp_server(name: str, payload: ServerUpdateIn) -> Dict[str, Any]:
    """Merge-patch enabled/timeout_seconds; starts or stops the server.

    Timeout semantics: the response timeout is baked into a live client
    at construction, so changing ``timeout_seconds`` on a RUNNING server
    triggers a re-discovery (the server is briefly restarted) — the new
    value takes effect immediately instead of being silently ignored
    until the next natural reconnect.
    """
    pool = _pool()
    try:
        record = pool.update_server(
            name,
            enabled=payload.enabled,
            timeout_seconds=payload.timeout_seconds,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown MCP server: {name}")
    except McpConfigError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except OSError as exc:
        logger.error("MCP config persistence failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"config save failed: {exc}")
    return {"ok": True, "name": name, "state": record.state.value}


@router.delete("/mcp/servers/{name}")
def delete_mcp_server(name: str) -> Dict[str, Any]:
    """Remove a user server entry + unregister its tools.

    Built-in servers (drawio) without a user override cannot be deleted.
    """
    try:
        _pool().remove_server(name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown MCP server: {name}")
    except McpClientError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except OSError as exc:
        logger.error("MCP config persistence failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"config save failed: {exc}")
    return {"ok": True, "name": name}
