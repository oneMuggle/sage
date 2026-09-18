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
import re
import time as _time
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
    tokens: Optional[int] = None
    cost_usd: Optional[float] = None


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
                if isinstance(pair, list | tuple) and len(pair) >= 2 and str(pair[0]).lower() == "public-access-token" and isinstance(pair[1], str):
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


#: Expected JWT issuer for Trigger.dev public-access-tokens
_TRIGGER_ISSUER = "https://id.trigger.dev"

#: Expected JWT audience for Trigger.dev public-access-tokens
_TRIGGER_AUDIENCE = "https://api.trigger.dev"


def validate_jwt_claims(claims: Dict[str, Any]) -> bool:
    """Validate JWT claims from a Trigger.dev public-access-token.

    Checks:
    - iss == "https://id.trigger.dev"
    - aud == "https://api.trigger.dev" (if present)
    - exp > current time (not expired)
    - pub == True (public access token marker)

    Returns True if all checks pass, False otherwise.
    """
    if not isinstance(claims, dict):
        return False

    # Issuer check (required)
    iss = claims.get("iss")
    if iss != _TRIGGER_ISSUER:
        logger.debug("JWT issuer mismatch: %r", iss)
        return False

    # Audience check (optional but must match if present)
    aud = claims.get("aud")
    if aud is not None and aud != _TRIGGER_AUDIENCE:
        logger.debug("JWT audience mismatch: %r", aud)
        return False

    # Expiration check (required)
    exp = claims.get("exp")
    if not isinstance(exp, int | float) or exp <= _time.time():
        logger.debug("JWT missing, invalid, or expired exp claim")
        return False

    # Public access token marker (required)
    pub = claims.get("pub")
    return pub is True


#: Pattern for token counts like "6.6k", "1.2M", "1500", "1,500"
_TOKEN_RE = re.compile(r"^[\d,]+(?:\.\d+)?\s*([kKmMbB])?$")


def parse_token_count(text: str) -> Optional[int]:
    """Parse a token count string like '6.6k' or '1,500' into an integer.

    Returns None if the text is not a valid token count.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    cleaned = text.strip().replace(",", "")
    m = _TOKEN_RE.match(cleaned)
    if not m:
        return None
    suffix = (m.group(1) or "").lower()
    numeric = float(cleaned.rstrip("kKmMbB"))
    multiplier = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get(suffix, 1)
    return int(numeric * multiplier)


#: Pattern for cost strings like "$0.03", "$ 1.50", "0.05"
_COST_RE = re.compile(r"^\$?\s*([\d,]+(?:\.\d+)?)$")


def parse_cost_usd(text: str) -> Optional[float]:
    """Parse a cost string like '$0.03' or '1.50' into a float.

    Returns None if the text is not a valid cost.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    cleaned = text.strip().replace(",", "")
    m = _COST_RE.match(cleaned)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def extract_models_from_trace(
    trace_json: Dict[str, Any], run_id: str
) -> List[Dict[str, Any]]:
    """Extract model + provider + tokens + cost from Trigger.dev trace events.

    Looks for events with message="ai.streamText.doStream" matching runId.
    Model name comes from style.accessory.items[icon=tabler-cube].text.
    Provider comes from style.icon (format: "ai-provider-<name>").
    Tokens come from style.accessory.items[icon=tabler-hash].text (e.g. "6.6k").
    Cost comes from style.accessory.items[icon=tabler-currency-dollar].text.
    """
    events = trace_json.get("events") if isinstance(trace_json, dict) else None
    if not isinstance(events, list):
        return []
    found: List[Dict[str, Any]] = []
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
        tokens: Optional[int] = None
        cost_usd: Optional[float] = None
        models: List[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            icon = item.get("icon") or ""
            text = item.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            if icon == "tabler-cube":
                models.append(text.strip())
            elif icon == "tabler-hash":
                tokens = parse_token_count(text)
            elif icon == "tabler-currency-dollar":
                cost_usd = parse_cost_usd(text)
        for model in models:
            entry: Dict[str, Any] = {"model": model}
            if provider:
                entry["provider"] = provider
            if tokens is not None:
                entry["tokens"] = tokens
            if cost_usd is not None:
                entry["cost_usd"] = cost_usd
            if entry not in found:
                found.append(entry)
    return found


class RunTraceResolver:
    """Stateful resolver: caches the most recently observed runId.

    The fetch of /api/runs/{id}/trace is delegated to an injected callable
    so tests can mock it without touching the network or browser.

    Retry policy (per reference project background.js, 8×retry with 3s interval):
    The trace fetch is retried up to ``max_attempts`` times on any exception
    (connection error, HTTP 5xx, timeout). Sleep between attempts is
    ``base_delay`` seconds (default 3.0, matching the reference project's
    fixed interval). The resolver never raises — failures are logged and
    silently dropped so the observation pipeline stays alive.
    """

    #: Default retry count per reference project (background.js: 8 retries).
    DEFAULT_MAX_ATTEMPTS = 8

    #: Default delay between retries in seconds (reference project: 3s).
    DEFAULT_BASE_DELAY_S = 3.0

    def __init__(
        self,
        fetch_trace: Callable[[str, Optional[str]], Dict[str, Any]],
        emit_evidence: Callable[[RunTraceEvidence], None],
        *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        base_delay: float = DEFAULT_BASE_DELAY_S,
    ):
        self._fetch_trace = fetch_trace
        self._emit_evidence = emit_evidence
        self._last_run_id: Optional[str] = None
        self._max_attempts = max(1, int(max_attempts))
        self._base_delay = max(0.0, float(base_delay))

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
        if not validate_jwt_claims(claims):
            logger.debug("JWT claims validation failed, skipping token")
            return
        run_id = extract_run_id_from_claims(claims)
        if not run_id or run_id == self._last_run_id:
            return
        self._last_run_id = run_id
        trace = self._fetch_trace_with_retry(run_id, token)
        if trace is None:
            return
        models = extract_models_from_trace(trace, run_id)
        for entry in models:
            self._emit_evidence(
                RunTraceEvidence(
                    model_id=entry["model"],
                    run_id=run_id,
                    provider=entry.get("provider", ""),
                    tokens=entry.get("tokens"),
                    cost_usd=entry.get("cost_usd"),
                )
            )

    def _fetch_trace_with_retry(
        self, run_id: str, token: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch the trace for ``run_id``, retrying up to ``_max_attempts``.

        Retries on any exception (network error, HTTP 5xx, timeout). Sleeps
        ``_base_delay`` seconds between attempts (fixed interval per the
        reference project). Returns the trace dict on success, or ``None``
        if all attempts failed. Never raises — failures are logged.
        """
        last_exc: Optional[BaseException] = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                return self._fetch_trace(run_id, token)
            except Exception as exc:
                last_exc = exc
                if attempt < self._max_attempts:
                    logger.debug(
                        "run trace fetch attempt %d/%d failed for %s: %s; "
                        "retrying in %.1fs",
                        attempt, self._max_attempts, run_id, exc,
                        self._base_delay,
                    )
                    if self._base_delay > 0:
                        _time.sleep(self._base_delay)
        logger.warning(
            "run trace fetch failed after %d attempts for %s: %s",
            self._max_attempts, run_id, last_exc,
        )
        return None
