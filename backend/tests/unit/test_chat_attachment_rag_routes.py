"""r58 — 附件向量索引三端点单测（index / search / delete）。

沿用 test_chat_attachment_text.py 的 fake MediaStore 口径（不经过
multipart 上传，直接 seed 存储）；嵌入端点用 respx 拦截（r54 同款）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from backend.services.attachment_rag import attachment_page_path
from backend.services.multimodal.media_store import MediaKind

pytest.importorskip("respx", reason="respx not installed；CI 全量安装")

import respx  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from httpx import Response  # noqa: E402

from backend.api import chat_attachment_routes  # noqa: E402

pytestmark = pytest.mark.unit

DIM = 4


@dataclass
class _Ref:
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

    def load(self, media_id: str):
        item = _FakeStore.saved.get(media_id)
        if item is None:
            return None
        return _Ref(
            id=media_id,
            kind=item["kind"],
            mime_type="text/plain",
            file_path=item["file_path"],
            file_size=len(item["content"]),
            created_at="",
            source="chat_upload",
            metadata={},
            api_url=f"/api/v1/media/{media_id}",
        ), item["content"]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    _FakeStore.saved.clear()
    monkeypatch.setattr(chat_attachment_routes, "MEDIA_ROOT", "unused")
    monkeypatch.setattr(chat_attachment_routes, "MediaStore", _FakeStore)
    monkeypatch.setattr(
        chat_attachment_routes, "ATTACHMENT_VECTOR_STORE", tmp_path / "rag" / "attachments.json"
    )
    app = FastAPI()
    app.include_router(chat_attachment_routes.router)
    return TestClient(app)


def _seed_txt(media_id: str, text: str):
    _FakeStore.saved[media_id] = {
        "content": text.encode("utf-8"),
        "kind": MediaKind.DOCUMENT,
        "file_path": f"fake/{media_id}.txt",
    }


def _seed_audio(media_id: str):
    _FakeStore.saved[media_id] = {
        "content": b"ID3audio",
        "kind": MediaKind.AUDIO,
        "file_path": f"fake/{media_id}.mp3",
    }


def _embed_body(vectors):
    return json.dumps({"data": [{"embedding": v} for v in vectors]})


def _index_body(**overrides):
    body = {
        "embed": {
            "base_url": "https://embed.example/v1",
            "api_key": "k-test",
            "model": "text-embedding-test",
            "dim": DIM,
        },
        "target_chunk_size": 50,
    }
    body.update(overrides)
    return body


def _embed_route(request) -> Response:
    """按请求 input 条数回同数向量（真实嵌入端点契约）。"""
    body = json.loads(request.content)
    return Response(200, content=_embed_body([[0.1, 0.2, 0.3, 0.4]] * len(body["input"])))


def test_index_search_delete_roundtrip(client):
    _seed_txt(
        "med-1",
        "甲段落内容，写得足够长以便跨过目标分块阈值形成独立分块。\n\n" * 3,
    )
    with respx.mock(base_url="https://embed.example", assert_all_called=False) as mock:
        mock.post("/v1/embeddings").mock(side_effect=_embed_route)
        res = client.post("/chat/attachments/med-1/index", json=_index_body())
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["chunks"] > 0
    assert body["page_path"] == attachment_page_path("med-1")

    hits = client.post(
        "/chat/attachments/search",
        json={"query_vector": [0.1, 0.2, 0.3, 0.4], "dim": DIM, "limit": 10},
    ).json()["hits"]
    assert len(hits) == body["chunks"]
    assert all(h["page_path"] == attachment_page_path("med-1") for h in hits)

    removed = client.delete("/chat/attachments/med-1/index").json()["removed"]
    assert removed == body["chunks"]
    assert client.post(
        "/chat/attachments/search",
        json={"query_vector": [0.1, 0.2, 0.3, 0.4], "dim": DIM},
    ).json()["hits"] == []


def test_index_nonexistent_404(client):
    res = client.post("/chat/attachments/ghost/index", json=_index_body())
    assert res.status_code == 404


def test_index_non_document_400(client):
    _seed_audio("med-audio")
    res = client.post("/chat/attachments/med-audio/index", json=_index_body())
    assert res.status_code == 400
    assert "不是文本文档" in res.json()["error"]


def test_search_empty_store_returns_empty(client):
    res = client.post(
        "/chat/attachments/search",
        json={"query_vector": [0.1, 0.2, 0.3, 0.4], "dim": DIM},
    )
    assert res.status_code == 200
    assert res.json()["hits"] == []


def test_search_dim_mismatch_400(client):
    res = client.post(
        "/chat/attachments/search",
        json={"query_vector": [0.1, 0.2], "dim": DIM},
    )
    assert res.status_code == 400
    assert "不符" in res.json()["error"]


def test_index_embed_failure_502(client):
    _seed_txt("med-err", "内容段落。\n\n内容段落二。")
    with respx.mock(base_url="https://embed.example", assert_all_called=False) as mock:
        mock.post("/v1/embeddings").mock(return_value=Response(500, text="boom"))
        res = client.post("/chat/attachments/med-err/index", json=_index_body())
    assert res.status_code == 502
    assert "嵌入请求失败" in res.json()["error"]


def test_delete_without_index_is_zero(client):
    res = client.delete("/chat/attachments/nope/index")
    assert res.status_code == 200
    assert res.json()["removed"] == 0
