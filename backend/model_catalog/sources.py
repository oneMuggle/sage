"""External data-source mappers: convert upstream API shapes to CandidateModel.

Each mapper is a pure function — no networking, no side effects.  Callers are
responsible for fetching data (with safety guards) and passing the parsed JSON.

OpenRouter schema (verified 2026-09-15 from official docs):

- Endpoint: GET /api/v1/models
- Response: {"data": [Model, ...]}
- Model object has: id (string like "openai/gpt-4o"), context_length (number),
  pricing.prompt (string, USD per token), pricing.completion (string, USD per
  token), architecture (object), created (Unix timestamp).
- Prices are per-token *strings*; "0" means free; negative values are not free.
- Multiply by 1_000_000 to get per-million Decimal.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from .schemas import CandidateModel, ModelKey, Price

_OPENROUTER_SOURCE = "openrouter"
_OPENROUTER_PRICING_SCOPE = "openrouter"
_PER_MILLION = Decimal("1000000")


def _utc_now_z() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _split_model_id(raw_id: str) -> ModelKey:
    """OpenRouter ids are ``provider/slug``; missing slash → provider='openrouter'."""
    if "/" in raw_id:
        provider, _, model_id = raw_id.partition("/")
        return ModelKey(provider=provider or _OPENROUTER_SOURCE, model_id=model_id or raw_id)
    return ModelKey(provider=_OPENROUTER_SOURCE, model_id=raw_id)


def _price_per_million(raw) -> Decimal | None:
    """Convert a per-token string to per-million Decimal.

    None / empty → unknown (None).  Negative → unknown (not free).
    "0" → Decimal(0) — a known free rate, distinct from unknown.
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        raw = str(raw)
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    if value < 0:
        return None
    return value * _PER_MILLION


def map_openrouter(data: dict) -> list[CandidateModel]:
    """Convert OpenRouter /api/v1/models response to CandidateModel records.

    Missing prices stay unknown (None), not zero.  pricing_scope='openrouter'.
    """
    if data is None or not isinstance(data, dict):
        raise TypeError("OpenRouter data must be a dict")

    models = data.get("data") or []
    if not isinstance(models, list):
        raise TypeError("OpenRouter data.data must be a list")

    timestamp = _utc_now_z()
    results: list[CandidateModel] = []
    for model in models:
        if not isinstance(model, dict):
            continue
        model_id_raw = model.get("id")
        if not isinstance(model_id_raw, str) or not model_id_raw.strip():
            continue

        pricing = model.get("pricing") or {}
        if not isinstance(pricing, dict):
            pricing = {}

        context_length = model.get("context_length")
        native = context_length if isinstance(context_length, int) and context_length > 0 else None

        results.append(
            CandidateModel(
                model_key=_split_model_id(model_id_raw),
                native=native,
                price=Price(
                    input_per_million=_price_per_million(pricing.get("prompt")),
                    output_per_million=_price_per_million(pricing.get("completion")),
                ),
                source=_OPENROUTER_SOURCE,
                source_updated_at=timestamp,
                pricing_scope=_OPENROUTER_PRICING_SCOPE,
            )
        )
    return results
