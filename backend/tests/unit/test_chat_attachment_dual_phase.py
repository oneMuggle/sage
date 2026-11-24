from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import chat_attachment_routes


def test_pdf_upload_enqueues_when_enabled(monkeypatch, tmp_path) -> None:
    submitted = []

    class FakeQueue:
        def submit(self, **kwargs):
            submitted.append(kwargs)
            return "k"

    class FakeSettings:
        enabled = True
        configured = True
        use_in_chat_attachment = True
        max_upload_mb = 25
        base_url = "http://m:8000"

    monkeypatch.setattr(chat_attachment_routes, "MEDIA_ROOT", tmp_path)
    monkeypatch.setattr(chat_attachment_routes, "get_mineru_queue", lambda: FakeQueue())
    monkeypatch.setattr(
        chat_attachment_routes, "load_mineru_settings", lambda: FakeSettings()
    )
    app = FastAPI()
    app.include_router(chat_attachment_routes.router, prefix="/api/v1")
    pdf = b"%PDF-1.4\n%%EOF"
    response = TestClient(app).post(
        "/api/v1/chat/attachments",
        files={"file": ("a.pdf", pdf, "application/pdf")},
    )
    assert response.status_code == 200
    assert submitted
    assert submitted[0]["filename"] == "a.pdf"
