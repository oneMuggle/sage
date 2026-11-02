"""Wiki `/vision` 端点的本地 OCR 回退测试。"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import wiki_routes as wr
from backend.services.ocr import (
    OcrConfig,
    OcrLine,
    OcrResult,
    OcrService,
    init_ocr_service,
    reset_ocr_service,
)

pytestmark = pytest.mark.unit


def _make_wiki_project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "wiki" / "pages").mkdir(parents=True)
    (root / "wiki" / "schema.md").write_bytes(b"---\ntitle: schema\n---\n")
    return root.resolve()


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(wr.router)
    return TestClient(app)


@pytest.fixture()
def patch_auth(monkeypatch):
    def _patch(root: Path) -> None:
        monkeypatch.setattr(
            wr, "authorize_registered_project", lambda p: Path(p).resolve()
        )

    return _patch


class _FakeEngine:
    name = "fake-ocr"

    def available(self):
        return True, ""

    def recognize(self, image_bytes, opts):
        return OcrResult(
            text="OCR 兜底文本",
            lines=(OcrLine(text="OCR 兜底文本", confidence=0.9),),
            engine=self.name,
        )


def test_route_vision_falls_back_to_local_ocr(
    client, patch_auth, monkeypatch, tmp_path
) -> None:
    init_ocr_service(
        OcrService(
            engines=[_FakeEngine()],
            config_provider=lambda: OcrConfig(enabled=True, engine="auto"),
        )
    )
    try:
        root = _make_wiki_project(tmp_path)
        patch_auth(root)

        async def _fail_caption(**kwargs):
            raise RuntimeError("vision down")

        import backend.wiki as wiki_pkg

        monkeypatch.setattr(wiki_pkg, "caption_image", _fail_caption)
        payload = {
            "image_data": base64.b64encode(b"\x89PNG fake").decode("ascii"),
            "project_path": str(root),
            "provider": "openai",
            "base_url": "http://x",
            "api_key": "k",
            "model": "gpt-4v",
        }
        body = client.post("/wiki/vision", json=payload).json()
        assert body["mode"] == "ocr"
        assert body["caption"] == "OCR 兜底文本"
        assert body["engine"] == "fake-ocr"
    finally:
        reset_ocr_service()
