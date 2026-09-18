"""Arena run.trace.model resolver per spec §3.5.

Extracts the highest-weight evidence source for model identification
(weight 1.00 in backend/services/model_probe_py/classify.py:19-34).

Protocol (confirmed against arena-trace-inspector v2.0.0 reference):
  1. Arena SSE stream at /ai-proxy/realtime/v1/sessions/<sessionId>/out
     emits frames with JSON body containing records[].headers array
  2. public-access-token JWT is in headers as ["public-access-token", "<jwt>"]
  3. JWT payload contains: pub=true, iss="https://id.trigger.dev",
     run="run_<id>" (or scopes=["read:runs:run_<id>"] in older tokens)
  4. GET https://api.trigger.dev/api/v1/runs/<runId>/events with Bearer token
  5. Response has events[] array; find events with message="ai.streamText.doStream"
  6. Model name is in event.style.accessory.items[icon=tabler-cube].text
  7. Provider is in event.style.icon (format: "ai-provider-<name>")
"""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunTraceEvidence:
    """Highest-weight evidence for model identification."""
    model_id: str
    run_id: str
    weight: float = 1.00
    source: str = "run.trace.model"
    provider: str = ""


def _strip_sse_prefix(payload: str) -> str:
    """Strip SSE 'data: ' prefix lines to get raw JSON."""
    lines = payload.strip().splitlines()
    data_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("data:"):
            data_lines.append(stripped[5:].lstrip())
        elif stripped:
            data_lines.append(stripped)
    return "\n".join(data_lines)


def parse_sse_frame(payload: str) -> Optional[Dict[str, Any]]:
    """Parse raw SSE payload into JSON object. Returns None on parse failure."""
    raw = _strip_sse_prefix(payload)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None


def extract_public_access_token(frame: Dict[str, Any]) -> Optional[str]:
    """Extract public-access-token from SSE frame records[].headers.

    The token appears as a key-value pair in the headers array:
    {"records": [{"headers": [["public-access-token", "<jwt>"], ...]}]}
    """
    records = frame.get("records") if isinstance(frame, dict) else None
    if not isinstance(records, list):
        records = [frame]
    for record in records:
        if not isinstance(record, dict):
            continue
        headers = record.get("headers")
        if isinstance(headers, list):
            for pair in headers:
                if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                    if str(pair[0]).lower() == "public-access-token" and isinstance(pair[1], str):
                        return pair[1]
        elif isinstance(headers, dict):
            for key, value in headers.items():
                if str(key).lower() == "public-access-token" and isinstance(value, str):
                    return value
    return None


def decode_jwt_payload(token: str) -> Dict[str, Any]:
    """Decode JWT payload (no signature verification).

    Raises ValueError on malformed token.
    """
    if not isinstance(token, str):
        raise ValueError("token must be a string")
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError(f"JWT must have 3 parts, got {len(parts)}")
    payload_b64 = parts[1]
    padding = "=" * ((4 - len(payload_b64) % 4) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload_b64 + padding)
        return json.loads(decoded)
    except Exception as exc:
        raise ValueError(f"Cannot decode JWT payload: {exc}") from exc


def extract_run_id_from_claims(claims: Dict[str, Any]) -> Optional[str]:
    """Extract runId from JWT claims.

    Two formats supported:
    - New: claims["type"] == "run" and claims["run"] == "run_<id>"
    - Old: claims["scopes"] contains exactly one "read:runs:run_<id>"
    """
    run_field = claims.get("run")
    if isinstance(run_field, str) and run_field.startswith("run_"):
        return run_field
    scopes = claims.get("scopes") or []
    run_scopes = [
        s for s in scopes
        if isinstance(s, str) and s.startswith("read:runs:run_")
    ]
    if len(run_scopes) == 1:
        return run_scopes[0][len("read:runs:"):]
    return None


def extract_models_from_trace(
    trace_json: Dict[str, Any], run_id: str
) -> List[Dict[str, str]]:
    """Extract model + provider from Trigger.dev trace events.

    Looks for events with message="ai.streamText.doStream" matching runId.
    Model name comes from style.accessory.items[icon=tabler-cube].text.
    Provider comes from style.icon (format: "ai-provider-<name>").
    """
    events = trace_json.get("events") if isinstance(trace_json, dict) else None
    if not isinstance(events, list):
        return []
    found: List[Dict[str, str]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("runId") != run_id:
            continue
        if event.get("message") != "ai.streamText.doStream":
            continue
        style = event.get("style") or {}
        provider_icon = style.get("icon") or ""
        provider = ""
        if isinstance(provider_icon, str) and provider_icon.startswith("ai-provider-"):
            provider = provider_icon[len("ai-provider-"):]
        accessory = style.get("accessory") or {}
        items = accessory.get("items") or []
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("icon") != "tabler-cube":
                continue
            model_text = item.get("text")
            if isinstance(model_text, str) and model_text.strip():
                model = model_text.strip()
                entry: Dict[str, str] = {"model": model}
                if provider:
                    entry["provider"] = provider
                if entry not in found:
                    found.append(entry)
    return found


class RunTraceResolver:
    """Stateful resolver: caches the most recently observed runId.

    The fetch of /api/runs/{id}/trace is delegated to an injected callable
    so tests can mock it without touching the network or browser.
    """

    def __init__(
        self,
        fetch_trace: Callable[[str, Optional[str]], Dict[str, Any]],
        emit_evidence: Callable[[RunTraceEvidence], None],
    ):
        self._fetch_trace = fetch_trace
        self._emit_evidence = emit_evidence
        self._last_run_id: Optional[str] = None

    def observe_sse_chunk(self, payload: str) -> None:
        """Hook called by arena_observation.process_event on WS frames.

        Flow:
        1. Parse SSE frame JSON
        2. Extract public-access-token from records[].headers
        3. Decode JWT to get runId
        4. Fetch trace if runId is new
        5. Parse trace events to extract model + provider
        6. Emit RunTraceEvidence
        """
        frame = parse_sse_frame(payload)
        if frame is None:
            return
        token = extract_public_access_token(frame)
        if not token:
            return
        try:
            claims = decode_jwt_payload(token)
        except ValueError as exc:
            logger.debug("JWT decode failed: %s", exc)
            return
        run_id = extract_run_id_from_claims(claims)
        if not run_id or run_id == self._last_run_id:
            return
        self._last_run_id = run_id
        try:
            trace = self._fetch_trace(run_id, token)
        except Exception as exc:
            logger.warning("run trace fetch failed for %s: %s", run_id, exc)
            return
        models = extract_models_from_trace(trace, run_id)
        for entry in models:
            self._emit_evidence(
                RunTraceEvidence(
                    model_id=entry["model"],
                    run_id=run_id,
                    provider=entry.get("provider", ""),
                )
            )
