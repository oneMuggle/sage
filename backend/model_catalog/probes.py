"""Service probe adapters: extract model metadata from running services.

Each adapter is a pure function — ``parse_probe(service, response) -> ProbeValues``.
``probe_endpoint`` reads endpoint configuration and makes outbound requests.

Supported services:
- ``ollama``: POST ``/api/show`` → ``model_info.llama.context_length`` → native
- ``openai-compatible`` (LM Studio, vLLM, Xinference, LocalAI): ``/v1/models``
  returns model listing only; no reliable context/price metadata.

Critical rules:
- Only exact runtime fields write to ``service``.
- File metadata (GGUF ``llama.context_length``) is ``native``, not ``service``.
- Service failure marks probe stale; does not delete previous success.
"""

from __future__ import annotations

import json
import logging
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Timeout for probe requests (seconds)
_PROBE_TIMEOUT = 10.0
_MAX_RESPONSE_BYTES = 1 * 1024 * 1024  # 1 MiB


class ProbeValues(BaseModel):
    """Extracted metadata from a probe response.

    Fields map directly to :class:`EndpointPatch` fields so the route can
    pass them to ``repository.save_probe`` without translation.
    """

    native: int | None = None
    service: int | None = None
    architecture: str | None = None
    quantization: str | None = None


class ProbeResult(BaseModel):
    """Route-level probe response.

    status:
    - ``success``: probe returned usable metadata
    - ``unsupported``: service has no metadata endpoint
    - ``error``: network error, timeout, or malformed response
    """

    status: Literal["success", "unsupported", "error"]
    adapter: str = "unknown"
    data: dict | None = None
    error: str | None = None


def parse_probe(service: str, response: dict) -> ProbeValues:
    """Parse a service-specific response into probe values.

    Pure function — no networking, no side effects.

    Rules:
    - Ollama ``/api/show``: ``model_info.llama.context_length`` → native
    - OpenAI-compatible: no reliable metadata → empty ProbeValues
    - Unknown service → empty ProbeValues
    """
    if service == "ollama":
        return _parse_ollama(response)
    if service in (
        "openai-compatible",
        "lmstudio",
        "vllm",
        "xinference",
        "localai",
    ):
        return ProbeValues()
    return ProbeValues()


def _parse_ollama(response: dict) -> ProbeValues:
    """Parse Ollama ``/api/show`` response.

    Ollama returns ``model_info`` with ``llama.*`` keys:
    - ``llama.context_length``: context window from GGUF metadata → native
    - ``llama.embedding_length``, etc. (ignored)

    ``details`` may contain:
    - ``family`` → architecture
    - ``quantization_level`` → quantization

    Only exact runtime fields write to ``service``.  File metadata (GGUF
    ``llama.context_length``) is ``native``, not ``service``.
    """
    if not isinstance(response, dict):
        return ProbeValues()

    model_info = response.get("model_info") or {}
    if not isinstance(model_info, dict):
        model_info = {}

    native = _positive_int(model_info.get("llama.context_length"))

    details = response.get("details") or {}
    if not isinstance(details, dict):
        details = {}

    architecture = _nonblank_str(details.get("family"))
    quantization = _nonblank_str(details.get("quantization_level"))

    return ProbeValues(
        native=native,
        service=None,
        architecture=architecture,
        quantization=quantization,
    )


def _positive_int(value) -> int | None:
    """Return value if it is a strict positive int, else None."""
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    return value if value > 0 else None


def _nonblank_str(value) -> str | None:
    """Return value if it is a non-blank string, else None."""
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def detect_service(protocol: str, base_url: str) -> str:
    """Map endpoint protocol to a service identifier for adapter selection.

    Only ``ollama`` has a dedicated metadata endpoint.  Everything else
    (OpenAI-compatible, Anthropic, Gemini) maps to ``openai-compatible``
    for probing purposes — none of them expose context/price metadata
    via their standard discovery endpoints.
    """
    if protocol == "ollama":
        return "ollama"
    return "openai-compatible"


async def probe_endpoint(
    endpoint_id: str,
    model_id: str,
    *,
    base_url: str,
    api_key: str = "",
    protocol: str = "openai-compatible",
) -> ProbeResult:
    """Probe an endpoint for model metadata.

    Constructs a request with credentials, calls the service-specific path,
    and returns a :class:`ProbeResult`.  Uses shared ``upstream_security``
    helpers for DNS validation, SSRF prevention, and bounded responses.

    The caller (route handler) is responsible for persisting the result
    via ``repository.save_probe``.
    """
    from backend.api.upstream_security import (
        client_for_resolved_address,
        read_response_body_limited,
        resolve_and_validate_upstream_host,
    )

    service = detect_service(protocol, base_url)

    try:
        if service == "ollama":
            return await _probe_ollama(
                base_url,
                model_id,
                resolve_fn=resolve_and_validate_upstream_host,
                client_fn=client_for_resolved_address,
                read_fn=read_response_body_limited,
            )
        # OpenAI-compatible services have no metadata endpoint
        return ProbeResult(
            status="unsupported",
            adapter=service,
            error="OpenAI-compatible services do not expose model metadata via /v1/models",
        )
    except Exception as exc:
        logger.warning("probe failed for %s/%s: %s", endpoint_id, model_id, exc)
        return ProbeResult(
            status="error",
            adapter=service,
            error=str(exc)[:500],
        )


async def _probe_ollama(
    base_url: str,
    model_id: str,
    *,
    resolve_fn,
    client_fn,
    read_fn,
) -> ProbeResult:
    """Probe Ollama ``/api/show`` for model metadata."""
    url = base_url.rstrip("/") + "/api/show"
    parsed = urlparse(url)

    pinned_address = await resolve_fn(parsed)
    client = client_fn(pinned_address, _PROBE_TIMEOUT)
    try:
        response = await client.post(url, json={"model": model_id})
        response.raise_for_status()
        body = await read_fn(response, _MAX_RESPONSE_BYTES)
        data = json.loads(body)
        values = parse_probe("ollama", data)
        return ProbeResult(
            status="success",
            adapter="ollama",
            data=values.model_dump(),
        )
    finally:
        await client.aclose()


def load_endpoint_config(endpoint_id: str) -> dict | None:
    """Read endpoint configuration from settings storage.

    Returns the endpoint dict or None if not found.
    """
    from backend.data.settings_repo import SettingsRepository

    repo = SettingsRepository()
    settings = repo.get_json("app_settings")
    if not isinstance(settings, dict):
        return None
    endpoints = settings.get("endpoints") or []
    if not isinstance(endpoints, list):
        return None
    for ep in endpoints:
        if isinstance(ep, dict) and ep.get("id") == endpoint_id:
            return ep
    return None


async def probe_endpoint_from_settings(
    endpoint_id: str, model_id: str
) -> ProbeResult:
    """Probe using endpoint configuration from settings storage.

    This is the main entry point for the POST /probe route.
    """
    config = load_endpoint_config(endpoint_id)
    if config is None:
        return ProbeResult(
            status="error",
            adapter="unknown",
            error=f"endpoint {endpoint_id!r} not found in settings",
        )
    base_url = config.get("baseUrl") or config.get("base_url") or ""
    if not base_url:
        return ProbeResult(
            status="error",
            adapter="unknown",
            error="endpoint has no base URL",
        )
    api_key = config.get("apiKey") or config.get("api_key") or ""
    protocol = config.get("protocol", "openai-compatible")
    return await probe_endpoint(
        endpoint_id,
        model_id,
        base_url=base_url,
        api_key=api_key,
        protocol=protocol,
    )
