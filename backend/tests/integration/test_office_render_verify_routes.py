"""Integration tests for the M1 render & verify endpoint.

The endpoint is exercised through the real FastAPI stack; the PDF
converter is monkeypatched because CI has no LibreOffice.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.office.export_pdf import ExportPdfResult


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


def _make_pdf(path: Path, *, width: float = 595.28, height: float = 841.89) -> Path:
    import fitz

    document = fitz.open()
    try:
        page = document.new_page(width=width, height=height)
        page.insert_text((100, 100), "Hello", fontname="helv", fontsize=12)
        document.save(str(path))
    finally:
        document.close()
    return path


def _fake_export(pdf_path: Path):
    def exporter(source: Path, workspace: Path, *, timeout_seconds: int = 120):
        return ExportPdfResult(ok=True, method="libreoffice", output_path=str(pdf_path))

    return exporter


def test_render_verify_endpoint_returns_passed(
    workspace: Path, http_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = workspace / "doc.docx"
    source.write_bytes(b"not really docx")
    pdf = _make_pdf(workspace / "doc.pdf")
    monkeypatch.setattr("backend.office.render_verify.export_to_pdf", _fake_export(pdf))

    response = http_client.post(
        "/api/v1/office/render/verify",
        json={
            "workspace_path": str(workspace),
            "file_path": str(source),
            "expected_size": "A4",
            "thumbnail_pages": 1,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "passed"
    assert body["rendered"] is True
    assert body["page_count"] == 1
    assert body["summary"]["pages"] == 1
    assert body["thumbnails"][0].startswith("data:image/jpeg;base64,")


def test_render_verify_endpoint_degrades_without_converter(
    workspace: Path, http_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = workspace / "doc.docx"
    source.write_bytes(b"not really docx")

    def failing_export(source: Path, workspace: Path, *, timeout_seconds: int = 120):
        return ExportPdfResult(ok=False, error="no soffice")

    monkeypatch.setattr("backend.office.render_verify.export_to_pdf", failing_export)

    response = http_client.post(
        "/api/v1/office/render/verify",
        json={"workspace_path": str(workspace), "file_path": str(source)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["rendered"] is False
    assert any(w["code"] == "render_unavailable" for w in body["warnings"])


def test_render_verify_endpoint_rejects_outside_workspace(
    tmp_path: Path, http_client: TestClient
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "outside.docx"
    outside.write_bytes(b"not really docx")

    response = http_client.post(
        "/api/v1/office/render/verify",
        json={"workspace_path": str(workspace), "file_path": str(outside)},
    )

    assert response.status_code == 400


def test_render_verify_endpoint_rejects_unsupported_suffix(
    workspace: Path, http_client: TestClient
) -> None:
    source = workspace / "notes.txt"
    source.write_text("text", encoding="utf-8")

    response = http_client.post(
        "/api/v1/office/render/verify",
        json={"workspace_path": str(workspace), "file_path": str(source)},
    )

    assert response.status_code == 422
