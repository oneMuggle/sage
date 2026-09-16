"""Load builtin seed data into the model catalog on startup.

Reads ``backend/builtin.json`` and stages records if ``model_catalog_entries``
is empty. No network access. Idempotent — calling on a populated catalog
is a no-op.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List

from .repository import CatalogRepository
from .schemas import CandidateModel, ModelKey, Price

logger = logging.getLogger(__name__)

_BUILTIN_JSON_PATH = Path(__file__).parent.parent / "builtin.json"
_BUILTIN_SOURCE = "builtin"
_BUILTIN_PRICING_SCOPE_SELF_HOSTED = "self-hosted"


def _count_entries(repo: CatalogRepository) -> int:
    """Return the number of entries in the catalog."""
    from backend.data.database import _SQLITE_LOCK

    with _SQLITE_LOCK:
        row = repo.db.get_connection().execute(
            "SELECT COUNT(*) FROM model_catalog_entries"
        ).fetchone()
        return row[0] if row else 0


def _parse_builtin_json(raw: str) -> List[CandidateModel]:
    """Parse builtin.json into CandidateModel records.

    Pure function — no I/O, no side effects.
    """
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("builtin.json root must be a dict")
    models = data.get("models") or []
    if not isinstance(models, list):
        raise ValueError("builtin.json 'models' must be a list")
    timestamp = data.get("generated_at")
    records: List[CandidateModel] = []
    for model in models:
        if not isinstance(model, dict):
            continue
        provider = model.get("provider")
        model_id = model.get("model_id")
        if not provider or not model_id:
            continue
        native = model.get("native")
        if not isinstance(native, int) or native <= 0:
            native = None
        price_data = model.get("price") or {}
        pricing_scope = (
            model.get("pricing_scope") or _BUILTIN_PRICING_SCOPE_SELF_HOSTED
        )
        # Per-model source_updated_at preferred; fall back to top-level generated_at
        per_model_ts = model.get("source_updated_at")
        effective_ts = (
            per_model_ts
            if isinstance(per_model_ts, str) and per_model_ts
            else (timestamp if isinstance(timestamp, str) else None)
        )
        records.append(
            CandidateModel(
                model_key=ModelKey(
                    provider=str(provider), model_id=str(model_id)
                ),
                native=native,
                price=Price(
                    input_per_million=price_data.get("input_per_million"),
                    output_per_million=price_data.get("output_per_million"),
                ),
                source=_BUILTIN_SOURCE,
                source_updated_at=effective_ts,
                pricing_scope=str(pricing_scope),
            )
        )
    return records


def seed_if_empty(repo: CatalogRepository) -> int:
    """Load builtin seed data if the catalog is empty.

    Returns the number of records loaded, or 0 if catalog was already
    populated or builtin.json was not found.
    """
    if _count_entries(repo) > 0:
        return 0
    if not _BUILTIN_JSON_PATH.exists():
        logger.debug("builtin.json not found at %s", _BUILTIN_JSON_PATH)
        return 0
    try:
        raw = _BUILTIN_JSON_PATH.read_text(encoding="utf-8")
        records = _parse_builtin_json(raw)
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        logger.warning("Failed to load builtin.json: %s", exc)
        return 0
    if not records:
        return 0
    snapshot_id = repo.stage(records, _BUILTIN_SOURCE)
    # Auto-apply all items from the builtin snapshot
    items = repo.diff(snapshot_id)
    from .snapshots import FIELDS

    for item in items:
        try:
            repo.apply(
                snapshot_id,
                item.id,
                list(FIELDS),
                item.base_revision,
            )
        except Exception as exc:
            logger.warning("Failed to apply builtin item %s: %s", item.id, exc)
    logger.info("Loaded %d builtin seed records", len(records))
    return len(records)
