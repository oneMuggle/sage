"""Integration tests for M6 PDF page-operation endpoints."""

from __future__ import annotations

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


def _pdf(path: Path, text: str) -> Path:
    import fitz

    document = fitz.open()
    try:
        page = document.new_page(width=400, height=300)
        page.insert_text((50, 50), text, fontname="helv", fontsize=12)
        document.save(str(path))
    finally:
        document.close()
    return path


def _text(path: Path) -> str:
    import fitz

    document = fitz.open(str(path))
    try:
        return "\n".join(page.get_text() for page in document)
    finally:
        document.close()


def test_pdf_page_numbers_endpoint(workspace: Path, http_client: TestClient) -> None:
    source = _pdf(workspace / "doc.pdf", "Hello")

    response = http_client.post(
        "/api/v1/office/pdf/page-numbers",
        json={"workspace_path": str(workspace), "file_path": str(source), "template": "P{n}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["outputs"] == ["doc-numbered.pdf"]
    assert "P1" in _text(workspace / body["outputs"][0])


def test_pdf_merge_endpoint(workspace: Path, http_client: TestClient) -> None:
    first = _pdf(workspace / "a.pdf", "Alpha")
    second = _pdf(workspace / "b.pdf", "Beta")

    response = http_client.post(
        "/api/v1/office/pdf/merge",
        json={
            "workspace_path": str(workspace),
            "file_paths": [str(first), str(second)],
            "output_filename": "merged.pdf",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["page_count"] == 2
    text = _text(workspace / body["outputs"][0])
    assert "Alpha" in text
    assert "Beta" in text
