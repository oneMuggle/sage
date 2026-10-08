# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""ArtifactRepository 与 classify_artifact 契约单测（R186 + F1）。"""

from __future__ import annotations

import json

import pytest

from backend.data.artifact_repo import ArtifactRepository, classify_artifact
from backend.data.database import Database

pytestmark = pytest.mark.unit


@pytest.fixture()
def repo(tmp_path):
    db = Database(db_path=str(tmp_path / "artifacts_test.db"))
    db.init_db()
    try:
        yield ArtifactRepository(db)
    finally:
        db.close()


@pytest.mark.parametrize(
    ("file_path", "expected_kind"),
    [
        ("/tmp/readme.md", "markdown"),
        ("/tmp/doc.mdx", "markdown"),
        ("/tmp/main.py", "code"),
        ("/tmp/Component.tsx", "code"),
        ("/tmp/chart.png", "image"),
        ("/tmp/table.csv", "csv"),
        ("/tmp/config.json", "json"),
        ("/tmp/paper.pdf", "pdf"),
        ("/tmp/report.docx", "docx"),
        ("/tmp/sheet.xlsx", "xlsx"),
        ("/tmp/slides.pptx", "pptx"),
        ("/tmp/notes.unknown", "text"),
    ],
)
def test_classify_artifact_by_extension(file_path: str, expected_kind: str) -> None:
    assert classify_artifact(file_path) == expected_kind


def test_record_and_get_artifact_with_office_metadata(repo: ArtifactRepository) -> None:
    spec_json = json.dumps({"page_size": "A4", "font_name": "SimSun"}, ensure_ascii=False)
    created = repo.record_artifact(
        session_id="sess-1",
        path="/workspace/out/thesis.docx",
        name="thesis.docx",
        kind="docx",
        size=4096,
        tool_call_id="tc-1",
        workspace_path="/workspace/out",
        format_spec=spec_json,
    )
    assert created["session_id"] == "sess-1"
    assert created["workspace_path"] == "/workspace/out"
    assert created["format_spec"] == spec_json

    loaded = repo.get_artifact(created["id"])
    assert loaded is not None
    assert loaded["id"] == created["id"]
    assert loaded["name"] == "thesis.docx"
    assert loaded["kind"] == "docx"
    assert loaded["size"] == 4096
    assert loaded["workspace_path"] == "/workspace/out"
    assert loaded["format_spec"] == spec_json


def test_record_artifact_upserts_by_session_and_path_preserving_metadata(
    repo: ArtifactRepository,
) -> None:
    first = repo.record_artifact(
        session_id="sess-1",
        path="/workspace/out/report.docx",
        name="report.docx",
        kind="docx",
        size=1024,
        tool_call_id="tc-1",
        workspace_path="/workspace/out",
        format_spec='{"font_size":12}',
    )
    # Subsequent update without workspace_path/format_spec keeps existing metadata via COALESCE
    second = repo.record_artifact(
        session_id="sess-1",
        path="/workspace/out/report.docx",
        name="report.docx",
        kind="docx",
        size=2048,
        tool_call_id="tc-2",
    )
    assert second["id"] == first["id"]

    rows = repo.list_by_session("sess-1")
    assert len(rows) == 1
    assert rows[0]["size"] == 2048
    assert rows[0]["tool_call_id"] == "tc-2"
    assert rows[0]["workspace_path"] == "/workspace/out"
    assert rows[0]["format_spec"] == '{"font_size":12}'


def test_list_and_delete_by_session_isolates_sessions(repo: ArtifactRepository) -> None:
    repo.record_artifact(
        session_id="sess-a",
        path="/workspace/a1.py",
        name="a1.py",
        kind="code",
        size=100,
    )
    repo.record_artifact(
        session_id="sess-b",
        path="/workspace/b1.py",
        name="b1.py",
        kind="code",
        size=200,
    )
    assert [r["name"] for r in repo.list_by_session("sess-a")] == ["a1.py"]
    assert [r["name"] for r in repo.list_by_session("sess-b")] == ["b1.py"]

    deleted = repo.delete_by_session("sess-a")
    assert deleted == 1
    assert repo.list_by_session("sess-a") == []
    assert len(repo.list_by_session("sess-b")) == 1
