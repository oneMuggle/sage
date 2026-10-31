"""本地 OCR REST 端点。

- ``GET  /api/v1/ocr/capabilities``：引擎/模型/语言可用性（聊天页门控用）
- ``POST /api/v1/ocr/image``：识别 data URL 图片，返回结构化文本

安全边界：只接受 ``data:image/...;base64,``，不接受任意文件路径；单图
上限与聊天图片一致（解码后 ≤10MB）。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.services.ocr import MAX_IMAGE_BYTES, get_ocr_service

router = APIRouter(prefix="/ocr", tags=["ocr"])

#: base64 膨胀后的请求体上限（10MB 原始字节 × 4/3 + data URL 前缀余量）
_MAX_DATA_URL_CHARS = int(MAX_IMAGE_BYTES * 4 / 3) + 4096


class OcrImageRequest(BaseModel):
    """OCR 识别请求。"""

    model_config = ConfigDict(extra="forbid")

    image: str = Field(description="data:image/...;base64,... 形式的图片")
    lang: Optional[str] = Field(
        default=None, description="auto / ch / en，缺省使用 ocr_config.lang"
    )


@router.get("/capabilities")
def ocr_capabilities() -> dict:
    """返回 OCR 引擎与模型可用性。"""
    return get_ocr_service().capabilities()


@router.post("/image")
def ocr_image(payload: OcrImageRequest) -> dict:
    """识别一张 data URL 图片。"""
    if len(payload.image) > _MAX_DATA_URL_CHARS:
        raise HTTPException(status_code=413, detail="image_too_large")
    if not payload.image.startswith("data:image/"):
        raise HTTPException(status_code=400, detail="invalid_image_data_url")
    result = get_ocr_service().recognize_data_url(payload.image, lang=payload.lang)
    return result.to_dict()
