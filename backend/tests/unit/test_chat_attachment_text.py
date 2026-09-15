"""R37: 聊天文本文档附件路由单元测试

fake MediaStore（类级共享存储，同 R27/R30 测试口径）覆盖：
- txt/md 上传 → kind=DOCUMENT + text 全文响应
- 非 utf-8 / 非文本类型拒绝
- GET text 端点：存在返回全文 / 非 DOCUMENT 400 / 不存在 404
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

pytest.importorskip(
    "multipart", reason="python-multipart not installed (本地环境)；CI 全量安装"
)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.api import chat_attachment_routes  # noqa: E402

pytestmark = pytest.mark.unit

try:  # 本地 anaconda 无 python-multipart；CI 全量安装
    import python_multipart  # noqa: F401

    _HAS_MULTIPART = True
except ImportError:
    _HAS_MULTIPART = False

_no_multipart = pytest.mark.skipif(not _HAS_MULTIPART, reason="python-multipart not installed")


@dataclass
class _Ref:
    """Pydantic-serializable mirror of backend.services.multimodal.media_store.MediaRef"""
    id: str = ""
    kind: object = None
    mime_type: str = ""
    file_path: str = ""
    file_size: int = 0
    created_at: str = ""
    source: str = ""
    metadata: dict = None
    api_url: str = ""


class _FakeStore:
    saved: dict = {}

    def __init__(self, root=None):
        self.root = root

    def save(self, content: bytes, kind, source, metadata=None, ext=None):
        mid = f"m{len(_FakeStore.saved)}"
        _FakeStore.saved[mid] = {
            "content": content,
            "kind": kind,
            "ext": ext,
        }
        return _Ref(
            id=mid,
            kind=kind,
            mime_type="text/plain" if kind.value == "document" else "audio/mpeg",
            file_path=f"fake/{mid}",
            file_size=len(content),
            created_at="2026-09-15T00:00:00",
            source=source,
            metadata=metadata or {},
            api_url=f"/api/v1/media/{mid}",
        )

    def load(self, media_id: str):
        item = _FakeStore.saved.get(media_id)
        if item is None:
            return None
        return _Ref(
            id=media_id,
            kind=item["kind"],
            mime_type="text/plain",
            file_path=f"fake/{media_id}",
            file_size=len(item["content"]),
            created_at="",
            source="chat_upload",
            metadata={},
            api_url=f"/api/v1/media/{media_id}",
        ), item["content"]


@pytest.fixture()
def client(monkeypatch):
    if not _HAS_MULTIPART:
        pytest.skip("python-multipart not installed (本地环境)；CI 全量安装")
    _FakeStore.saved.clear()
    monkeypatch.setattr(chat_attachment_routes, "MEDIA_ROOT", "unused")
    monkeypatch.setattr(chat_attachment_routes, "MediaStore", _FakeStore)
    app = FastAPI()
    app.include_router(chat_attachment_routes.router)
    return TestClient(app)


@_no_multipart
def test_upload_txt_returns_text_and_document_kind(client):
    res = client.post(
        "/chat/attachments",
        files={"file": ("notes.md", "# 标题\n正文".encode(), "text/markdown")},
    )
    assert res.status_code == 200
    body = res.json()
    assert "error" not in body
    assert body["text"] == "# 标题\n正文"
    assert body["media_ref"]["id"].startswith("m")
    # kind 是 DOCUMENT（枚举值 document）
    assert _FakeStore.saved[body["media_ref"]["id"]]["kind"].value == "document"


@_no_multipart
def test_upload_non_utf8_rejected(client):
    res = client.post(
        "/chat/attachments",
        files={"file": ("bad.txt", b"\xff\xfe\x00bad", "text/plain")},
    )
    assert res.status_code == 200
    assert "不是有效的 UTF-8" in res.json().get("error", "")


@_no_multipart
def test_upload_unsupported_type_still_rejected(client):
    res = client.post(
        "/chat/attachments",
        files={"file": ("evil.exe", b"MZ", "application/octet-stream")},
    )
    assert res.status_code == 200
    assert "不支持的文件类型" in res.json().get("error", "")


def test_get_text_endpoint_roundtrip(client):
    created = client.post(
        "/chat/attachments",
        files={"file": ("doc.txt", "全文内容".encode(), "text/plain")},
    ).json()
    mid = created["media_ref"]["id"]
    res = client.get(f"/chat/attachments/{mid}/text")
    assert res.status_code == 200
    assert res.json()["text"] == "全文内容"


def test_get_text_endpoint_404_and_400(client):
    assert client.get("/chat/attachments/nope/text").status_code == 404
    # 上传一个音频再取文本 → 400 非 DOCUMENT
    client.post(
        "/chat/attachments",
        files={"file": ("a.mp3", b"\x00\x01", "audio/mpeg")},
    )
    audio_id = list(_FakeStore.saved.keys())[-1]
    assert client.get(f"/chat/attachments/{audio_id}/text").status_code == 400
