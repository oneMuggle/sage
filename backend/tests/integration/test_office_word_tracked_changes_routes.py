"""Integration tests for M3 Word tracked-changes endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document
from fastapi.testclient import TestClient

from backend.main import app
from backend.office.word_revision_writer import apply_word_revisions


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


def _revised_doc(workspace: Path) -> Path:
    source = workspace / "source.docx"
    document = Document()
    document.add_paragraph("Hello AI")
    document.save(str(source))
    result = apply_word_revisions(
        source,
        [{"find": "AI", "replace": "人工智能"}],
        "revised.docx",
        workspace_path=str(workspace),
        add_comments=False,
    )
    assert result.applied == 1
    return workspace / "revised.docx"


def test_tracked_changes_endpoint_reads_revisions(
    workspace: Path, http_client: TestClient
) -> None:
    revised = _revised_doc(workspace)

    response = http_client.post(
        "/api/v1/office/word/tracked-changes",
        json={"workspace_path": str(workspace), "file_path": str(revised)},
    )

    assert response.status_code == 200
    body = response.json()
    assert {change["kind"] for change in body["changes"]} == {"insert", "delete"}
    assert body["source_path"] == "revised.docx"


def test_tracked_changes_resolve_endpoint_accepts(
    workspace: Path, http_client: TestClient
) -> None:
    revised = _revised_doc(workspace)

    response = http_client.post(
        "/api/v1/office/word/tracked-changes/resolve",
        json={
            "workspace_path": str(workspace),
            "file_path": str(revised),
            "mode": "accept",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "accept"
    assert body["insertions"] == 1
    assert body["deletions"] == 1
    accepted = Document(str(workspace / body["output_path"]))
    assert accepted.paragraphs[0].text == "Hello 人工智能"
