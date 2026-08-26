"""Settings stub routes.

Routes registered here:

- GET  /api/v1/settings                  — return redacted AppSettings
- PUT  /api/v1/settings                  — accept-and-ignore (stub)
- GET  /api/v1/preferences/{key}        — return {value, value_type, category}
- PUT  /api/v1/preferences/{key}        — accept-and-ignore (stub)

Contract:
    register_settings_routes(registry: dict) -> None

The stub returns a *redacted* settings payload (apiKey → hasApiKey=true) so
the smoke spec doesn't trigger settingsClient auto-migration that would
PUT legacy residue. Smoke tests don't exercise real settings save; real
flow lives in `backend/api/settings_routes.py` + hex/legacy shims.
"""
from __future__ import annotations

from .common import send_json


_STUB_SETTINGS: dict = {
    "version": "0.0.0-stub",
    "streaming": True,
    "autoMemory": False,
    "confirmDelete": True,
    "memoryServerSync": False,
    "endpoints": [],
    "modelSelections": {},
    "maxContext": 8192,
    "temperature": 0.7,
    "timezone": "Asia/Shanghai",
    "wiki": {"enabled": True, "autoIndex": False},
    "orch": {
        "maxIterations": 10,
        "maxSubagentIterations": 6,
        "worktreeIsolation": False,
    },
}


_STUB_PREFERENCES: dict[str, dict] = {
    "app_settings": {"value": None, "value_type": "string", "category": "general"},
    "theme_mode": {"value": "light", "value_type": "string", "category": "ui"},
    "theme_preset": {"value": "default", "value_type": "string", "category": "ui"},
    "current_session_id": {"value": None, "value_type": "string", "category": "session"},
    "permission_mode": {"value": "default", "value_type": "string", "category": "ui"},
    "permission_rules": {"value": "[]", "value_type": "string", "category": "ui"},
}


def register_settings_routes(registry: dict) -> None:
    registry[("GET", r"^/api/v1/settings$")] = _get_settings
    registry[("PUT", r"^/api/v1/settings$")] = _put_settings
    registry[("GET", r"^/api/v1/preferences/(?P<key>[^/]+)$")] = _get_preference
    registry[("PUT", r"^/api/v1/preferences/(?P<key>[^/]+)$")] = _put_preference


def _get_settings(ctx, body, **_):
    send_json(ctx, 200, dict(_STUB_SETTINGS))


def _put_settings(ctx, body, **_):
    # Stub accepts and returns the redacted baseline; real persistence is
    # backend SettingsRepository territory. Returning 200 with redacted
    # shape lets the smoke client never see its own PUT body echoed.
    send_json(ctx, 200, dict(_STUB_SETTINGS))


def _get_preference(ctx, body, key, **_):
    entry = _STUB_PREFERENCES.get(key)
    if entry is None:
        send_json(ctx, 200, {"value": None, "value_type": "string", "category": "ui"})
        return
    send_json(ctx, 200, dict(entry))


def _put_preference(ctx, body, key, **_):
    _STUB_PREFERENCES[key] = {
        "value": body.get("value"),
        "value_type": body.get("value_type", "string"),
        "category": body.get("category", "ui"),
    }
    send_json(ctx, 200, dict(_STUB_PREFERENCES[key]))