"""Arena run.trace.model resolver per spec §3.5.

Extracts the highest-weight evidence source for model identification
(weight 1.00 in backend/services/model_probe_py/classify.py:19-34).

Flow:
  1. Hook into SSE stream in arena_observation.process_event
  2. Scan WS frame payloadData for a public-access-token + runId
  3. Call Arena /api/runs/{runId}/trace via the same browser session
     (Network.fetch CDP command — spec §7.3 forbids a separate HTTP client)
  4. Locate the ai.streamText.doStream span in the response
  5. Emit a {"source": "run.trace.model", "modelId": ..., "weight": 1.0}
     evidence dict and feed it to the model probe worker

Known TODO (Phase B):
  - The exact SSE field name for public-access-token is unconfirmed.
    See test_run_trace_resolver.py for the assumed shape.
  - The /api/runs/{id}/trace auth scheme is unconfirmed (likely Bearer).
    Will be measured empirically in Phase B.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunTraceEvidence:
    """Highest-weight evidence for model identification."""
    model_id: str
    run_id: str
    weight: float = 1.00
    source: str = "run.trace.model"


# Tentative regex — actual field name to be filled in after dev logging.
_TOKEN_PATTERN = re.compile(
    r'"public-access-token"\s*:\s*"(?P<token>[A-Za-z0-9._\-]+)"'
)
_RUN_ID_PATTERN = re.compile(
    r'"runId"\s*:\s*"(?P<run_id>[A-Za-z0-9._\-]+)"'
)


def scan_sse_frame_for_run_id(payload: str) -> Optional[str]:
    """Return the runId if the SSE chunk contains one, else None.

    TODO(Phase B): replace regex with the actual field name once a real
    SSE chunk is captured in dev mode.
    """
    m = _RUN_ID_PATTERN.search(payload)
    return m.group("run_id") if m else None


def extract_authorization_token(payload: str) -> Optional[str]:
    """Return the public-access-token if present in the SSE chunk.

    TODO(Phase B): confirm the exact field name; current assumption is
    the token is serialized as a top-level field in the SSE JSON object.
    """
    m = _TOKEN_PATTERN.search(payload)
    return m.group("token") if m else None


def parse_trace_response(trace_json: Dict[str, Any]) -> Optional[str]:
    """Locate the ai.streamText.doStream span and return its model label.

    The trace response is assumed to be an OpenTelemetry-shaped JSON
    document with a `spans` array. We look for the span whose `name`
    is `ai.streamText.doStream` and return `attributes.model` (or
    `attributes.ai.model` if present).

    TODO(Phase B): confirm the exact attribute path once a real trace
    response is captured.
    """
    spans = trace_json.get("spans") or []
    for span in spans:
        if span.get("name") == "ai.streamText.doStream":
            attrs = span.get("attributes") or {}
            return attrs.get("model") or attrs.get("ai.model")
    return None


class RunTraceResolver:
    """Stateful resolver: caches the most recently observed runId per session.

    The actual fetch of /api/runs/{id}/trace is delegated to an injected
    callable so tests can mock it without touching the network or browser.
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
        """Hook called by arena_observation.process_event on WS frames."""
        run_id = scan_sse_frame_for_run_id(payload)
        if not run_id or run_id == self._last_run_id:
            return
        self._last_run_id = run_id
        token = extract_authorization_token(payload)
        try:
            trace = self._fetch_trace(run_id, token)
        except Exception as exc:
            logger.warning("run trace fetch failed for %s: %s", run_id, exc)
            return
        model_id = parse_trace_response(trace)
        if model_id:
            self._emit_evidence(
                RunTraceEvidence(model_id=model_id, run_id=run_id)
            )
