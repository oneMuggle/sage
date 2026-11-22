"""Integration test for M6b PDF embedded-image reading."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture()
def http_client() -> TestClient:
    return TestClient(
        app,
        headers={"X-Sage-Local-Authorization": "Bearer test-local-auth-token"},
    )


def _pdf_with_image(workspace: Path) -> Path:
    import pymupdf
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (20, 20), "red").save(buffer, format="PNG")
    path = workspace / "with-image.pdf"
    document = pymupdf.open()
    try:
        page = document.new_page(width=400, height=300)
        page.insert_image(pymupdf.Rect(50, 50, 150, 150), stream=buffer.getvalue())
        document.save(str(path))
    finally:
        document.close()
    return path


def test_pdf_read_endpoint_returns_embedded_images(
    workspace: Path, http_client: TestClient
) -> None:
    source = _pdf_with_image(workspace)

    response = http_client.post(
        "/api/v1/office/pdf/read",
        json={
            "workspace_path": str(workspace),
            "file_path": str(source),
            "include_images": True,
            "max_images_per_page": 2,
        },
    )

    assert response.status_code == 200
    page = response.json()["pages"][0]
    assert page["image_count"] == 1
    assert len(page["images"]) == 1
    assert page["images"][0]["data_url"].startswith("data:image/")
