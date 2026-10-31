"""本地 OCR REST 端点单元测试（fake 服务）。"""

from __future__ import annotations

import base64

import pytest
from fastapi import HTTPException

from backend.api import ocr_routes
from backend.services.ocr import (
    OcrConfig,
    OcrLine,
    OcrResult,
    OcrService,
    init_ocr_service,
    reset_ocr_service,
)

pytestmark = pytest.mark.unit

PNG_DATA_URL = "data:image/png;base64," + base64.b64encode(b"fake").decode("ascii")


class FakeEngine:
    name = "fake-ocr"

    def available(self):
        return True, ""

    def recognize(self, image_bytes, opts):
        return OcrResult(
            text="识别结果",
            lines=(OcrLine(text="识别结果", confidence=0.9),),
            engine=self.name,
            lang=opts.lang,
        )


@pytest.fixture(autouse=True)
def _isolate_service():
    init_ocr_service(
        OcrService(
            engines=[FakeEngine()],
            config_provider=lambda: OcrConfig(enabled=True, engine="auto"),
        )
    )
    yield
    reset_ocr_service()


def test_capabilities_endpoint() -> None:
    caps = ocr_routes.ocr_capabilities()

    assert caps["available"] is True
    assert caps["selected_engine"] == "fake-ocr"


def test_image_endpoint_returns_text() -> None:
    result = ocr_routes.ocr_image(ocr_routes.OcrImageRequest(image=PNG_DATA_URL))

    assert result["text"] == "识别结果"
    assert result["engine"] == "fake-ocr"


def test_image_endpoint_rejects_non_image() -> None:
    with pytest.raises(HTTPException) as exc:
        ocr_routes.ocr_image(
            ocr_routes.OcrImageRequest(image="data:text/plain;base64,AAAA")
        )

    assert exc.value.status_code == 400


def test_image_endpoint_rejects_too_large(monkeypatch) -> None:
    monkeypatch.setattr(ocr_routes, "_MAX_DATA_URL_CHARS", 10)

    with pytest.raises(HTTPException) as exc:
        ocr_routes.ocr_image(ocr_routes.OcrImageRequest(image=PNG_DATA_URL))

    assert exc.value.status_code == 413


def test_batch_endpoint_roundtrip() -> None:
    from backend.services.ocr.batch import reset_ocr_batch_service

    try:
        submitted = ocr_routes.ocr_batch(
            ocr_routes.OcrBatchRequest(images=[PNG_DATA_URL, PNG_DATA_URL])
        )
        job_id = submitted["job_id"]
        status = None
        import time

        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status = ocr_routes.ocr_batch_status(job_id)
            if status["status"] in ("completed", "failed", "cancelled"):
                break
            time.sleep(0.02)
        assert status is not None
        assert status["status"] == "completed"
        assert status["total"] == 2
        assert [item["text"] for item in status["results"]] == ["识别结果", "识别结果"]
    finally:
        reset_ocr_batch_service()
