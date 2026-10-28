"""Reconcile endpoint-discovered models into catalog bindings.

Routing candidates come from ``model_catalog_bindings``; discovery is the only
place that knows which models an endpoint actually serves.  This module binds a
discovered id to an existing catalog entry only when the catalog resolves it to
a single (provider, pricing_scope) -- never inventing providers (ambiguous bare
ids stay unbound, mirroring ``_endpoint_catalog_filter``'s policy).

Task 12 (2026-10-28): this is the production caller that gives ``bind()``
actual bindings, so ``RoutingEngine`` has candidates on a real install.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.data.database import _SQLITE_LOCK
from backend.model_catalog.repository import CatalogRepository
from backend.model_catalog.schemas import EndpointKey, ModelKey

logger = logging.getLogger(__name__)

# Binding target layout — provider, catalog_model_id, pricing_scope.
BindingTarget = Tuple[str, str, str]


class _CatalogIndex:
    """In-memory snapshot of the catalog's (provider, model_id, pricing_scope) keys."""

    def __init__(self, rows: List[Any]) -> None:
        self._exact: Dict[str, Set[Tuple[str, str]]] = {}
        self._rows: List[Tuple[str, str, str]] = []
        for row in rows:
            provider = row["provider"]
            model_id = row["model_id"]
            pricing_scope = row["pricing_scope"]
            self._exact.setdefault(model_id, set()).add((provider, pricing_scope))
            self._rows.append((provider, model_id, pricing_scope))

    def resolve(self, discovered_id: str) -> Optional[BindingTarget]:
        """Resolve a discovered id to exactly one catalog target, or ``None``.

        Rule 1 (R34b): exact ``model_id == discovered_id`` with exactly one
        distinct ``(provider, pricing_scope)`` pair.
        Rule 2 (R34b): suffix form ``model_id`` ending with
        ``"/" + discovered_id`` with exactly one distinct
        ``(provider, pricing_scope, model_id)`` triple.
        Zero or multiple candidates stay unbound -- the provider is never
        guessed from the endpoint id.
        """
        exact = self._exact.get(discovered_id)
        if exact is not None and len(exact) == 1:
            provider, pricing_scope = next(iter(exact))
            return (provider, discovered_id, pricing_scope)

        suffix = "/" + discovered_id
        suffixed = {
            (provider, model_id, pricing_scope)
            for provider, model_id, pricing_scope in self._rows
            if model_id.endswith(suffix)
        }
        if len(suffixed) == 1:
            return next(iter(suffixed))
        return None


def _catalog_index(repo: CatalogRepository) -> _CatalogIndex:
    with _SQLITE_LOCK:
        rows = repo.db.get_connection().execute(
            "SELECT DISTINCT provider, model_id, pricing_scope "
            "FROM model_catalog_entries"
        ).fetchall()
    return _CatalogIndex(rows)


def _discovered_ids(endpoint: Dict[str, Any]) -> List[str]:
    """Extract non-blank discovered model ids; malformed entries are ignored."""
    models = endpoint.get("discoveredModels")
    if not isinstance(models, list):
        return []
    ids: List[str] = []
    for model in models:
        if not isinstance(model, dict):
            continue
        model_id = model.get("id")
        if isinstance(model_id, str) and model_id.strip():
            ids.append(model_id)
    return ids


def reconcile_endpoint_bindings(
    repo: CatalogRepository,
    settings: Any,
    endpoint_id: Optional[str] = None,
) -> Dict[str, int]:
    """Bind discovered endpoint models to existing catalog entries.

    ``endpoint_id`` restricts processing to one endpoint; ``None`` means every
    endpoint in ``settings["endpoints"]``.

    Returns ``{"bound": int, "skipped": int}``.  Never raises on malformed
    settings; discovered ids with no unique catalog target are counted as
    ``skipped`` (no catalog entries are created, no providers invented).
    """
    stats = {"bound": 0, "skipped": 0}
    if not isinstance(settings, dict):
        return stats
    endpoints = settings.get("endpoints")
    if not isinstance(endpoints, list):
        return stats

    wanted = (
        endpoint_id
        if isinstance(endpoint_id, str) and endpoint_id.strip()
        else None
    )
    index: Optional[_CatalogIndex] = None

    for endpoint in endpoints:
        if not isinstance(endpoint, dict):
            continue
        ep_id = endpoint.get("id")
        if not isinstance(ep_id, str) or not ep_id.strip():
            continue
        if wanted is not None and ep_id != wanted:
            continue
        discovered = _discovered_ids(endpoint)
        if not discovered:
            continue
        if index is None:
            index = _catalog_index(repo)
        for model_id in discovered:
            target = index.resolve(model_id)
            if target is None:
                stats["skipped"] += 1
                logger.debug(
                    "catalog discovery: no unique entry for %r on endpoint %s",
                    model_id,
                    ep_id,
                )
                continue
            provider, catalog_model_id, pricing_scope = target
            try:
                repo.bind(
                    EndpointKey(endpoint_id=ep_id, model_id=model_id),
                    ModelKey(provider=provider, model_id=catalog_model_id),
                    pricing_scope,
                )
            except Exception:
                stats["skipped"] += 1
                logger.debug(
                    "catalog discovery: bind failed for %r on endpoint %s",
                    model_id,
                    ep_id,
                    exc_info=True,
                )
                continue
            stats["bound"] += 1
            logger.debug(
                "catalog discovery: bound %r -> %s/%s on endpoint %s",
                model_id,
                provider,
                catalog_model_id,
                ep_id,
            )
    return stats
