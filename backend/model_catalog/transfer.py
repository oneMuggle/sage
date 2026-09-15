"""Bundle encode/decode for portable model-catalog transfer.

The bundle is a JSON envelope:

    {
        "formatVersion": 1,
        "payload": {
            "generatedAt": "<UTC RFC3339 ending in Z>",
            "source": "<nonblank string>",
            "records": [<CandidateModel JSON>, ...]
        },
        "sha256": "<hex digest of the canonical payload>"
    }

Hash the payload with ``json.dumps(payload, sort_keys=True, separators=(',', ':'),
ensure_ascii=False, allow_nan=False)`` encoded as UTF-8, then SHA-256.

Constraints:

- Maximum 10 000 records per bundle
- Maximum 10 MiB encoded size
- No duplicate candidate identities (provider + model_id + source + pricing_scope)
- Only ``formatVersion=1`` is accepted; unknown versions are rejected
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone

from pydantic import ValidationError

from .schemas import CandidateModel

FORMAT_VERSION = 1
MAX_RECORDS = 10_000
MAX_BUNDLE_BYTES = 10 * 1024 * 1024  # 10 MiB


class BundleValidationError(Exception):
    """Envelope or content constraint violated; callers map this to HTTP 422."""


def _identity_tuple(record: CandidateModel) -> tuple:
    return (
        record.model_key.provider,
        record.model_key.model_id,
        record.source,
        record.pricing_scope,
    )


def _utc_now_z() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _hash_payload(payload: dict) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def encode_bundle(records: list[CandidateModel], source: str) -> bytes:
    """Validate records, then return a signed bundle as UTF-8 bytes."""
    if not isinstance(source, str) or not source.strip():
        raise BundleValidationError("source must be a non-blank string")
    if not isinstance(records, list):
        raise BundleValidationError("records must be a list")

    if len(records) > MAX_RECORDS:
        raise BundleValidationError(
            f"bundle contains {len(records)} records (maximum {MAX_RECORDS})"
        )

    validated: list[CandidateModel] = []
    for record in records:
        if isinstance(record, CandidateModel):
            validated.append(record)
        else:
            try:
                validated.append(CandidateModel.model_validate(record))
            except ValidationError as exc:
                raise BundleValidationError(f"invalid candidate: {exc}") from exc

    for record in validated:
        if record.source != source:
            raise BundleValidationError(
                f"candidate source {record.source!r} does not match bundle source {source!r}"
            )

    seen = set()
    for record in validated:
        identity = _identity_tuple(record)
        if identity in seen:
            raise BundleValidationError(
                f"duplicate candidate identity: {identity}"
            )
        seen.add(identity)

    payload = {
        "generatedAt": _utc_now_z(),
        "source": source,
        "records": [r.model_dump(mode="json") for r in validated],
    }
    digest = _hash_payload(payload)
    envelope = {
        "formatVersion": FORMAT_VERSION,
        "payload": payload,
        "sha256": digest,
    }
    raw = json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    if len(raw) > MAX_BUNDLE_BYTES:
        raise BundleValidationError(
            f"bundle size {len(raw)} exceeds {MAX_BUNDLE_BYTES} bytes"
        )
    return raw


def decode_bundle(data: bytes | str) -> list[CandidateModel]:
    """Verify the envelope and return the validated records."""
    if not isinstance(data, (bytes, str)):
        raise BundleValidationError("bundle must be bytes or str")
    try:
        raw = data if isinstance(data, bytes) else data.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise BundleValidationError(f"bundle is not valid UTF-8: {exc}") from exc
    if len(raw) > MAX_BUNDLE_BYTES:
        raise BundleValidationError(
            f"bundle size {len(raw)} exceeds {MAX_BUNDLE_BYTES} bytes"
        )
    try:
        envelope = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BundleValidationError(f"invalid JSON: {exc}") from exc

    if not isinstance(envelope, dict):
        raise BundleValidationError("envelope must be a JSON object")

    for field in ("formatVersion", "payload", "sha256"):
        if field not in envelope:
            raise BundleValidationError(f"missing envelope field: {field}")

    version = envelope["formatVersion"]
    if isinstance(version, bool) or version != FORMAT_VERSION:
        raise BundleValidationError(
            f"unknown formatVersion {version!r}; expected {FORMAT_VERSION}"
        )

    payload = envelope["payload"]
    if not isinstance(payload, dict):
        raise BundleValidationError("payload must be a JSON object")
    for field in ("generatedAt", "source", "records"):
        if field not in payload:
            raise BundleValidationError(f"missing payload field: {field}")
    if not isinstance(payload["source"], str) or not payload["source"].strip():
        raise BundleValidationError("payload.source must be a non-blank string")

    try:
        expected = _hash_payload(payload)
    except (TypeError, ValueError) as exc:
        raise BundleValidationError(f"payload cannot be canonicalized: {exc}") from exc
    supplied = envelope["sha256"]
    if not isinstance(supplied, str) or not hmac.compare_digest(supplied, expected):
        raise BundleValidationError("sha256 digest mismatch")

    records_data = payload["records"]
    if not isinstance(records_data, list):
        raise BundleValidationError("payload.records must be a list")
    if len(records_data) > MAX_RECORDS:
        raise BundleValidationError(
            f"bundle contains {len(records_data)} records (maximum {MAX_RECORDS})"
        )

    try:
        records = [CandidateModel.model_validate(r) for r in records_data]
    except ValidationError as exc:
        raise BundleValidationError(f"invalid candidate record: {exc}") from exc

    if any(record.source != payload["source"] for record in records):
        raise BundleValidationError("candidate source does not match payload source")
    identities = [_identity_tuple(record) for record in records]
    if len(set(identities)) != len(identities):
        raise BundleValidationError("duplicate candidate identity")
    return records
