"""本地 OCR 子系统。

公开接口：
- ``get_ocr_service()`` / ``init_ocr_service()`` / ``reset_ocr_service()``
- ``OcrResult`` / ``OcrLine`` / ``OcrOptions``
- ``load_ocr_config()`` / ``OcrConfig``

引擎：RapidOCR(ONNX，可选) 与 Tesseract(可选) 自动选择，未安装时能力位降级。
"""

from .config import OCR_CONFIG_KEY, OcrConfig, load_ocr_config
from .models import (
    MAX_IMAGE_BYTES,
    QUALITY_EMPTY,
    QUALITY_FAILED,
    QUALITY_LOW_CONFIDENCE,
    QUALITY_OK,
    OcrLine,
    OcrOptions,
    OcrResult,
)
from .service import (
    OcrService,
    get_ocr_service,
    init_ocr_service,
    reset_ocr_service,
)

__all__ = [
    "OCR_CONFIG_KEY",
    "MAX_IMAGE_BYTES",
    "QUALITY_EMPTY",
    "QUALITY_FAILED",
    "QUALITY_LOW_CONFIDENCE",
    "QUALITY_OK",
    "OcrConfig",
    "OcrLine",
    "OcrOptions",
    "OcrResult",
    "OcrService",
    "get_ocr_service",
    "init_ocr_service",
    "load_ocr_config",
    "reset_ocr_service",
]
