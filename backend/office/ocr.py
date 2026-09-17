"""扫描件 OCR 兜底（office-p4a）—— pytesseract 可选依赖。

触发条件（由 :mod:`.pdf` 的 read_pdf 逐页调用）：
- 页面文本层近乎为空（< ``OCR_MIN_TEXT_CHARS``，即扫描/纯图页）；
- 环境变量 ``SAGE_OCR=1``（显式 opt-in —— OCR 整页光栅化 + tesseract
  推理代价高，默认关闭，行为与未引入本模块前完全一致）；
- 依赖可用：``pytesseract``（pip 包，可选）+ ``tesseract`` 二进制
  （系统安装；中文需 ``chi_sim`` 语言包）。

任一条件不满足 → 返回 ``None``，调用方沿用原（空）文本。绝不抛异常。

Python 3.8 兼容（typing.* generics），win7 cherry-pick 友好
（tesseract 有官方 Win7 构建；语言包安装见模块常量注释）。
"""

from __future__ import annotations

import logging
import os
import shutil
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "OCR_MIN_TEXT_CHARS",
    "ocr_available",
    "ocr_page_if_needed",
    "is_ocr_enabled",
]

#: 页面文本层字符数低于该值视为扫描页（触发 OCR 候选）
OCR_MIN_TEXT_CHARS = 32

#: 显式开关（默认关闭：OCR 代价高，避免对正常 PDF 造成意外减速）
_OCR_ENV_VAR = "SAGE_OCR"

#: tesseract 识别语言（默认英文+简中；用户可覆盖）
_OCR_LANG_ENV_VAR = "SAGE_OCR_LANG"


def is_ocr_enabled() -> bool:
    """用户是否显式开启 OCR（``SAGE_OCR=1``）。"""
    return os.environ.get(_OCR_ENV_VAR, "").strip() == "1"


def ocr_available() -> Tuple[bool, str]:
    """探测 OCR 依赖可用性；返回 ``(可用, 缺失原因)``。缺失原因为空串表示可用。"""
    try:
        import pytesseract  # noqa: F401 — 懒加载探测
    except Exception:  # noqa: BLE001 — 缺失/损坏都归为不可用
        return False, "pytesseract 未安装（pip install pytesseract）"
    if not shutil.which("tesseract"):
        return False, "tesseract 未安装或不在 PATH"
    return True, ""


def _ocr_lang() -> str:
    return os.environ.get(_OCR_LANG_ENV_VAR, "eng+chi_sim").strip() or "eng"


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
        import io

        import pytesseract
        from PIL import Image

        pix = page.get_pixmap(dpi=200)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        recognized = pytesseract.image_to_string(img, lang=_ocr_lang())
        return recognized if recognized.strip() else None
    except Exception:  # noqa: BLE001 — best-effort 兜底
        logger.warning("OCR failed on page; keeping original text", exc_info=True)
        return None
