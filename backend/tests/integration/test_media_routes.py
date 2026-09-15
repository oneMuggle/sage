"""Media serve 路由集成测试"""

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio()
async def test_serve_media_found(tmp_path, monkeypatch):
    """GET /api/v1/media/{id} 应返回文件"""
    from backend.services.multimodal.media_store import MediaKind, MediaStore
    monkeypatch.setattr("backend.api.media_routes.MEDIA_ROOT", tmp_path)
    store = MediaStore(root=tmp_path)
    content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
    ref = store.save(content=content, kind=MediaKind.IMAGE, source="test")

    from fastapi import FastAPI

    from backend.api.media_routes import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/media/{ref.id}")
    assert resp.status_code == 200


@pytest.mark.asyncio()
async def test_serve_media_not_found():
    """GET /api/v1/media/{id} 不存在应 404"""
    from fastapi import FastAPI

    from backend.api.media_routes import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/media/nonexistent_id")
    assert resp.status_code == 404
