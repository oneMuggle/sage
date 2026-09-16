"""Model catalog HTTP API routes.

Routes are mounted at ``/api/v1/model-catalog`` and require local auth.

All endpoints delegate persistence to :class:`CatalogRepository`; this module
handles HTTP concerns only: validation, status codes, error mapping, and the
bounded outbound fetch for OpenRouter sync.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ValidationError

from backend.api.local_auth import require_local_auth
from backend.api.upstream_security import (
    client_for_resolved_address,
    read_response_body_limited,
    resolve_and_validate_upstream_host,
)
from backend.data.settings_repo import SettingsRepository
from backend.model_catalog.repository import CatalogRepository
from backend.model_catalog.schemas import CandidateModel, EndpointKey
from backend.model_catalog.snapshots import CatalogConflict, CatalogNotFoundError
from backend.model_catalog.sources import map_openrouter
from backend.model_catalog.transfer import (
    BundleValidationError,
    decode_bundle,
    encode_bundle,
)

logger = logging.getLogger(__name__)

_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
_OPENROUTER_TIMEOUT = 30.0
_OPENROUTER_MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MiB
_MAX_PAGE_LIMIT = 100
_MAX_IMPORT_BYTES = 10 * 1024 * 1024  # 10 MiB


def build_router(repo: Optional[CatalogRepository] = None) -> APIRouter:
    """Build the model-catalog APIRouter, optionally injecting a repository.

    When ``repo`` is ``None`` the router reads ``request.app.state.catalog_repo``
    at request time (the normal production path).
    """
    router = APIRouter()

    def _repo(request: Request) -> CatalogRepository:
        if repo is not None:
            return repo
        stored = getattr(request.app.state, "catalog_repo", None)
        if stored is None:
            raise HTTPException(status_code=503, detail="catalog repository unavailable")
        return stored

    # ---- GET /models ---------------------------------------------------

    @router.get("/models")
    async def list_models(
        request: Request,
        limit: int = Query(default=50, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        endpoint_id: Optional[str] = Query(default=None),
    ):
        require_local_auth(request)
        repository = _repo(request)
        effective_limit = min(limit, _MAX_PAGE_LIMIT)
        with _read_lock(repository):
            conn = repository.db.get_connection()
            if endpoint_id:
                catalog_filter = _endpoint_catalog_filter(repository, endpoint_id)
                count_query = (
                    "SELECT COUNT(*) FROM model_catalog_entries e "
                    f"WHERE {catalog_filter.sql}"
                )
                rows_query = (
                    "SELECT e.data FROM model_catalog_entries e "
                    f"WHERE {catalog_filter.sql} "
                    "ORDER BY e.updated_at DESC LIMIT ? OFFSET ?"
                )
                total = conn.execute(
                    count_query, catalog_filter.parameters
                ).fetchone()[0]
                rows = conn.execute(
                    rows_query,
                    (*catalog_filter.parameters, effective_limit, offset),
                ).fetchall()
            else:
                total = conn.execute(
                    "SELECT COUNT(*) FROM model_catalog_entries"
                ).fetchone()[0]
                rows = conn.execute(
                    "SELECT data FROM model_catalog_entries ORDER BY updated_at DESC "
                    "LIMIT ? OFFSET ?",
                    (effective_limit, offset),
                ).fetchall()
        items = [CandidateModel.model_validate_json(r["data"]) for r in rows]
        return {
            "items": [i.model_dump(mode="json") for i in items],
            "total": total,
            "limit": effective_limit,
            "offset": offset,
        }

    # ---- GET /effective ------------------------------------------------

    @router.get("/effective")
    async def get_effective(
        request: Request,
        endpoint_id: str = Query(...),
        model_id: str = Query(...),
    ):
        require_local_auth(request)
        repository = _repo(request)
        endpoint = EndpointKey(endpoint_id=endpoint_id, model_id=model_id)
        result = repository.resolve(endpoint)
        return result.model_dump(mode="json")

    # ---- PUT /overrides ------------------------------------------------

    class OverrideRequest(BaseModel):
        endpoint_id: str
        model_id: str
        patch: dict
        expected_revision: int = 0

    @router.put("/overrides")
    async def put_override(request: Request):
        require_local_auth(request)
        repository = _repo(request)
        try:
            body = OverrideRequest.model_validate(await request.json())
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        endpoint = EndpointKey(endpoint_id=body.endpoint_id, model_id=body.model_id)
        try:
            revision = repository.set_override(
                endpoint, body.patch, body.expected_revision
            )
        except CatalogConflict:
            raise HTTPException(status_code=409, detail="override revision changed")
        except (ValidationError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {"revision": revision}

    # ---- DELETE /overrides -----------------------------------------------

    @router.delete("/overrides")
    async def delete_override(
        request: Request,
        endpoint_id: str = Query(...),
        model_id: str = Query(...),
        expected_revision: int = Query(...),
    ):
        """Delete a user override, restoring inherited values from lower layers."""
        require_local_auth(request)
        repository = _repo(request)
        endpoint = EndpointKey(endpoint_id=endpoint_id, model_id=model_id)
        try:
            revision = repository.delete_override(endpoint, expected_revision)
        except CatalogNotFoundError:
            raise HTTPException(status_code=404, detail="override not found")
        except CatalogConflict:
            raise HTTPException(status_code=409, detail="override revision changed")
        return {"revision": revision}

    # ---- POST /snapshots/import ----------------------------------------

    @router.post("/snapshots/import")
    async def import_snapshot(request: Request):
        require_local_auth(request)
        repository = _repo(request)
        raw = await _read_body_limited(request, _MAX_IMPORT_BYTES)
        try:
            records = decode_bundle(raw)
        except BundleValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        source = records[0].source if records else "custom_json"
        snapshot_id = repository.stage(records, source)
        return {"snapshot_id": snapshot_id, "count": len(records)}

    # ---- GET /snapshots ------------------------------------------------

    @router.get("/snapshots")
    async def list_snapshots(request: Request):
        require_local_auth(request)
        repository = _repo(request)
        with _read_lock(repository):
            rows = repository.db.get_connection().execute(
                "SELECT id, source, digest, created_at FROM model_catalog_snapshots "
                "ORDER BY created_at DESC"
            ).fetchall()
        return [
            {
                "id": r["id"],
                "source": r["source"],
                "digest": r["digest"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    # ---- GET /snapshots/{id}/diff --------------------------------------

    @router.get("/snapshots/{snapshot_id}/diff")
    async def get_diff(request: Request, snapshot_id: str):
        require_local_auth(request)
        repository = _repo(request)
        try:
            items = repository.diff(snapshot_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="snapshot not found")
        return [item.model_dump(mode="json") for item in items]

    # ---- POST /snapshots/{id}/items/{item}/apply -----------------------

    class ApplyRequest(BaseModel):
        fields: list[str]
        expected_revision: int

    @router.post("/snapshots/{snapshot_id}/items/{item_id}/apply")
    async def apply_item(request: Request, snapshot_id: str, item_id: str):
        require_local_auth(request)
        repository = _repo(request)
        try:
            body = ApplyRequest.model_validate(await request.json())
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        try:
            repository.apply(
                snapshot_id, item_id, body.fields, body.expected_revision
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="snapshot item not found")
        except CatalogConflict:
            raise HTTPException(
                status_code=409, detail="snapshot item or source revision changed"
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {"status": "applied"}

    # ---- POST /snapshots/{id}/items/{item}/ignore ----------------------

    @router.post("/snapshots/{snapshot_id}/items/{item_id}/ignore")
    async def ignore_item(request: Request, snapshot_id: str, item_id: str):
        require_local_auth(request)
        repository = _repo(request)
        try:
            repository.ignore(snapshot_id, item_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="snapshot item not found")
        except CatalogConflict:
            raise HTTPException(
                status_code=409, detail="snapshot item is already reviewed"
            )
        return {"status": "ignored"}

    # ---- GET /snapshots/{id}/export ------------------------------------

    @router.get("/snapshots/{snapshot_id}/export")
    async def export_snapshot(request: Request, snapshot_id: str):
        require_local_auth(request)
        repository = _repo(request)
        try:
            items = repository.diff(snapshot_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="snapshot not found")
        candidates = [item.after for item in items]
        source = candidates[0].source if candidates else "export"
        raw = encode_bundle(candidates, source)
        return json.loads(raw)

    # ---- POST /sync/openrouter -----------------------------------------

    @router.post("/sync/openrouter")
    async def sync_openrouter(request: Request):
        require_local_auth(request)
        repository = _repo(request)
        try:
            data = await _fetch_openrouter()
        except Exception as exc:
            logger.warning("OpenRouter sync failed: %s", exc)
            raise HTTPException(status_code=502, detail="upstream request failed")
        records = map_openrouter(data)
        if not records:
            return {"snapshot_id": None, "count": 0}
        snapshot_id = repository.stage(records, "openrouter")
        return {"snapshot_id": snapshot_id, "count": len(records)}

    # ---- POST /probe ---------------------------------------------------

    class ProbeRequest(BaseModel):
        endpoint_id: str
        model_id: str

    @router.post("/probe")
    async def probe_model(request: Request):
        """Probe an endpoint for model metadata.

        Reads endpoint configuration from settings, calls the service-specific
        metadata path, and persists the result via repository.save_probe().
        """
        require_local_auth(request)
        repository = _repo(request)
        try:
            body = ProbeRequest.model_validate(await request.json())
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        from backend.model_catalog.probes import (
            load_endpoint_config,
            probe_endpoint_from_settings,
        )

        result = await probe_endpoint_from_settings(body.endpoint_id, body.model_id)
        # Extract base_url from config for staleness detection
        config = load_endpoint_config(body.endpoint_id)
        base_url = (config.get("baseUrl") or config.get("base_url") or "") if config else ""
        # Persist the probe result (only success writes effective data)
        endpoint = EndpointKey(
            endpoint_id=body.endpoint_id, model_id=body.model_id
        )
        patch = result.data if result.status == "success" else {}
        repository.save_probe(
            endpoint,
            patch,
            adapter=result.adapter,
            status=result.status,
            error=result.error,
            base_url=base_url or None,
        )
        return result.model_dump()

    return router


@dataclass(frozen=True)
class _CatalogFilter:
    sql: str
    parameters: tuple[str, ...]


def _endpoint_catalog_filter(repository: CatalogRepository, endpoint_id: str) -> _CatalogFilter:
    """Build one endpoint filter from explicit bindings and persisted discovery.

    Explicit bindings are authoritative for the corresponding endpoint model ID.
    Discovery is only used when one provider and pricing scope can be determined
    from the catalog; ambiguous bare IDs are deliberately excluded.
    """
    conn = repository.db.get_connection()
    bindings = conn.execute(
        "SELECT model_id, provider, catalog_model_id, pricing_scope "
        "FROM model_catalog_bindings WHERE endpoint_id=?",
        (endpoint_id,),
    ).fetchall()
    clauses: list[str] = []
    parameters: list[str] = []
    if bindings:
        return _CatalogFilter(
            sql=(
                "EXISTS (SELECT 1 FROM model_catalog_bindings b "
                "WHERE b.endpoint_id=? AND e.provider=b.provider "
                "AND e.model_id=b.catalog_model_id "
                "AND e.pricing_scope=b.pricing_scope)"
            ),
            parameters=(endpoint_id,),
        )

    settings = SettingsRepository(repository.db).get_json("app_settings")
    discovered: list[str] = []
    if isinstance(settings, dict):
        endpoints = settings.get("endpoints")
        if isinstance(endpoints, list):
            endpoint = next(
                (
                    value
                    for value in endpoints
                    if isinstance(value, dict) and value.get("id") == endpoint_id
                ),
                None,
            )
            models = endpoint.get("discoveredModels") if isinstance(endpoint, dict) else None
            if isinstance(models, list):
                discovered = [
                    value["id"]
                    for value in models
                    if isinstance(value, dict)
                    and isinstance(value.get("id"), str)
                    and value["id"].strip()
                ]

    explicit_model_ids = {row["model_id"] for row in bindings}
    catalog_keys = conn.execute(
        "SELECT DISTINCT provider, model_id, pricing_scope "
        "FROM model_catalog_entries"
    ).fetchall()
    catalog_by_model: dict[str, set[tuple[str, str]]] = {}
    for row in catalog_keys:
        catalog_by_model.setdefault(row["model_id"], set()).add(
            (row["provider"], row["pricing_scope"])
        )

    derived: set[tuple[str, str, str]] = set()
    for raw_id in discovered:
        if raw_id in explicit_model_ids:
            continue
        if "/" in raw_id:
            provider, model_id = raw_id.split("/", 1)
            candidates = {
                (candidate_provider, pricing_scope)
                for candidate_provider, pricing_scope in catalog_by_model.get(model_id, set())
                if candidate_provider == provider and model_id
            }
        else:
            model_id = raw_id
            candidates = catalog_by_model.get(model_id, set())
        if len(candidates) != 1:
            continue
        provider, pricing_scope = next(iter(candidates))
        derived.add((provider, model_id, pricing_scope))

    for provider, model_id, pricing_scope in sorted(derived):
        clauses.append(
            "(e.provider=? AND e.model_id=? AND e.pricing_scope=?)"
        )
        parameters.extend((provider, model_id, pricing_scope))

    return _CatalogFilter(
        sql=" OR ".join(clauses) if clauses else "0",
        parameters=tuple(parameters),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_lock(repository: CatalogRepository):
    """Acquire the SQLite read lock without starting a write transaction."""
    from backend.data.database import _SQLITE_LOCK

    return _SQLITE_LOCK


async def _read_body_limited(request: Request, max_bytes: int) -> bytes:
    """Read the request body with a size cap, raising 413 when exceeded."""
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > max_bytes:
                raise HTTPException(status_code=413, detail="payload too large")
        except ValueError:
            pass
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail="payload too large")
        chunks.append(chunk)
    return b"".join(chunks)


async def _fetch_openrouter() -> dict:
    """Fetch the OpenRouter models list with DNS validation and bounded response.

    Uses shared security helpers to prevent SSRF, DNS rebinding, and memory
    exhaustion attacks. The response is capped at
    ``_OPENROUTER_MAX_RESPONSE_BYTES`` via streaming read.
    """
    from urllib.parse import urlparse

    parsed = urlparse(_OPENROUTER_MODELS_URL)
    # Resolve DNS and validate the target is not a private/loopback address
    pinned_address = await resolve_and_validate_upstream_host(parsed)
    # Create a client pinned to the resolved IP (prevents DNS rebinding)
    client = client_for_resolved_address(pinned_address, _OPENROUTER_TIMEOUT)
    try:
        response = await client.get(_OPENROUTER_MODELS_URL)
        response.raise_for_status()
        # Read the response with a hard cap via streaming
        body = await read_response_body_limited(
            response, _OPENROUTER_MAX_RESPONSE_BYTES
        )
        return json.loads(body)
    finally:
        await client.aclose()
