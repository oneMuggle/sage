# backend/tests/api/test_artifact_routes.py
import hashlib
from pathlib import Path

import pytest

from backend.data import artifact_repo


@pytest.mark.asyncio()
async def test_list_artifacts_empty(client):
    resp = await client.get("/api/v1/sessions/sess_test/artifacts")
    assert resp.status_code == 200
    assert resp.json() == {"artifacts": []}


@pytest.mark.asyncio()
async def test_list_artifacts_returns_recorded(client):
    artifact_repo.record_artifact("sess_test", "/tmp/a.md", "a.md", "markdown", 10)
    resp = await client.get("/api/v1/sessions/sess_test/artifacts")
    assert resp.status_code == 200
    items = resp.json()["artifacts"]
    assert len(items) == 1
    assert items[0]["name"] == "a.md"


@pytest.mark.asyncio()
async def test_content_404_for_missing(client):
    resp = await client.get("/api/v1/sessions/sess_test/artifacts/nope/content")
    assert resp.status_code == 404


@pytest.mark.asyncio()
async def test_content_404_for_wrong_session(client):
    aid = artifact_repo.record_artifact("sess_a", "/tmp/a.md", "a.md", "markdown", 10)
    resp = await client.get(f"/api/v1/sessions/sess_other/artifacts/{aid}/content")
    assert resp.status_code == 404


@pytest.mark.asyncio()
async def test_reveal_404_for_missing(client):
    resp = await client.post("/api/v1/sessions/sess_test/artifacts/nope/reveal")
    assert resp.status_code == 404


# ==================== Version History (Phase 2 M2) ====================


def _make_artifact_with_versions(tmp_path: Path, session_id: str = "sess_v"):
    """Helper: create an artifact on disk and 2 versions in the DB."""
    from backend.data import artifact_version_repo

    content_file = tmp_path / "doc.md"
    content_file.write_text("# v1 content\n", encoding="utf-8")

    aid = artifact_repo.record_artifact(
        session_id=session_id,
        path=str(content_file),
        name="doc.md",
        kind="text",
        size=len("# v1 content\n"),
    )
    snapshot_dir = str(content_file.parent / ".snapshots")

    artifact_version_repo.create_version(
        artifact_id=aid,
        content="# v1 content\n",
        content_hash=hashlib.sha256("# v1 content\n".encode()).hexdigest(),
        snapshot_dir=snapshot_dir,
        note="v1",
    )
    artifact_version_repo.create_version(
        artifact_id=aid,
        content="# v2 content\n",
        content_hash=hashlib.sha256("# v2 content\n".encode()).hexdigest(),
        snapshot_dir=snapshot_dir,
        note="v2",
    )
    return aid, content_file


@pytest.mark.asyncio()
async def test_list_versions_404_for_missing(client):
    resp = await client.get("/api/v1/sessions/sess_test/artifacts/nope/versions")
    assert resp.status_code == 404


@pytest.mark.asyncio()
async def test_list_versions_404_for_wrong_session(client, tmp_path):
    aid, _ = _make_artifact_with_versions(tmp_path, session_id="sess_a")
    resp = await client.get(f"/api/v1/sessions/sess_b/artifacts/{aid}/versions")
    assert resp.status_code == 404


@pytest.mark.asyncio()
async def test_list_versions_returns_metadata(client, tmp_path):
    aid, _ = _make_artifact_with_versions(tmp_path)
    resp = await client.get(f"/api/v1/sessions/sess_v/artifacts/{aid}/versions")
    assert resp.status_code == 200
    versions = resp.json()["versions"]
    assert len(versions) == 2
    # DESC order: v2 first
    assert versions[0]["version_num"] == 2
    assert versions[0]["note"] == "v2"
    assert versions[1]["version_num"] == 1
    # Metadata only, no content in list
    assert "content" not in versions[0]


@pytest.mark.asyncio()
async def test_get_version_returns_content(client, tmp_path):
    aid, _ = _make_artifact_with_versions(tmp_path)
    resp = await client.get(f"/api/v1/sessions/sess_v/artifacts/{aid}/versions/1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["version_num"] == 1
    assert body["content"] == "# v1 content\n"


@pytest.mark.asyncio()
async def test_get_version_404_for_missing_version(client, tmp_path):
    aid, _ = _make_artifact_with_versions(tmp_path)
    resp = await client.get(f"/api/v1/sessions/sess_v/artifacts/{aid}/versions/999")
    assert resp.status_code == 404


@pytest.mark.asyncio()
async def test_restore_creates_new_version(client, tmp_path):
    aid, _ = _make_artifact_with_versions(tmp_path)

    resp = await client.post(
        f"/api/v1/sessions/sess_v/artifacts/{aid}/versions/restore",
        json={"version_num": 1, "note": "restored to v1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["restored_from"] == 1
    # New version should be v3 (after v1, v2)
    assert body["new_version"]["version_num"] == 3
    assert body["new_version"]["note"] == "restored to v1"

    # The new version's content should match v1
    resp2 = await client.get(f"/api/v1/sessions/sess_v/artifacts/{aid}/versions/3")
    assert resp2.status_code == 200
    assert resp2.json()["content"] == "# v1 content\n"


@pytest.mark.asyncio()
async def test_restore_404_for_missing_target(client, tmp_path):
    aid, _ = _make_artifact_with_versions(tmp_path)
    resp = await client.post(
        f"/api/v1/sessions/sess_v/artifacts/{aid}/versions/restore",
        json={"version_num": 999},
    )
    assert resp.status_code == 404


# ==================== PUT /{artifact_id} (Phase 2 M2) ====================


@pytest.mark.asyncio()
async def test_update_artifact_success(client, tmp_path):
    """PUT 替换内容：base_hash 匹配 → 200 + 新版本。"""
    content_file = tmp_path / "edit.md"
    original = "# Original\n"
    content_file.write_text(original, encoding="utf-8")

    aid = artifact_repo.record_artifact(
        session_id="sess_u", path=str(content_file),
        name="edit.md", kind="text", size=len(original),
    )
    base_hash = hashlib.sha256(original.encode()).hexdigest()

    new_content = "# Updated\n\nNew body\n"
    resp = await client.put(
        f"/api/v1/sessions/sess_u/artifacts/{aid}",
        json={"base_hash": base_hash, "content": new_content, "note": "edit"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"]["version_num"] == 1
    assert content_file.read_text(encoding="utf-8") == new_content


@pytest.mark.asyncio()
async def test_update_artifact_conflict(client, tmp_path):
    """PUT base_hash 不匹配 → 409 Conflict，文件不变。"""
    content_file = tmp_path / "edit2.md"
    original = "# Original\n"
    content_file.write_text(original, encoding="utf-8")

    aid = artifact_repo.record_artifact(
        session_id="sess_u", path=str(content_file),
        name="edit2.md", kind="text", size=len(original),
    )

    resp = await client.put(
        f"/api/v1/sessions/sess_u/artifacts/{aid}",
        json={"base_hash": "b" * 64, "content": "# Should not apply\n"},
    )
    assert resp.status_code == 409
    assert content_file.read_text(encoding="utf-8") == original


@pytest.mark.asyncio()
async def test_update_artifact_404_missing(client):
    resp = await client.put(
        "/api/v1/sessions/sess_test/artifacts/nope",
        json={"base_hash": "a" * 64, "content": "x"},
    )
    assert resp.status_code == 404
