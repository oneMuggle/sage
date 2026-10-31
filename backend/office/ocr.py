"""扫描件 OCR 兜底（office-p4a）——统一 OCR 服务适配层。

保留既有语义（SAGE_OCR=1 显式开启、文本层阈值、语言包回退、置信度过滤），
识别实现委托给 ``backend.services.ocr``，以便聊天 / Agent / Wiki 复用同一套
引擎与模型管理。

触发条件（由 :mod:`.pdf` 的 read_pdf 逐页调用）：
- 页面文本层近乎为空（< ``OCR_MIN_TEXT_CHARS``，即扫描/纯图页）；
- 环境变量 ``SAGE_OCR=1``（显式 opt-in —— OCR 整页光栅化 + 推理代价高，
  默认关闭，行为与未引入本模块前完全一致）；
- 依赖可用：``pytesseract``（pip 包，可选）+ ``tesseract`` 二进制
  （系统安装；中文需 ``chi_sim`` 语言包）。

任一条件不满足 → 返回 ``None``，调用方沿用原（空）文本。绝不抛异常。

Python 3.8 兼容；win7 cherry-pick 友好（tesseract 有 Win7 社区构建）。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "OCR_MIN_TEXT_CHARS",
    "ocr_available",
    "ocr_page_if_needed",
    "is_ocr_enabled",
    "ocr_languages",
]

#: 页面文本层字符数低于该值视为扫描页（触发 OCR 候选）
OCR_MIN_TEXT_CHARS = 32

#: 显式开关（默认关闭：OCR 代价高，避免对正常 PDF 造成意外减速）
_OCR_ENV_VAR = "SAGE_OCR"

#: tesseract 识别语言（默认英文+简中；用户可覆盖）
_OCR_LANG_ENV_VAR = "SAGE_OCR_LANG"

#: 低置信度文本过滤阈值（0-100，image_to_data 的 conf 列）；0 = 不过滤
_OCR_MIN_CONFIDENCE_DEFAULT = 40


def _min_confidence() -> int:
    raw = os.environ.get("SAGE_OCR_MIN_CONFIDENCE", "").strip()
    if not raw:
        return _OCR_MIN_CONFIDENCE_DEFAULT
    try:
        return max(0, min(100, int(raw)))
    except ValueError:
        return _OCR_MIN_CONFIDENCE_DEFAULT


def is_ocr_enabled() -> bool:
    """用户是否显式开启 OCR（``SAGE_OCR=1``）。"""
    return os.environ.get(_OCR_ENV_VAR, "").strip() == "1"


def ocr_available() -> Tuple[bool, str]:
    """探测 OCR 依赖可用性；返回 ``(可用, 缺失原因)``。

    统一走 ``backend.services.ocr`` 的引擎选择（RapidOCR 优先、Tesseract
    兜底）；Office 扫描页仍由 ``SAGE_OCR=1`` 显式开启。
    """
    try:
        from backend.services.ocr import get_ocr_service

        caps = get_ocr_service().capabilities()
        if caps.get("available"):
            return True, ""
        return False, str(caps.get("reason") or "OCR 引擎不可用")
    except Exception as exc:  # noqa: BLE001 — 探测失败归为不可用
        return False, str(exc)


def _ocr_lang() -> str:
    return os.environ.get(_OCR_LANG_ENV_VAR, "eng+chi_sim").strip() or "eng"


def ocr_languages() -> Optional[list]:
    """返回 tesseract 已安装的语言包列表；依赖缺失返回 None。"""
    from backend.services.ocr.engines.tesseract import TesseractEngine

    return TesseractEngine().languages()


def _resolve_lang_with_fallback(pytesseract: Any) -> str:
    """兼容旧调用方：请求语言与已安装语言包求交集；全部缺失回退 eng。"""
    from backend.services.ocr.engines.tesseract import resolve_lang_with_fallback

    return resolve_lang_with_fallback(pytesseract, _ocr_lang())


def _recognize(pytesseract: Any, img: Any, lang: str, min_conf: int) -> str:
    """兼容旧调用方：识别一页（优先 image_to_data，失败退回 image_to_string）。"""
    from backend.services.ocr.engines.tesseract import _lines_from_data

    if min_conf <= 0:
        return pytesseract.image_to_string(img, lang=lang)
    try:
        data = pytesseract.image_to_data(
            img, lang=lang, output_type=pytesseract.Output.DICT
        )
        lines, _best = _lines_from_data(data, min_conf / 100.0)
        return "\n".join(line.text for line in lines if line.text)
    except Exception:  # noqa: BLE001 — data 通道失败退回 string 通道
        logger.warning(
            "image_to_data failed; falling back to image_to_string", exc_info=True
        )
        return pytesseract.image_to_string(img, lang=lang)


def ocr_page_if_needed(page: Any, text: str) -> Optional[str]:
    """文本层近乎为空时对该页做 OCR，返回识别文本；否则/不可用返回 None。

    ``page`` 是 pymupdf 页对象（仅调用 ``get_pixmap``）。任何异常按
    "OCR 不可用" 处理（返回 None + warning），绝不影响读取主流程。
    """
    if len(text.strip()) >= OCR_MIN_TEXT_CHARS:
        return None
    if not is_ocr_enabled():
        return None
    ok, reason = ocr_available()
    if not ok:
        logger.debug("OCR skipped: %s", reason)
        return None
    try:
        pix = page.get_pixmap(dpi=200)
        image_bytes = pix.tobytes("png")

        from backend.services.ocr import get_ocr_service

        result = get_ocr_service().recognize_bytes(
            image_bytes,
            source="office_pdf",
            lang=_ocr_lang(),
            min_confidence=_min_confidence() / 100.0,
            # 扫描页优先保真：更高分辨率 + 开启方向分类
            max_side=2048,
            use_cls=True,
        )
        if not result.ok:
            logger.debug("OCR failed: %s", result.error)
            return None
        return result.text if result.text.strip() else None
    except Exception:  # noqa: BLE001 — best-effort 兜底
        logger.warning("OCR failed on page; keeping original text", exc_info=True)
        return None
