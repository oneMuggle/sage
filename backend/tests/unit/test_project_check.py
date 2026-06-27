"""Integration tests for GET /wiki/project/check."""

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app


@pytest.fixture()
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _qs(path: str, intent: str) -> str:
    from urllib.parse import quote

    return f"/api/v1/wiki/project/check?path={quote(path)}&intent={intent}"


# 12. create + not exists + parent writable → ok
@pytest.mark.asyncio()
async def test_check_create_missing_path_parent_writable(client, tmp_path):
    target = tmp_path / "new-wiki"
    r = await client.get(_qs(str(target), "create"))
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is False
    assert body["parent_writable"] is True
    assert body["writable"] is False
    assert body["error"] is None


# 13. create + not exists + parent not writable → error
@pytest.mark.asyncio()
async def test_check_create_missing_path_parent_not_writable(client, tmp_path, monkeypatch):
    target = "/proc/1/this-cannot-be-created/cannot"
    r = await client.get(_qs(target, "create"))
    assert r.status_code == 200
    body = r.json()
    assert body["parent_writable"] is False
    assert body["error"] is not None


# 14. create + exists + has wiki/ → error "already a wiki project"
@pytest.mark.asyncio()
async def test_check_create_existing_wiki_returns_error(client, tmp_path):
    target = tmp_path / "existing-wiki"
    target.mkdir()
    (target / "wiki").mkdir()
    r = await client.get(_qs(str(target), "create"))
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is True
    assert body["is_project"] is True
    assert body["error"] is not None
    assert "已经是" in body["error"] or "already" in body["error"].lower()


# 15. create + exists but is a file → error
@pytest.mark.asyncio()
async def test_check_create_path_is_file(client, tmp_path):
    f = tmp_path / "a-file"
    f.write_text("hello")
    r = await client.get(_qs(str(f), "create"))
    assert r.status_code == 200
    body = r.json()
    assert body["error"] is not None


# 16. open + not exists → error
@pytest.mark.asyncio()
async def test_check_open_missing_path(client, tmp_path):
    target = tmp_path / "no-such"
    r = await client.get(_qs(str(target), "open"))
    assert r.status_code == 200
    body = r.json()
    assert body["error"] is not None
    assert body["exists"] is False


# 17. open + not a directory → error
@pytest.mark.asyncio()
async def test_check_open_path_is_file(client, tmp_path):
    f = tmp_path / "f"
    f.write_text("x")
    r = await client.get(_qs(str(f), "open"))
    assert r.status_code == 200
    assert r.json()["error"] is not None


# 18. open + exists + no wiki/ → error
@pytest.mark.asyncio()
async def test_check_open_no_wiki_subdir(client, tmp_path):
    d = tmp_path / "not-a-wiki"
    d.mkdir()
    r = await client.get(_qs(str(d), "open"))
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is True
    assert body["is_project"] is False
    assert body["error"] is not None


# 19. open + exists + has wiki/ → ok
@pytest.mark.asyncio()
async def test_check_open_valid_wiki(client, tmp_path):
    d = tmp_path / "valid-wiki"
    d.mkdir()
    (d / "wiki").mkdir()
    r = await client.get(_qs(str(d), "open"))
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is True
    assert body["is_project"] is True
    assert body["error"] is None


# 20. intent missing or invalid → 422
@pytest.mark.asyncio()
async def test_check_invalid_intent_returns_422(client, tmp_path):
    r = await client.get(f"/api/v1/wiki/project/check?path={tmp_path}&intent=bogus")
    assert r.status_code == 422


# 21. path contains ~ → expanduser
@pytest.mark.asyncio()
async def test_check_expanduser(client, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    fake = tmp_path / "home-wiki"
    fake.mkdir()
    (fake / "wiki").mkdir()
    r = await client.get("/api/v1/wiki/project/check?path=~/home-wiki&intent=open")
    assert r.status_code == 200
    assert r.json()["is_project"] is True
