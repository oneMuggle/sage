from __future__ import annotations

import json
import logging
import re
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, Deque, Dict, List, Optional

from .model_probe_py.classify import (
    collectModelFields,
    protocolFingerprint,
    scanTextForModel,
)
from .run_trace_resolver import RunTraceResolver

logger = logging.getLogger(__name__)


#: URL patterns that look like AI inference endpoints
_LLM_URL_HINTS = re.compile(
    r"(?:completions?|chat|messages|generate|generateContent|"
    r"streamGenerateContent|converse|invoke|agent|run|responses|"
    r"assistant|thread|conversation|inference|chatbot|api/v\d|/api/|/rpc/|/graphql/)",
    re.IGNORECASE,
)

#: Telemetry / analytics hosts whose payloads should never be treated as model evidence
_TELEMETRY_RE = re.compile(
    r"(?:datadoghq|datadog|posthog|sentry|amplitude|mixpanel|segment\.io|"
    r"segment\.com|google-analytics|googletagmanager|hotjar|clarity\.ms|"
    r"fullstory|logrocket|newrelic|nr-data|bugsnag|rollbar|trackjs|"
    r"raygun|elastic\.co|honeycomb|lightstep|opentelemetry|otlp|"
    r"statsig|launchdarkly|optimizely|split\.io|vwo\.com|matomo|"
    r"plausible\.io|umami|vercel-insights|vercel\.com/_vercel/insights)",
    re.IGNORECASE,
)

#: Static asset extensions
_STATIC_EXT_RE = re.compile(
    r"\.(?:js|css|png|jpe?g|gif|svg|woff2?|ttf|ico|map|mp4|webp|avif)(?:\?|$)",
    re.IGNORECASE,
)


def _is_llm_relevant(url: str) -> bool:
    if not url:
        return False
    if _STATIC_EXT_RE.search(url):
        return False
    if _TELEMETRY_RE.search(url):
        return False
    return bool(_LLM_URL_HINTS.search(url))


class ModelObservationService:
    """Route CDP Network events into probe worker; track recent verdicts."""

    #: Default cap on stored verdicts (matches spec §3.1 probe_evidence_cap)
    DEFAULT_VERDICT_CAP = 500

    def __init__(
        self,
        browser_session: Any,
        worker: Any,
        verdict_cap: int = DEFAULT_VERDICT_CAP,
        run_trace_resolver: Optional[RunTraceResolver] = None,
        pump_factory: Optional[Callable[[ModelObservationService], Any]] = None,
    ):
        self._browser_session = browser_session
        self._worker = worker
        self._verdict_cap = verdict_cap
        self._run_trace_resolver = run_trace_resolver
        self._verdicts: Deque[Dict] = deque(maxlen=verdict_cap)
        self._running = False
        #: pump_factory(service) → 事件泵（需 start()/stop()）；None 时 start()
        #: 只置 running 标志（测试/手动喂事件模式），不建立真实 CDP 连接
        self._pump_factory = pump_factory
        self._pump: Any = None

    def start(self) -> None:
        """Open the event pump (long-lived CDP connection → Network events)."""
        if self._running:
            return
        if self._pump_factory is not None:
            self._pump = self._pump_factory(self)
            self._pump.start()
        self._running = True
        logger.info("ModelObservationService started (pump=%s)", self._pump is not None)

    def stop(self) -> None:
        if self._pump is not None:
            try:
                self._pump.stop()
            except Exception as exc:  # noqa: BLE001 — shutdown 不能抛
                logger.debug("observation pump stop failed: %s", exc)
            self._pump = None
        self._running = False
        logger.info("ModelObservationService stopped")

    def process_event(self, event: Dict) -> Optional[Dict]:
        """Parse a single CDP event into evidence; ask worker to classify.

        Returns the verdict dict, or None if the event was filtered out.
        """
        if not isinstance(event, dict):
            return None
        method = event.get("method", "")
        params = event.get("params") or {}

        if method == "Network.requestWillBeSent":
            evidence = self._evidence_from_request(params)
        elif method == "Network.responseReceived":
            evidence = self._evidence_from_response(params)
        elif method == "Network.webSocketFrameReceived":
            evidence = self._evidence_from_ws_frame(params)
            if self._run_trace_resolver is not None:
                payload_data = params.get("payloadData") or ""
                if payload_data:
                    try:
                        self._run_trace_resolver.observe_sse_chunk(payload_data)
                    except Exception as exc:
                        logger.warning("run_trace_resolver hook failed: %s", exc)
        else:
            return None

        if evidence is None:
            return None

        try:
            verdict = self._worker.classify(evidence)
        except Exception as e:  # noqa: BLE001
            logger.warning("worker.classify failed: %s", e)
            return None

        if verdict and verdict.get("modelId") or verdict and verdict.get("family"):
            self._record_verdict(verdict)
            return verdict
        return None

    def get_recent_verdicts(self, n: int = 10) -> List[Dict]:
        if n <= 0:
            return []
        return list(self._verdicts)[-n:]

    # -- internal helpers -------------------------------------------------

    def _record_verdict(self, verdict: Dict) -> None:
        record = dict(verdict)
        record["observed_at"] = (
            datetime.now(timezone.utc)  # noqa: UP017 — py38 兼容
            .replace(tzinfo=None, microsecond=0)
            .isoformat()
        )
        self._verdicts.append(record)
        while len(self._verdicts) > self._verdict_cap:
            self._verdicts.popleft()

    def _evidence_from_request(self, params: Dict) -> Optional[Dict]:
        request = params.get("request") or {}
        url = request.get("url") or ""
        if not _is_llm_relevant(url):
            return None
        post_data = request.get("postData") or ""
        if not post_data:
            return None
        # Try to find a model field in the request body
        try:
            payload = json.loads(post_data)
        except (ValueError, TypeError):
            # Not JSON — try regex scan
            found = scanTextForModel(post_data)
            if found:
                return {"source": "request.body.model", "modelId": found[0], "raw": url}
            return None
        fields = collectModelFields(payload)
        if fields:
            return {"source": "request.body.model", "modelId": fields[0]["value"], "raw": url}
        return None

    def _evidence_from_response(self, params: Dict) -> Optional[Dict]:
        response = params.get("response") or {}
        url = response.get("url") or ""
        if not _is_llm_relevant(url):
            return None
        # Check headers first
        headers = response.get("headers") or {}
        for k, v in headers.items():
            if "model" in k.lower() and isinstance(v, str):
                return {"source": "response.header.model", "modelId": v, "raw": url}
        # Body parsing happens later via loadingFinished
        return None

    def _evidence_from_ws_frame(self, params: Dict) -> Optional[Dict]:
        # SSE chunks arrive as text WebSocket frames on /api/agent
        response = params.get("response") or {}
        url = response.get("url") or ""
        if not _is_llm_relevant(url):
            return None
        payload = params.get("payloadData") or ""
        if not payload:
            return None
        # Try structured parse first
        try:
            obj = json.loads(payload)
            fields = collectModelFields(obj)
            if fields:
                return {"source": "sse.chunk.model", "modelId": fields[0]["value"], "raw": url}
        except (ValueError, TypeError):
            pass
        # Regex fallback
        found = scanTextForModel(payload)
        if found:
            return {"source": "sse.chunk.model", "modelId": found[0], "raw": url}
        # Protocol fingerprint as last resort
        family = protocolFingerprint(payload)
        if family:
            return {"source": "protocol.framing", "family": family, "raw": url}
        return None
