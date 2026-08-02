# backend/tests/api/test_artifact_routes.py
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
