"""Integration tests for M5 OOXML endpoints."""

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


def _docx(workspace: Path) -> Path:
    from docx import Document

    document = Document()
    paragraph = document.add_paragraph()
    paragraph.add_run("Hello")
    paragraph.add_run(" ")
    paragraph.add_run("world")
    path = workspace / "doc.docx"
    document.save(str(path))
    return path


def test_ooxml_validate_endpoint(workspace: Path, http_client: TestClient) -> None:
    source = _docx(workspace)

    response = http_client.post(
        "/api/v1/office/ooxml/validate",
        json={"workspace_path": str(workspace), "file_path": str(source)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["ok"] is True


def test_ooxml_merge_runs_endpoint(workspace: Path, http_client: TestClient) -> None:
    source = _docx(workspace)

    response = http_client.post(
        "/api/v1/office/ooxml/merge-runs",
        json={"workspace_path": str(workspace), "file_path": str(source)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["merged_runs"] == 2
    from docx import Document

    merged = Document(str(workspace / body["output_path"]))
    assert len(merged.paragraphs[0].runs) == 1


def test_ooxml_validate_rejects_outside_workspace(
    tmp_path: Path, http_client: TestClient
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "outside.docx"
    outside.write_bytes(b"not a docx")

    response = http_client.post(
        "/api/v1/office/ooxml/validate",
        json={"workspace_path": str(workspace), "file_path": str(outside)},
    )

    assert response.status_code == 400
