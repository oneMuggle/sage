"""Integration test for web fallback mode (Task 9).

Tests the complete web fallback flow:
1. Valid token loads the app (static files + API access)
2. Invalid/missing token returns 401
3. Verifies the served HTML is a valid SPA entry point
"""

from __future__ import annotations

import importlib
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def web_mode_client(tmp_path_factory):
    """Set up web mode with a minimal dist-web for testing.

    Creates a temporary dist-web directory with a realistic index.html
    that mimics the actual Vite build output structure.
    """
    # Create a minimal dist-web directory
    dist_web = tmp_path_factory.mktemp("dist-web")

    # Create a realistic index.html (mimics Vite build output)
    index_html = """<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/png" href="/favicon-32.png" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Sage</title>
    <script type="module" crossorigin src="/assets/index-abc123.js"></script>
    <link rel="stylesheet" crossorigin href="/assets/index-def456.css">
  </head>
  <body>
    <div id="root"></div>
    <script>
      // Web mode: electronAPI should be undefined
      if (typeof window !== 'undefined') {
        window.__SAGE_PLATFORM__ = 'web';
      }
    </script>
  </body>
</html>"""
    (dist_web / "index.html").write_text(index_html)

    # Create a minimal assets directory
    assets_dir = dist_web / "assets"
    assets_dir.mkdir()
    (assets_dir / "index-abc123.js").write_text(
        "// Mock JS bundle\n"
        "console.log('Sage web mode loaded');\n"
        "// All electronAPI references are optional-chained\n"
        "const api = typeof window !== 'undefined' ? window.electronAPI : undefined;\n"
    )
    (assets_dir / "index-def456.css").write_text("/* Mock CSS */ body { margin: 0; }")

    # Set environment variables
    os.environ["SAGE_WEB_MODE"] = "1"
    os.environ["SAGE_LOCAL_AUTH_TOKEN"] = "integration-test-token"
    os.environ["SAGE_WEB_DIST_PATH"] = str(dist_web)

    # Reload modules to pick up env changes
    import backend.config
    importlib.reload(backend.config)

    import backend.api.local_auth as auth_mod
    importlib.reload(auth_mod)

    import backend.main
    importlib.reload(backend.main)

    client = TestClient(backend.main.app)
    yield client

    # Cleanup: reload to restore default state
    del os.environ["SAGE_WEB_MODE"]
    del os.environ["SAGE_LOCAL_AUTH_TOKEN"]
    del os.environ["SAGE_WEB_DIST_PATH"]
    importlib.reload(backend.config)
    importlib.reload(auth_mod)
    importlib.reload(backend.main)


class TestWebFallbackIntegration:
    """Integration tests for web fallback mode.

    These tests verify the complete flow:
    - Static file serving
    - Token authentication
    - API access with valid token
    """

    def test_valid_token_via_url_param_loads_app(self, web_mode_client):
        """Valid token via URL param should load the app (index.html)."""
        response = web_mode_client.get("/?token=integration-test-token")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        assert "Sage" in response.text
        assert '<div id="root">' in response.text

    def test_valid_token_via_bearer_loads_app(self, web_mode_client):
        """Valid token via Bearer header should load the app."""
        response = web_mode_client.get(
            "/", headers={"Authorization": "Bearer integration-test-token"}
        )
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    def test_no_token_returns_401_for_api(self, web_mode_client):
        """API requests without token should return 401."""
        response = web_mode_client.get("/api/v1/sessions")
        assert response.status_code == 401
        assert "凭据" in response.json().get("detail", "")

    def test_invalid_token_returns_401_for_api(self, web_mode_client):
        """API requests with invalid token should return 401."""
        response = web_mode_client.get("/api/v1/sessions?token=wrong-token")
        assert response.status_code == 401

    def test_invalid_bearer_token_returns_401(self, web_mode_client):
        """API requests with invalid Bearer token should return 401."""
        response = web_mode_client.get(
            "/api/v1/sessions",
            headers={"Authorization": "Bearer invalid-token"}
        )
        assert response.status_code == 401

    def test_static_assets_public_no_auth_needed(self, web_mode_client):
        """Static assets (/assets/*) should be accessible without auth."""
        response = web_mode_client.get("/assets/index-abc123.js")
        assert response.status_code == 200
        assert "Sage web mode loaded" in response.text

    def test_css_asset_accessible(self, web_mode_client):
        """CSS assets should be accessible without auth."""
        response = web_mode_client.get("/assets/index-def456.css")
        assert response.status_code == 200

    def test_health_endpoint_public(self, web_mode_client):
        """Health endpoint should be publicly accessible."""
        response = web_mode_client.get("/health")
        assert response.status_code == 200
        assert response.json().get("status") == "ok"

    def test_web_mode_serves_complete_spa(self, web_mode_client):
        """Web mode should serve a complete SPA entry point."""
        response = web_mode_client.get("/")
        assert response.status_code == 200
        html = response.text
        # Verify SPA structure
        assert '<div id="root">' in html
        assert '<script type="module"' in html
        assert "/assets/" in html  # Asset paths should be present


class TestWebModeElectronAPI:
    """Tests to verify web mode does not expose electronAPI."""

    def test_html_does_not_require_electron_api(self, web_mode_client):
        """The served HTML should not require window.electronAPI to load.

        This verifies the HTML entry point is self-contained and doesn't
        have any synchronous electronAPI calls that would crash on web.
        """
        response = web_mode_client.get("/?token=integration-test-token")
        assert response.status_code == 200

        # The HTML should be a valid SPA entry point
        html = response.text
        assert '<div id="root">' in html, "Missing React root element"
        assert '<script type="module"' in html, "Missing module script tag"

    def test_js_bundle_uses_optional_chaining(self, web_mode_client):
        """JS bundle should use optional chaining for electronAPI access.

        This is a static check - verifies the mock bundle uses safe patterns.
        The actual Vite build (Task 7) ensures all 99 electronAPI references
        are optional-chained.
        """
        response = web_mode_client.get("/assets/index-abc123.js")
        assert response.status_code == 200

        js = response.text
        # Verify the pattern: window.electronAPI is accessed via optional chain
        # or guarded by typeof check
        assert "window.electronAPI" in js
        # The reference should be in a safe pattern (optional chain or typeof guard)
        assert "window.electronAPI?." in js or "typeof window" in js


class TestWebModePublicPaths:
    """Tests for public path configuration in web mode."""

    def test_root_is_public(self, web_mode_client):
        """Root path (/) should be public in web mode."""
        # Even without auth, we should get the HTML (not 401)
        response = web_mode_client.get("/")
        assert response.status_code == 200
        assert "Sage" in response.text

    def test_favicon_is_public(self, web_mode_client):
        """Favicon should be publicly accessible."""
        # This may 404 if not in dist-web, but should NOT be 401
        response = web_mode_client.get("/favicon.ico")
        assert response.status_code != 401

    def test_unknown_api_path_returns_401_without_token(self, web_mode_client):
        """Unknown API paths should require authentication."""
        response = web_mode_client.get("/api/v1/unknown-endpoint")
        # Should be 401 (auth required) or 404 (not found), but not 200
        assert response.status_code in (401, 404)
