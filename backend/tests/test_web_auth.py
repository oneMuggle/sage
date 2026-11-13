"""Tests for web-mode extensions to LocalAuthMiddleware (Task 3)."""

from __future__ import annotations

import importlib

import pytest
from fastapi import Request


@pytest.fixture()
def web_mode(monkeypatch):
    """Activate web mode with a known token for the duration of the test."""
    monkeypatch.setenv("SAGE_WEB_MODE", "1")
    monkeypatch.setenv("SAGE_LOCAL_AUTH_TOKEN", "test-token-abc")
    # Reload to pick up env changes where module-level caching occurs
    import backend.api.local_auth as auth_mod
    importlib.reload(auth_mod)
    yield auth_mod
    # Reload again to restore default state for other tests
    monkeypatch.delenv("SAGE_WEB_MODE", raising=False)
    importlib.reload(auth_mod)


def test_url_param_token_accepted_in_web_mode(web_mode, monkeypatch):
    """?token=<valid> is accepted as Bearer-equivalent in web mode."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/sessions",
        "query_string": b"token=test-token-abc",
        "headers": [],  # No Authorization header
    }
    request = Request(scope)
    assert web_mode.is_local_auth_valid(request) is True


def test_url_param_token_rejected_when_wrong(web_mode, monkeypatch):
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/sessions",
        "query_string": b"token=wrong-token",
        "headers": [],
    }
    request = Request(scope)
    assert web_mode.is_local_auth_valid(request) is False


def test_url_param_token_ignored_in_desktop_mode(monkeypatch):
    """In desktop mode (no SAGE_WEB_MODE), URL param token has no effect."""
    monkeypatch.setenv("SAGE_LOCAL_AUTH_TOKEN", "test-token-abc")
    # Ensure SAGE_WEB_MODE is NOT set
    monkeypatch.delenv("SAGE_WEB_MODE", raising=False)
    import backend.api.local_auth as auth_mod
    importlib.reload(auth_mod)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/sessions",
        "query_string": b"token=test-token-abc",
        "headers": [],
    }
    request = Request(scope)
    assert auth_mod.is_local_auth_valid(request) is False


def test_static_paths_public_in_web_mode(web_mode):
    assert web_mode.is_public_path("/") is True
    assert web_mode.is_public_path("/assets/index-abc.js") is True
    assert web_mode.is_public_path("/favicon.ico") is True


def test_static_paths_not_public_in_desktop_mode(monkeypatch):
    monkeypatch.delenv("SAGE_WEB_MODE", raising=False)
    import backend.api.local_auth as auth_mod
    importlib.reload(auth_mod)
    assert auth_mod.is_public_path("/") is False
    assert auth_mod.is_public_path("/assets/index.js") is False


def test_bearer_still_works_in_web_mode(web_mode):
    """Existing Bearer auth must still work in web mode (no regression)."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/sessions",
        "query_string": b"",
        "headers": [(b"authorization", b"Bearer test-token-abc")],
    }
    request = Request(scope)
    assert web_mode.is_local_auth_valid(request) is True


def test_health_always_public(web_mode):
    assert web_mode.is_public_path("/health") is True
    assert web_mode.is_public_path("/health/proof") is True
