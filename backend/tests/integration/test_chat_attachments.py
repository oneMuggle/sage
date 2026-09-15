"""Chat attachment upload 集成测试"""

import io

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio()
async def test_upload_audio_attachment(tmp_path, monkeypatch):
    """POST /api/v1/chat/attachments 上传音频文件"""
    monkeypatch.setattr("backend.api.chat_attachment_routes.MEDIA_ROOT", tmp_path)

    from fastapi import FastAPI

    from backend.api.chat_attachment_routes import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/chat/attachments",
            files={"file": ("test.mp3", io.BytesIO(b"\xff\xfb\x90\x00" + b"\x00" * 50), "audio/mpeg")},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "media_ref" in data


@pytest.mark.asyncio()
async def test_upload_too_large(tmp_path, monkeypatch):
    """超过 25MB 上限应返回错误"""
    from backend.api.chat_attachment_routes import MAX_ATTACHMENT_SIZE, router
    monkeypatch.setattr("backend.api.chat_attachment_routes.MEDIA_ROOT", tmp_path)

    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        huge = b"\x00" * (MAX_ATTACHMENT_SIZE + 1)
        resp = await client.post(
            "/api/v1/chat/attachments",
            files={"file": ("huge.mp3", io.BytesIO(huge), "audio/mpeg")},
        )
    data = resp.json()
    assert "error" in data


@pytest.mark.asyncio()
async def test_upload_unsupported_type(tmp_path, monkeypatch):
    """不支持的文件类型应返回错误"""
    monkeypatch.setattr("backend.api.chat_attachment_routes.MEDIA_ROOT", tmp_path)

    from fastapi import FastAPI

    from backend.api.chat_attachment_routes import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/chat/attachments",
            files={"file": ("test.exe", io.BytesIO(b"MZ\x90\x00"), "application/x-msdownload")},
        )
    data = resp.json()
    assert "error" in data
