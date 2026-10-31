"""OCR 批处理队列单元测试（fake OCR service）。"""

from __future__ import annotations

import time

import pytest

from backend.services.ocr.batch import (
    MAX_BATCH_ITEMS,
    OcrBatchService,
    decode_batch_images,
)
from backend.services.ocr.models import OcrLine, OcrResult

pytestmark = pytest.mark.unit


class FakeOcrService:
    def recognize_bytes(self, image_bytes, **kwargs):
        return OcrResult(
            text="批处理文字",
            lines=(OcrLine(text="批处理文字", confidence=0.9),),
            engine="fake",
        )


def _wait(service: OcrBatchService, job_id: str, timeout: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = service.get(job_id)
        assert data is not None
        if data["status"] in ("completed", "failed", "cancelled"):
            return data
        time.sleep(0.02)
    raise AssertionError("batch job did not finish in time")


def test_batch_completes_items_independently() -> None:
    service = OcrBatchService(service_provider=lambda: FakeOcrService())

    job = service.submit([b"one", b"two"], lang="auto")
    data = _wait(service, job.job_id)

    assert data["status"] == "completed"
    assert data["total"] == 2
    assert data["completed"] == 2
    assert data["failed"] == 0
    assert [item["text"] for item in data["results"]] == ["批处理文字", "批处理文字"]


def test_batch_rejects_too_many_items() -> None:
    service = OcrBatchService(service_provider=lambda: FakeOcrService())

    with pytest.raises(ValueError, match="at most"):
        service.submit([b"x"] * (MAX_BATCH_ITEMS + 1))


def test_batch_cancel_marks_job() -> None:
    service = OcrBatchService(service_provider=lambda: FakeOcrService())
    job = service.submit([b"one", b"two"], lang="auto")

    assert service.cancel(job.job_id) is True
    data = _wait(service, job.job_id)

    assert data["status"] in ("cancelled", "completed")


def test_decode_batch_images_rejects_invalid_data_url() -> None:
    with pytest.raises(ValueError, match="not a valid image data URL"):
        decode_batch_images(["data:text/plain;base64,AAAA"])


def test_decode_batch_images_decodes_valid_png() -> None:
    import base64

    payload = base64.b64encode(b"fake-png").decode("ascii")
    assert decode_batch_images(["data:image/png;base64," + payload]) == [b"fake-png"]
