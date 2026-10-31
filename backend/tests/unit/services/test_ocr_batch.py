"""OCR 批处理队列单元测试（fake OCR service）。"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import asdict

import pytest

from backend.services.ocr.batch import (
    MAX_BATCH_ITEMS,
    OcrBatchJob,
    OcrBatchService,
    decode_batch_images,
    decode_pdf_data_url,
    rasterize_pdf_pages,
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


def _new_service(tmp_path) -> OcrBatchService:
    return OcrBatchService(
        service_provider=lambda: FakeOcrService(),
        store_dir=tmp_path,
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


def _make_pdf(text: str = "SAGE PDF OCR") -> bytes:
    fitz = pytest.importorskip("fitz")
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    pdf_bytes = document.tobytes()
    document.close()
    return pdf_bytes


def test_batch_completes_items_independently(tmp_path) -> None:
    service = _new_service(tmp_path)

    job = service.submit([b"one", b"two"], lang="auto")
    data = _wait(service, job.job_id)

    assert data["status"] == "completed"
    assert data["source"] == "images"
    assert data["total"] == 2
    assert data["completed"] == 2
    assert data["failed"] == 0
    assert [item["text"] for item in data["results"]] == ["批处理文字", "批处理文字"]


def test_batch_rejects_too_many_items(tmp_path) -> None:
    service = _new_service(tmp_path)

    with pytest.raises(ValueError, match="at most"):
        service.submit([b"x"] * (MAX_BATCH_ITEMS + 1))


def test_batch_cancel_marks_job(tmp_path) -> None:
    service = _new_service(tmp_path)
    job = service.submit([b"one", b"two"], lang="auto")

    assert service.cancel(job.job_id) is True
    data = _wait(service, job.job_id)

    assert data["status"] in ("cancelled", "completed")


def test_batch_job_survives_restart(tmp_path) -> None:
    service = _new_service(tmp_path)
    job = service.submit([b"one"], lang="auto")
    _wait(service, job.job_id)

    restarted = _new_service(tmp_path)
    restored = restarted.get(job.job_id)

    assert restored is not None
    assert restored["status"] == "completed"
    assert restored["results"][0]["text"] == "批处理文字"


def test_running_job_is_marked_interrupted_on_restart(tmp_path) -> None:
    job = OcrBatchJob(
        job_id="interrupted1",
        total=1,
        lang="auto",
        max_side=None,
        status="running",
        results=[None],
    )
    (tmp_path / "interrupted1.json").write_text(
        json.dumps(asdict(job), ensure_ascii=False), encoding="utf-8"
    )

    restarted = _new_service(tmp_path)
    restored = restarted.get("interrupted1")

    assert restored is not None
    assert restored["status"] == "failed"
    assert "interrupted" in (restored["error"] or "")


def test_decode_batch_images_rejects_invalid_data_url() -> None:
    with pytest.raises(ValueError, match="not a valid image data URL"):
        decode_batch_images(["data:text/plain;base64,AAAA"])


def test_decode_batch_images_decodes_valid_png() -> None:
    payload = base64.b64encode(b"fake-png").decode("ascii")
    assert decode_batch_images(["data:image/png;base64," + payload]) == [b"fake-png"]


def test_decode_pdf_data_url_roundtrip() -> None:
    pdf_bytes = b"%PDF-fake"
    data_url = "data:application/pdf;base64," + base64.b64encode(pdf_bytes).decode("ascii")

    assert decode_pdf_data_url(data_url) == pdf_bytes


def test_decode_pdf_data_url_rejects_non_pdf() -> None:
    with pytest.raises(ValueError, match="not a valid PDF data URL"):
        decode_pdf_data_url("data:image/png;base64,AAAA")


def test_rasterize_pdf_pages_renders_png(tmp_path) -> None:
    pages = rasterize_pdf_pages(_make_pdf())

    assert len(pages) == 1
    assert pages[0].startswith(b"\x89PNG")


def test_submit_pdf_marks_source_and_runs(tmp_path) -> None:
    service = _new_service(tmp_path)

    job = service.submit_pdf(_make_pdf())
    data = _wait(service, job.job_id)

    assert data["status"] == "completed"
    assert data["source"] == "pdf"
    assert data["total"] == 1
    assert data["results"][0]["text"] == "批处理文字"
