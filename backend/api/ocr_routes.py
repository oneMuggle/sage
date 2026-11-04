"""本地 OCR REST 端点。

- ``GET  /api/v1/ocr/capabilities``：引擎/模型/语言可用性（聊天页门控用）
- ``POST /api/v1/ocr/image``：识别 data URL 图片，返回结构化文本

安全边界：只接受 ``data:image/...;base64,``，不接受任意文件路径；单图
上限与聊天图片一致（解码后 ≤10MB）。
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.services.ocr import (
    MAX_IMAGE_BYTES,
    get_ocr_service,
    reset_ocr_service,
)
from backend.services.ocr.batch import (
    MAX_BATCH_ITEMS,
    MAX_PDF_BYTES,
    MAX_PDF_PAGES,
    decode_batch_images,
    decode_pdf_data_url,
    get_ocr_batch_service,
)

router = APIRouter(prefix="/ocr", tags=["ocr"])

#: base64 膨胀后的请求体上限（10MB 原始字节 × 4/3 + data URL 前缀余量）
_MAX_DATA_URL_CHARS = int(MAX_IMAGE_BYTES * 4 / 3) + 4096
_MAX_PDF_DATA_URL_CHARS = int(MAX_PDF_BYTES * 4 / 3) + 4096


class OcrImageRequest(BaseModel):
    """OCR 识别请求。"""

    model_config = ConfigDict(extra="forbid")

    image: str = Field(description="data:image/...;base64,... 形式的图片")
    lang: Optional[str] = Field(
        default=None, description="auto / ch / en，缺省使用 ocr_config.lang"
    )


class OcrBatchRequest(BaseModel):
    """批量 OCR 请求（多图）。"""

    model_config = ConfigDict(extra="forbid")

    images: List[str] = Field(description="图片 data URL 列表（最多 20 张）")
    lang: Optional[str] = None
    max_side: Optional[int] = Field(default=None, ge=256, le=8192)


class OcrPdfBatchRequest(BaseModel):
    """PDF 页批处理请求（服务端逐页光栅化）。"""

    model_config = ConfigDict(extra="forbid")

    pdf: str = Field(description="data:application/pdf;base64,... 形式的 PDF")
    lang: Optional[str] = None
    max_side: Optional[int] = Field(default=None, ge=256, le=8192)
    max_pages: int = Field(default=MAX_PDF_PAGES, ge=1, le=MAX_PDF_PAGES)


class OcrBatchCleanupRequest(BaseModel):
    """清理已完成任务；缺省按服务端 TTL（7 天）。"""

    model_config = ConfigDict(extra="forbid")

    older_than_s: Optional[int] = Field(default=None, ge=0)



@router.get("/capabilities")
def ocr_capabilities() -> dict:
    """返回 OCR 引擎与模型可用性。"""
    return get_ocr_service().capabilities()


@router.post("/reload")
def ocr_reload() -> dict:
    """重新探测 OCR 引擎/模型（模型下载或恢复默认后调用）。"""
    reset_ocr_service()
    return get_ocr_service().capabilities()


@router.post("/batch")
def ocr_batch(payload: OcrBatchRequest) -> dict:
    """提交多图批处理任务，立即返回 job_id。"""
    if not payload.images:
        raise HTTPException(status_code=400, detail="images_required")
    if len(payload.images) > MAX_BATCH_ITEMS:
        raise HTTPException(status_code=413, detail="too_many_images")
    for index, image in enumerate(payload.images):
        if len(image) > _MAX_DATA_URL_CHARS:
            raise HTTPException(
                status_code=413, detail="image_too_large:images[%d]" % index
            )
    try:
        images = decode_batch_images(payload.images)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job = get_ocr_batch_service().submit(
        images, lang=payload.lang or "auto", max_side=payload.max_side
    )
    return {"job_id": job.job_id, "total": job.total}


@router.post("/batch/pdf")
def ocr_batch_pdf(payload: OcrPdfBatchRequest) -> dict:
    """提交 PDF 页批处理；服务端用 PyMuPDF 逐页光栅化。"""
    if len(payload.pdf) > _MAX_PDF_DATA_URL_CHARS:
        raise HTTPException(status_code=413, detail="pdf_too_large")
    try:
        pdf_bytes = decode_pdf_data_url(payload.pdf)
        job = get_ocr_batch_service().submit_pdf(
            pdf_bytes,
            lang=payload.lang or "auto",
            max_side=payload.max_side,
            max_pages=payload.max_pages,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "job_id": job.job_id,
        "total": job.total,
        "pages": job.total,
        "source": job.source,
    }


@router.post("/batch/cleanup")
def ocr_batch_cleanup(payload: OcrBatchCleanupRequest) -> dict:
    """清理已结束任务；缺省按 7 天 TTL。"""
    removed = get_ocr_batch_service().cleanup(payload.older_than_s)
    return {"removed": removed}


@router.get("/batch/{job_id}")
def ocr_batch_status(job_id: str) -> dict:
    """查询批处理进度与结果。"""
    job = get_ocr_batch_service().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job_not_found")
    return job


@router.delete("/batch/{job_id}")
def ocr_batch_delete(job_id: str) -> dict:
    """删除任务及其持久化快照。"""
    if not get_ocr_batch_service().delete(job_id):
        raise HTTPException(status_code=404, detail="job_not_found")
    return {"ok": True}


@router.post("/batch/{job_id}/cancel")
def ocr_batch_cancel(job_id: str) -> dict:
    """请求取消批处理（worker 在当前项结束后停止）。"""
    if not get_ocr_batch_service().cancel(job_id):
        raise HTTPException(status_code=404, detail="job_not_found")
    return {"ok": True}


@router.post("/image")
def ocr_image(payload: OcrImageRequest) -> dict:
    """识别一张 data URL 图片。"""
    if len(payload.image) > _MAX_DATA_URL_CHARS:
        raise HTTPException(status_code=413, detail="image_too_large")
    if not payload.image.startswith("data:image/"):
        raise HTTPException(status_code=400, detail="invalid_image_data_url")
    result = get_ocr_service().recognize_data_url(payload.image, lang=payload.lang)
    return result.to_dict()
