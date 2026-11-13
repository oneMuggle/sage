"""Tests for web mode static file serving (Task 2)."""

import importlib

from fastapi.testclient import TestClient


def test_serves_index_html_in_web_mode(monkeypatch, tmp_path):
    """In web mode, GET / should serve dist-web/index.html."""
    # Create temporary dist-web directory with index.html
    dist_web = tmp_path / "dist-web"
    dist_web.mkdir()
    (dist_web / "index.html").write_text("<html><body>Sage Web</body></html>")

    # Set env vars BEFORE reload so they survive module re-execution
    monkeypatch.setenv("SAGE_WEB_MODE", "1")
    monkeypatch.setenv("SAGE_WEB_DIST_PATH", str(dist_web))

    import backend.main
    importlib.reload(backend.main)

    client = TestClient(backend.main.app)
    response = client.get("/")
    assert response.status_code == 200
    assert "Sage Web" in response.text


def test_no_mount_when_not_web_mode(monkeypatch, tmp_path):
    """Without SAGE_WEB_MODE, GET / should NOT serve static files (404 or other)."""
    dist_web = tmp_path / "dist-web"
    dist_web.mkdir()
    (dist_web / "index.html").write_text("<html><body>Should Not See</body></html>")

    monkeypatch.delenv("SAGE_WEB_MODE", raising=False)
    monkeypatch.setenv("SAGE_WEB_DIST_PATH", str(dist_web))

    import backend.main
    importlib.reload(backend.main)

    client = TestClient(backend.main.app)
    response = client.get("/")
    # Should NOT get the static file — either 404 or some other non-200
    assert response.status_code != 200 or "Should Not See" not in response.text


def test_warns_when_dist_web_missing(monkeypatch, tmp_path, caplog):
    """When web mode is on but dist-web doesn't exist, should log a warning."""
    import logging
    nonexistent = tmp_path / "does-not-exist"

    monkeypatch.setenv("SAGE_WEB_MODE", "1")
    monkeypatch.setenv("SAGE_WEB_DIST_PATH", str(nonexistent))

    import backend.main
    with caplog.at_level(logging.WARNING, logger="backend.main"):
        importlib.reload(backend.main)

    # Should have logged a warning about missing dist-web
    assert any("dist-web" in record.message.lower() or "not found" in record.message.lower()
               for record in caplog.records)

