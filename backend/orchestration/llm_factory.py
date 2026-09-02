"""
LLM factory for the orchestration layer.

Builds an ``LLMClient`` from the user's persisted endpoint configuration
(``app_settings`` in the preferences table), following the same pattern as
``backend/scheduler/evolution.py``: callers accept an *injected* client and
fall back to a settings-derived default when none is provided.

Resolution order for the endpoint:

1. ``modelSelections.chatModel.{endpointId, modelId}`` — the endpoint the
   user selected for chat, with the selected model.
2. The first endpoint in ``endpoints`` that carries a non-empty ``apiKey``,
   with its first discovered model (if any).

If no usable endpoint exists (no settings / no endpoints / no apiKey), the
factory returns ``None`` and callers degrade gracefully (single-task
planner fallback, clean ``ToolResult`` error for the agent tool).

All functions are defensive: any settings corruption (non-dict payloads,
missing keys, snake_case residue) yields ``None`` rather than raising.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Default model when an endpoint has no discovered models recorded.
DEFAULT_MODEL = "gpt-3.5-turbo"


def load_llm_config_from_settings() -> Optional[Dict[str, Any]]:
    """Resolve an ``LLMConfig``-compatible dict from persisted app_settings.

    Returns:
        A dict suitable for ``LLMConfig(**cfg)`` (provider/api_key/base_url/
        model/temperature), or ``None`` when no usable endpoint is configured.
    """
    try:
        from backend.data.settings_canonicalizer import to_camel
        from backend.data.settings_repo import SettingsRepository

        raw = SettingsRepository().get_json("app_settings")
    except Exception as exc:  # DB unavailable / corrupted — degrade
        logger.warning("llm_factory: failed to read app_settings: %s", exc)
        return None

    if not isinstance(raw, dict):
        return None

    # Normalize legacy snake_case residue to camelCase before reading.
    settings = to_camel(raw)

    endpoints = settings.get("endpoints") or []
    if not isinstance(endpoints, list) or not endpoints:
        return None

    selections = settings.get("modelSelections") or {}
    chat_selection = selections.get("chatModel") if isinstance(selections, dict) else None

    endpoint = None
    model_id = None
    if isinstance(chat_selection, dict) and chat_selection.get("endpointId"):
        endpoint = next(
            (
                ep
                for ep in endpoints
                if isinstance(ep, dict) and ep.get("id") == chat_selection.get("endpointId")
            ),
            None,
        )
        model_id = chat_selection.get("modelId") or None

    # Fallback: first endpoint with a usable apiKey.
    if endpoint is None:
        endpoint = next(
            (ep for ep in endpoints if isinstance(ep, dict) and ep.get("apiKey")),
            None,
        )

    if (
        not isinstance(endpoint, dict)
        or (endpoint.get("protocol") or "openai-compatible") not in _SUPPORTED_PROTOCOLS
        or (not endpoint.get("apiKey") and endpoint.get("protocol") not in {"ollama", "openai-compatible"})
        or not endpoint.get("baseUrl")
    ):
        return None

    if not model_id:
        discovered = endpoint.get("discoveredModels") or []
        if isinstance(discovered, list) and discovered and isinstance(discovered[0], dict):
            model_id = discovered[0].get("id")
    if not model_id:
        model_id = DEFAULT_MODEL

    return {
        "provider": "custom",
        "api_key": endpoint["apiKey"],
        "base_url": endpoint["baseUrl"],
        "model": model_id,
        "temperature": 0.3,
    }


def _endpoint_has_required_api_key(
    endpoint: Dict[str, Any], *, protocol: Optional[str] = None
) -> bool:
    """Return whether an endpoint satisfies its protocol's auth contract."""
    endpoint_protocol = protocol or endpoint.get("protocol") or "openai-compatible"
    if endpoint_protocol in {"ollama", "openai-compatible"}:
        return True
    return bool(endpoint.get("apiKey"))


_SUPPORTED_PROTOCOLS = frozenset({"anthropic", "gemini", "ollama", "openai-compatible"})

_PROVIDER_TYPES: Optional[Dict[str, Any]] = None


def _provider_types() -> Dict[str, Any]:
    """Load provider classes lazily so importing the factory stays cheap."""
    global _PROVIDER_TYPES
    if _PROVIDER_TYPES is None:
        from backend.adapters.out.llm.anthropic import AnthropicProvider
        from backend.adapters.out.llm.gemini import GeminiProvider
        from backend.adapters.out.llm.ollama import OllamaProvider
        from backend.adapters.out.llm.openai import OpenAIProvider

        _PROVIDER_TYPES = {
            "anthropic": AnthropicProvider,
            "gemini": GeminiProvider,
            "ollama": OllamaProvider,
            "openai-compatible": OpenAIProvider,
        }
    return _PROVIDER_TYPES


def resolve_provider_and_model_from_settings() -> Optional[tuple[Any, str]]:  # noqa: PLR0911
    """Resolve the selected provider and the exact model it should receive.

    The endpoint and model are resolved together so callers cannot construct a
    client from one endpoint and submit a model selected from another. Unknown
    protocols fail closed rather than being treated as OpenAI-compatible.
    """
    try:
        from backend.data.settings_canonicalizer import to_camel
        from backend.data.settings_repo import SettingsRepository

        raw = SettingsRepository().get_json("app_settings")
        if not isinstance(raw, dict):
            return None
        settings = to_camel(raw)
        endpoints = settings.get("endpoints") or []
        if not isinstance(endpoints, list):
            return None
        selections = settings.get("modelSelections") or {}
        selection = selections.get("chatModel") if isinstance(selections, dict) else None
        selection = selection if isinstance(selection, dict) else {}
        endpoint_id = selection.get("endpointId")
        endpoint = next(
            (ep for ep in endpoints if isinstance(ep, dict) and endpoint_id and ep.get("id") == endpoint_id),
            None,
        )
        if endpoint_id and endpoint is None:
            return None
        if endpoint is None:
            endpoint = next(
                (
                    ep for ep in endpoints
                    if isinstance(ep, dict)
                    and (ep.get("protocol") or "openai-compatible") in _SUPPORTED_PROTOCOLS
                    and ep.get("baseUrl")
                    and _endpoint_has_required_api_key(ep)
                ),
                None,
            )
        if not isinstance(endpoint, dict) or not endpoint.get("baseUrl"):
            return None

        protocol = endpoint.get("protocol") or "openai-compatible"
        provider_type = _provider_types().get(protocol)
        if provider_type is None or not _endpoint_has_required_api_key(endpoint, protocol=protocol):
            return None
        discovered = endpoint.get("discoveredModels") or []
        discovered_model = (
            discovered[0].get("id")
            if isinstance(discovered, list)
            and discovered
            and isinstance(discovered[0], dict)
            else None
        )
        model = selection.get("modelId") or discovered_model
        if not isinstance(model, str) or not model.strip():
            return None
        provider = provider_type(
            api_key=endpoint.get("apiKey") or "", base_url=endpoint["baseUrl"]
        )
        return provider, model.strip()
    except Exception as exc:
        logger.warning("llm_factory: failed to resolve ProviderClient: %s", exc)
        return None


def resolve_model_from_settings() -> Optional[str]:
    """Return the selected model, or its endpoint's discovered fallback."""
    try:
        from backend.data.settings_canonicalizer import to_camel
        from backend.data.settings_repo import SettingsRepository

        raw = SettingsRepository().get_json("app_settings")
        if not isinstance(raw, dict):
            return None
        settings = to_camel(raw)
        selections = settings.get("modelSelections") or {}
        selection = selections.get("chatModel") if isinstance(selections, dict) else None
        if isinstance(selection, dict):
            model = selection.get("modelId")
            # A model without an endpoint is retained for injected/test callers;
            # endpoint-backed selections must be resolved atomically below.
            if not selection.get("endpointId") and isinstance(model, str) and model.strip():
                return model.strip()
    except Exception as exc:
        logger.warning("llm_factory: failed to resolve selected model: %s", exc)
        return None

    resolved = resolve_provider_and_model_from_settings()
    return resolved[1] if resolved is not None else None


def build_provider_client_from_settings(model: Optional[str] = None) -> Optional[Any]:
    """Build the settings-selected A2 ``ProviderClient``, or ``None``.

    ``model`` is retained for source compatibility; provider construction and
    model resolution intentionally share the same resolver.
    """
    resolved = resolve_provider_and_model_from_settings()
    return resolved[0] if resolved is not None else None


def build_llm_client_from_settings() -> Optional[Any]:
    """Build an ``LLMClient`` from persisted settings, or ``None``.

    Never raises — construction failures are logged and return ``None`` so
    callers can degrade (planner falls back to single-task decomposition).
    """
    cfg = load_llm_config_from_settings()
    if cfg is None:
        return None
    try:
        from backend.core.legacy.llm_client import LLMClient, LLMConfig

        return LLMClient(LLMConfig(**cfg))
    except Exception as exc:
        logger.warning("llm_factory: failed to build LLMClient: %s", exc)
        return None
