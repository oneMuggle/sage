"""R69 — media serve 路由单元测试。

直接调用路由函数。MediaStore 与 MEDIA_ROOT 打桩到 tmp 目录，覆盖：
非法 media_id 404、store 未命中 404、盘上文件缺失 404、命中返回
FileResponse（Cache-Control + media_type）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.api import media_routes as mr

pytestmark = pytest.mark.unit


def _fake_store(monkeypatch, load_result):
    captured = {}
    calls = {"load": 0}

    class _FakeStore:
        def __init__(self, root=None):
            captured["root"] = root

        def load(self, media_id):
            calls["load"] += 1
            captured["media_id"] = media_id
            return load_result

    monkeypatch.setattr(mr, "MediaStore", _FakeStore)
    return captured


@pytest.mark.asyncio()
async def test_serve_media_rejects_invalid_id_format():
    with pytest.raises(HTTPException) as ei:
        await mr.serve_media("not-hex-id")
    assert ei.value.status_code == 404


@pytest.mark.asyncio()
async def test_serve_media_rejects_wrong_length_id():
    with pytest.raises(HTTPException) as ei:
        await mr.serve_media("0123456789azz")  # 13 位，含非 hex 字符
    assert ei.value.status_code == 404


@pytest.mark.asyncio()
async def test_serve_media_store_miss_404(monkeypatch):
    _fake_store(monkeypatch, None)
    with pytest.raises(HTTPException) as ei:
        await mr.serve_media("0123456789ab")
    assert ei.value.status_code == 404


@pytest.mark.asyncio()
async def test_serve_media_file_missing_on_disk_404(monkeypatch, tmp_path):
    monkeypatch.setattr(mr, "MEDIA_ROOT", tmp_path)
    ref = SimpleNamespace(file_path="ghost/x.png", mime_type="image/png")
    _fake_store(monkeypatch, (ref, b"data"))
    with pytest.raises(HTTPException) as ei:
        await mr.serve_media("0123456789ab")
    assert ei.value.status_code == 404


@pytest.mark.asyncio()
async def test_serve_media_hit_returns_file_response(monkeypatch, tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    (target / "a.png").write_bytes(b"png-bytes")
    monkeypatch.setattr(mr, "MEDIA_ROOT", tmp_path)
    ref = SimpleNamespace(file_path="real/a.png", mime_type="image/png")
    captured = _fake_store(monkeypatch, (ref, b"ignored"))

    resp = await mr.serve_media("0123456789ab")
    assert captured["media_id"] == "0123456789ab"
    assert resp.media_type == "image/png"
    assert resp.headers["cache-control"] == "public, max-age=86400"
