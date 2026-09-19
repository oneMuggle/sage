"""Round D P10: 本地 OCR（可选依赖，扫描件 PDF→Word 的缺口补齐）。

``pdf_to_word`` 的文档化保真边界：无文本层的扫描件转出近空文档。本
模块用 **RapidOCR**（rapidocr-onnxruntime，本地 ONNX 推理，零外发，
契合"数据不出机"定位）把光栅化页面识别成文本行，作为扫描件的回退
文本来源。

可选依赖模式与 Pillow 相同：requirements-optional.txt 安装；缺失时
``is_ocr_available()`` 返回 False，调用方保持原行为（近空文档 + 提示
安装）。引擎实例进程内单例（模型加载 ~百 MB 级内存，秒级初始化——
绝不能每页新建）。

失败契约：``ocr_pdf_page`` 永不 raise —— 单页失败返回空列表。

Python 3.8-compatible syntax（win7 回流：rapidocr-onnxruntime 的
onnxruntime 依赖有 py38 兼容历史版本；缺失即降级，不硬求）。
"""

from __future__ import annotations

import logging
import threading
from importlib.util import find_spec
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

__all__ = ["is_ocr_available", "ocr_pdf_page", "OCR_RASTER_DPI"]

#: 光栅化 DPI —— 200 在中文文档上是识别率/速度的常用平衡点。
OCR_RASTER_DPI = 200

#: 置信度下限：低于该值的识别行丢弃（噪声/花纹误检）。
_MIN_CONFIDENCE = 0.5

_engine_lock = threading.Lock()
_engine: Optional[Any] = None
_engine_failed = False


def is_ocr_available() -> bool:
    """RapidOCR 可导入（不加载模型 —— capabilities 探测要求零副作用）。"""
    return find_spec("rapidocr_onnxruntime") is not None


def _get_engine() -> Optional[Any]:
    """进程内单例引擎；初始化失败后不再重试（_engine_failed 闩锁）。"""
    global _engine, _engine_failed
    if _engine is not None:
        return _engine
    if _engine_failed:
        return None
    with _engine_lock:
        if _engine is not None:
            return _engine
        if _engine_failed:
            return None
        try:
            from rapidocr_onnxruntime import RapidOCR  # noqa: PLC0415 — heavy optional import

            _engine = RapidOCR()
            return _engine
        except Exception:  # noqa: BLE001 — 模型缺失/onnxruntime 不兼容等
            logger.warning("RapidOCR engine init failed; OCR disabled", exc_info=True)
            _engine_failed = True
            return None


def ocr_pdf_page(page: Any) -> List[str]:
    """OCR one PyMuPDF page → 识别出的文本行（阅读顺序，按 y 再 x 排序）。

    ``page`` 是 ``pymupdf.Page``。永不 raise —— 引擎不可用/识别失败返回
    空列表，调用方自行决定降级文案。
    """
    engine = _get_engine()
    if engine is None:
        return []
    try:
        import pymupdf  # noqa: PLC0415 — caller always has it; keep import local anyway

        zoom = OCR_RASTER_DPI / 72.0
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        png_bytes = pix.tobytes("png")
        result, _elapsed = engine(png_bytes)
        if not result:
            return []
        # result: List of [box(4 points), text, score]
        lines = []
        for entry in result:
            try:
                box, text, score = entry[0], str(entry[1]), float(entry[2])
            except (IndexError, TypeError, ValueError):
                continue
            if score < _MIN_CONFIDENCE or not text.strip():
                continue
            # 排序 key：左上角 (y, x) —— 近似阅读顺序
            top_left = box[0] if box else (0, 0)
            lines.append((float(top_left[1]), float(top_left[0]), text.strip()))
        lines.sort(key=lambda t: (t[0], t[1]))
        return [t[2] for t in lines]
    except Exception:  # noqa: BLE001 — 单页 OCR 失败不阻断整体转换
        logger.warning("OCR failed for one page (non-fatal)", exc_info=True)
        return []
