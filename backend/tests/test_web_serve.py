"""Tests for web mode static file serving (Task 2)."""

import importlib
import mimetypes

from fastapi.testclient import TestClient

_WEB_MIME_SUFFIXES = (".js", ".mjs", ".css")


def _snapshot_web_mime_types() -> dict:
    return {suffix: mimetypes.guess_type("x" + suffix)[0] for suffix in _WEB_MIME_SUFFIXES}


def _restore_web_mime_types(snapshot: dict) -> None:
    for suffix, mime_type in snapshot.items():
        if mime_type:
            mimetypes.add_type(mime_type, suffix)


def test_register_web_static_mime_types_overrides_polluted_mapping():
    """Windows 注册表把 .js 登记为 text/plain 时，注册后必须回到标准 MIME。"""
    from backend.api.web_static import register_web_static_mime_types

    snapshot = _snapshot_web_mime_types()
    mimetypes.add_type("text/plain", ".js")
    try:
        assert mimetypes.guess_type("main.js")[0] == "text/plain"

        register_web_static_mime_types()

        assert mimetypes.guess_type("main.js")[0] == "text/javascript"
        assert mimetypes.guess_type("chunk.mjs")[0] == "text/javascript"
        assert mimetypes.guess_type("index.css")[0] == "text/css"
    finally:
        _restore_web_mime_types(snapshot)


def test_serves_js_with_javascript_mime_when_registry_mapping_is_polluted(
    monkeypatch, tmp_path
):
    """回归：注册表 .js→text/plain 时，入口 chunk 仍应以 JS MIME 下发。"""
    dist_web = tmp_path / "dist-web"
    assets = dist_web / "assets"
    assets.mkdir(parents=True)
    (dist_web / "index.html").write_text("<html><body>Sage Web</body></html>")
    (assets / "main-test.js").write_text("console.log('sage');")

    snapshot = _snapshot_web_mime_types()
    mimetypes.add_type("text/plain", ".js")
    try:
        monkeypatch.setenv("SAGE_WEB_MODE", "1")
        monkeypatch.setenv("SAGE_WEB_DIST_PATH", str(dist_web))

        import backend.main
        importlib.reload(backend.main)

        client = TestClient(backend.main.app)
        response = client.get("/assets/main-test.js")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/javascript")
    finally:
        _restore_web_mime_types(snapshot)


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

