"""Tests for theme REST API (7 endpoints)."""

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.theme_router import get_storage, router as theme_router
from backend.services.theme_storage import ThemeStorage


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    """Provide a FastAPI TestClient with a fresh ThemeStorage in tmp_path."""
    # Write defaults so storage can seed
    defaults = [
        {"id": "light", "name": "n", "description": "d", "cover": "/l.png"},
        {"id": "dark", "name": "n", "description": "d", "cover": "/d.png"},
    ]
    (tmp_path / "themes.defaults.json").write_text(json.dumps(defaults), encoding="utf-8")
    # ThemeStorage needs to know about tmp_path; expose via dependency override
    storage = ThemeStorage(tmp_path)
    app = FastAPI()
    # Override the storage dependency
    app.dependency_overrides[get_storage] = lambda: storage
    app.include_router(theme_router, prefix="/api/v1/theme")
    # Mirror what register_routers() does in production: install the unified
    # validation-error handler so pydantic ValidationError returns 200+envelope.
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse

    from backend.schemas.common import ApiError

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request, exc):
        err = ApiError(
            error="Validation failed",
            code="VALIDATION_ERROR",
            details={"errors": exc.errors()},
        )
        return JSONResponse(status_code=200, content=err.model_dump())

    return TestClient(app)


# --- list ---


def test_list_returns_seeded_presets(client: TestClient):
    resp = client.get("/api/v1/theme/list")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert len(data["data"]) == 2
    assert {p["id"] for p in data["data"]} == {"light", "dark"}


# --- get ---


def test_get_existing_returns_preset(client: TestClient):
    resp = client.get("/api/v1/theme/get/light")
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == "light"


def test_get_missing_returns_404_envelope(client: TestClient):
    resp = client.get("/api/v1/theme/get/nope")
    assert resp.status_code == 200  # business 404 in envelope
    body = resp.json()
    assert body["success"] is False
    assert body["code"] == "THEME_NOT_FOUND"


# --- save ---


def test_save_new_preset_returns_created(client: TestClient):
    new_preset = {"id": "ocean", "name": "n", "description": "d"}
    resp = client.post("/api/v1/theme/save", json=new_preset)
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == "ocean"


def test_save_invalid_id_returns_400_envelope(client: TestClient):
    bad = {"id": "INVALID!", "name": "n", "description": "d"}
    resp = client.post("/api/v1/theme/save", json=bad)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert body["code"] == "VALIDATION_ERROR"


# --- delete ---


def test_delete_existing_returns_success(client: TestClient):
    resp = client.delete("/api/v1/theme/delete/light")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_delete_missing_returns_404_envelope(client: TestClient):
    resp = client.delete("/api/v1/theme/delete/nope")
    body = resp.json()
    assert body["success"] is False
    assert body["code"] == "THEME_NOT_FOUND"


# --- active ---


def test_get_active_default(client: TestClient):
    resp = client.get("/api/v1/theme/active")
    assert resp.status_code == 200
    assert resp.json()["data"]["presetId"] == "light"


def test_save_active_then_get_roundtrips(client: TestClient):
    payload = {"presetId": "dark", "customCss": ":root {}"}
    put_resp = client.put("/api/v1/theme/active", json=payload)
    assert put_resp.status_code == 200
    get_resp = client.get("/api/v1/theme/active")
    assert get_resp.json()["data"]["presetId"] == "dark"


# --- validate ---


def test_validate_clean_css_returns_valid(client: TestClient):
    css = ":root { --color-bg: #fff; }"
    resp = client.post("/api/v1/theme/validate", json={"css": css})
    assert resp.status_code == 200
    assert resp.json()["data"]["valid"] is True


def test_validate_import_returns_invalid(client: TestClient):
    css = '@import url("evil.css");'
    resp = client.post("/api/v1/theme/validate", json={"css": css})
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["valid"] is False
    assert any("import" in e.lower() for e in body["data"]["errors"])
