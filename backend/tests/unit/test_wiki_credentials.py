"""backend/api/wiki_credentials.py 单测（2026-11-15 凭据兜底）。"""

from __future__ import annotations

from typing import Any

import pytest

from backend.api.wiki_credentials import resolve_llm_api_key

BASE = "https://api.example.com/v1"


def _patch_settings(monkeypatch: pytest.MonkeyPatch, payload: Any) -> None:
    from backend.data.settings_repo import SettingsRepository

    monkeypatch.setattr(SettingsRepository, "get_json", lambda self, key: payload)


def test_non_empty_provided_key_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(
        monkeypatch,
        {"endpoints": [{"id": "ep-1", "baseUrl": BASE, "apiKey": "sk-stored"}]},
    )
    assert resolve_llm_api_key(BASE, "sk-provided") == "sk-provided"


def test_empty_key_resolves_from_stored_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(
        monkeypatch,
        {
            "endpoints": [
                {"id": "ep-1", "baseUrl": BASE + "/", "apiKey": "sk-stored"},
            ]
        },
    )
    # 尾部斜杠与大小写差异不影响匹配
    assert resolve_llm_api_key("https://API.EXAMPLE.com/v1", "") == "sk-stored"


def test_blank_provided_key_is_treated_as_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(
        monkeypatch,
        {"endpoints": [{"id": "ep-1", "baseUrl": BASE, "apiKey": "sk-stored"}]},
    )
    assert resolve_llm_api_key(BASE, "   ") == "sk-stored"


def test_no_matching_endpoint_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(
        monkeypatch,
        {"endpoints": [{"id": "ep-1", "baseUrl": "https://other.test/v1", "apiKey": "sk"}]},
    )
    assert resolve_llm_api_key(BASE, "") == ""


def test_snake_case_payload_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(
        monkeypatch,
        {"endpoints": [{"id": "ep-1", "base_url": BASE, "api_key": "sk-stored"}]},
    )
    assert resolve_llm_api_key(BASE, "") == "sk-stored"


def test_db_failure_degrades_to_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.data.settings_repo import SettingsRepository

    def _boom(self: Any, key: str) -> Any:
        raise RuntimeError("db down")

    monkeypatch.setattr(SettingsRepository, "get_json", _boom)
    assert resolve_llm_api_key(BASE, "") == ""


def test_non_dict_settings_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, None)
    assert resolve_llm_api_key(BASE, "") == ""
