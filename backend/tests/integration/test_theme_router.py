"""theme_router 集成测试 — TDD"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture()
def theme_storage_dir(tmp_path: Path) -> Path:
    """临时主题存储目录"""
    return tmp_path


@pytest.fixture()
def theme_client(client, theme_storage_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """注入临时 ThemeStorage 到 theme_router"""
    from backend.services.theme_storage import ThemeStorage

    storage = ThemeStorage(storage_dir=theme_storage_dir)
    monkeypatch.setattr("backend.api.theme_router._storage", storage)
    return client


@pytest.fixture()
def sample_payload() -> dict:
    return {
        "id": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
        "name": "Test Theme",
        "css": ":root { --bg-base: #fff; }",
        "appearance": "light",
        "created_at": 1700000000000,
        "updated_at": 1700000000000,
    }


class TestSaveTheme:
    @pytest.mark.asyncio
    async def test_save_returns_id(self, theme_client, sample_payload: dict) -> None:
        resp = await theme_client.post("/api/theme/save", json=sample_payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == sample_payload["id"]

    @pytest.mark.asyncio
    async def test_save_validates_payload(self, theme_client) -> None:
        bad = {"id": "x", "name": "y", "css": "z", "appearance": "sepia"}
        resp = await theme_client.post("/api/theme/save", json=bad)
        assert resp.status_code == 422


class TestListThemes:
    @pytest.mark.asyncio
    async def test_list_empty(self, theme_client) -> None:
        resp = await theme_client.get("/api/theme/list")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_list_returns_saved(
        self, theme_client, sample_payload: dict
    ) -> None:
        await theme_client.post("/api/theme/save", json=sample_payload)
        resp = await theme_client.get("/api/theme/list")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == sample_payload["id"]


class TestDeleteTheme:
    @pytest.mark.asyncio
    async def test_delete_existing(
        self, theme_client, sample_payload: dict
    ) -> None:
        await theme_client.post("/api/theme/save", json=sample_payload)
        resp = await theme_client.post(
            "/api/theme/delete", json={"id": sample_payload["id"]}
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    @pytest.mark.asyncio
    async def test_delete_missing(self, theme_client) -> None:
        resp = await theme_client.post(
            "/api/theme/delete", json={"id": "nonexistent"}
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is False


class TestGetTheme:
    @pytest.mark.asyncio
    async def test_get_existing(
        self, theme_client, sample_payload: dict
    ) -> None:
        await theme_client.post("/api/theme/save", json=sample_payload)
        resp = await theme_client.get(f"/api/theme/get/{sample_payload['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Test Theme"

    @pytest.mark.asyncio
    async def test_get_missing_returns_404(self, theme_client) -> None:
        resp = await theme_client.get("/api/theme/get/nonexistent")
        assert resp.status_code == 404
