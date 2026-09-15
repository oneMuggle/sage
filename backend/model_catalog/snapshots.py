"""Pure snapshot field-selection helpers (no persistence or networking)."""

import hashlib
import json
from datetime import datetime, timezone

from .schemas import CandidateModel

FIELDS = (
    "native",
    "capabilities",
    "architecture",
    "quantization",
    "price.input_per_million",
    "price.output_per_million",
)


class CatalogConflict(Exception):  # noqa: N818 - public contract from the catalog spec
    """Stale revision or terminal review; API callers may map this to HTTP 409."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")  # noqa: UP017 - Python 3.10 runtime


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(records: list[CandidateModel]) -> str:
    return hashlib.sha256(
        canonical_json([r.model_dump(mode="json") for r in records]).encode()
    ).hexdigest()


def selected_fields(fields: list[str]) -> list[str]:
    expanded = [
        path
        for field in fields
        for path in (
            ("price.input_per_million", "price.output_per_million")
            if field == "price"
            else (field,)
        )
    ]
    if not expanded or any(field not in FIELDS for field in expanded):
        raise ValueError("select one or more catalog value fields")
    return list(dict.fromkeys(expanded))


def field_value(data: dict, path: str):
    if path.startswith("price."):
        return data.get("price", {}).get(path.split(".")[1])
    return data.get(path)


def merge_fields(
    before: CandidateModel | None,
    after: CandidateModel,
    fields: list[str],
    clear_fields: list[str] = (),
) -> CandidateModel:
    """Missing/null source fields never erase values; clears are internal rollback instructions."""
    old = before.model_dump(mode="json") if before else {}
    incoming = after.model_dump(mode="json")
    data = {**incoming, **old, "price": dict(old.get("price", {}))}
    for field in FIELDS:
        value = field_value(incoming, field)
        if field not in fields or (value is None and field not in clear_fields):
            if not before and not field.startswith("price."):
                data[field] = None
            continue
        if field.startswith("price."):
            data["price"][field.split(".")[1]] = value
        else:
            data[field] = value
    if "source_updated_at" in clear_fields:
        data["source_updated_at"] = None
    elif fields and after.source_updated_at is not None:
        data["source_updated_at"] = after.source_updated_at
    return CandidateModel.model_validate(data)
