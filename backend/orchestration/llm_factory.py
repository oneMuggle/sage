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

    if not isinstance(endpoint, dict) or not endpoint.get("apiKey") or not endpoint.get("baseUrl"):
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
