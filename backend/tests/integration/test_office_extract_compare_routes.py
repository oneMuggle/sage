"""Integration tests for M6b extraction and compare endpoints."""

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


def _docx(path: Path, text: str) -> Path:
    from docx import Document

    document = Document()
    document.add_paragraph(text)
    document.save(str(path))
    return path


def test_extract_endpoint_returns_structured_document(
    workspace: Path, http_client: TestClient
) -> None:
    source = _docx(workspace / "doc.docx", "Hello extract")

    response = http_client.post(
        "/api/v1/office/extract",
        json={
            "workspace_path": str(workspace),
            "file_path": str(source),
            "backend": "light",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["extractor"] == "light"
    assert "Hello extract" in body["document"]["markdown"]
    assert body["document"]["source_path"] == "doc.docx"


def test_compare_endpoint_returns_diff_report(
    workspace: Path, http_client: TestClient
) -> None:
    left = _docx(workspace / "left.docx", "Hello world")
    right = _docx(workspace / "right.docx", "Hello brave world")

    response = http_client.post(
        "/api/v1/office/compare",
        json={
            "workspace_path": str(workspace),
            "left_path": str(left),
            "right_path": str(right),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["added"] >= 1
    assert body["summary"]["removed"] >= 1
    assert "```diff" in body["report_markdown"]


def test_extract_rejects_outside_workspace(
    tmp_path: Path, http_client: TestClient
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = _docx(tmp_path / "outside.docx", "x")

    response = http_client.post(
        "/api/v1/office/extract",
        json={"workspace_path": str(workspace), "file_path": str(outside)},
    )

    assert response.status_code == 400
