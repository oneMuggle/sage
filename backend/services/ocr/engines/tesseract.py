"""Tesseract 引擎（pytesseract + 系统 tesseract 二进制）。

兼容既有 ``backend/office/ocr.py`` 的语义：
- 默认语言 ``eng+chi_sim``（可用 ``SAGE_OCR_LANG`` 覆盖）；
- ``image_to_data`` 逐词置信度过滤，失败退回 ``image_to_string``；
- 请求语言与已安装语言包求交集，全部缺失回退 ``eng``。

不依赖 Pillow：图片先写临时文件，再交给 pytesseract（它接受路径/bytes）。
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Tuple

from ..models import (
    QUALITY_EMPTY,
    QUALITY_LOW_CONFIDENCE,
    QUALITY_OK,
    OcrLine,
    OcrOptions,
    OcrResult,
)

logger = logging.getLogger(__name__)

_LANG_ENV_VAR = "SAGE_OCR_LANG"
_DEFAULT_LANG = "eng+chi_sim"


class TesseractEngine:
    """pytesseract 后端。"""

    name = "tesseract"

    def available(self) -> Tuple[bool, str]:
        try:
            import pytesseract  # noqa: F401 — 懒加载探测
        except Exception:  # noqa: BLE001
            return False, "pytesseract 未安装（pip install pytesseract）"
        if not shutil.which("tesseract"):
            return False, "tesseract 未安装或不在 PATH"
        return True, ""

    def languages(self) -> Optional[List[str]]:
        try:
            import pytesseract

            langs = pytesseract.get_languages(config="")
            return sorted(langs) if langs else None
        except Exception:  # noqa: BLE001 — best-effort
            return None

    def recognize(self, image_bytes: bytes, opts: OcrOptions) -> OcrResult:
        import pytesseract

        lang = resolve_lang_with_fallback(pytesseract, opts.lang)
        min_conf = max(0.0, min(1.0, float(opts.min_confidence)))
        tmp_path = _write_temp(image_bytes)
        try:
            if min_conf <= 0:
                text = _call_with_timeout(
                    pytesseract.image_to_string,
                    tmp_path,
                    lang=lang,
                    timeout=opts.timeout_s,
                )
                return OcrResult(
                    text=str(text).strip(),
                    lines=_lines_from_plain_text(text),
                    engine=self.name,
                    lang=lang,
                    quality=QUALITY_OK if str(text).strip() else QUALITY_EMPTY,
                )

            data = _call_with_timeout(
                pytesseract.image_to_data,
                tmp_path,
                lang=lang,
                output_type=pytesseract.Output.DICT,
                timeout=opts.timeout_s,
            )
            lines, best = _lines_from_data(data, min_conf)
            text = "\n".join(line.text for line in lines if line.text)
            if not text.strip():
                quality = QUALITY_EMPTY
            elif best < max(min_conf + 0.2, 0.6):
                quality = QUALITY_LOW_CONFIDENCE
            else:
                quality = QUALITY_OK
            return OcrResult(
                text=text,
                lines=tuple(lines),
                engine=self.name,
                lang=lang,
                quality=quality,
            )
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)


def _write_temp(image_bytes: bytes) -> str:
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    try:
        handle.write(image_bytes)
        return handle.name
    finally:
        handle.close()


def _call_with_timeout(func: Any, *args: Any, timeout: float, **kwargs: Any) -> Any:
    """调用 pytesseract；旧版本/测试桩不接受 timeout 时退回无超时调用。"""
    try:
        return func(*args, timeout=timeout, **kwargs)
    except TypeError:
        return func(*args, **kwargs)


def resolve_lang_with_fallback(
    pytesseract_module: Any, requested: Optional[str] = None
) -> str:
    """把统一语言标签映射为 tesseract 语言串，并与已安装语言包求交集。"""
    normalized = _normalize_requested(requested)
    requested_parts = [seg for seg in normalized.split("+") if seg]
    try:
        installed = set(pytesseract_module.get_languages(config=""))
    except Exception:  # noqa: BLE001 — 枚举失败则不回退，交由 tesseract 报错
        return "+".join(requested_parts)
    usable = [seg for seg in requested_parts if seg in installed]
    if usable:
        return "+".join(usable)
    logger.warning(
        "OCR 语言包 %s 均未安装（已装: %s），回退 eng",
        requested_parts,
        sorted(installed),
    )
    return "eng" if "eng" in installed else normalized


def _normalize_requested(requested: Optional[str]) -> str:
    """统一标签 → tesseract 语言串。"""
    value = (requested or "").strip()
    if not value or value == "auto":
        return os.environ.get(_LANG_ENV_VAR, _DEFAULT_LANG).strip() or "eng"
    if value == "ch":
        return "chi_sim+eng"
    if value == "en":
        return "eng"
    return value


def _lines_from_data(data: Dict[str, Any], min_conf: float) -> Tuple[List[OcrLine], float]:
    """按 block/par/line 聚合逐词结果，过滤低置信度词。"""
    words = data.get("text", []) or []
    confs = data.get("conf", []) or []
    blocks = data.get("block_num", []) or []
    pars = data.get("par_num", []) or []
    line_nums = data.get("line_num", []) or []
    lefts = data.get("left", []) or []
    tops = data.get("top", []) or []
    widths = data.get("width", []) or []
    heights = data.get("height", []) or []

    grouped: Dict[Tuple[int, int, int], Dict[str, Any]] = {}
    best = 0.0
    for index, raw_word in enumerate(words):
        word = str(raw_word).strip()
        if not word:
            continue
        try:
            conf_v = float(confs[index]) / 100.0
        except (IndexError, TypeError, ValueError):
            conf_v = -1.0
        if conf_v < min_conf:
            continue
        best = max(best, conf_v)
        key = (
            _safe_int(blocks, index),
            _safe_int(pars, index),
            _safe_int(line_nums, index),
        )
        entry = grouped.setdefault(key, {"words": [], "confs": [], "box": None})
        entry["words"].append(word)
        entry["confs"].append(conf_v)
        box = _word_box(lefts, tops, widths, heights, index)
        if box is not None:
            entry["box"] = _union_box(entry["box"], box)

    lines: List[OcrLine] = []
    for key in sorted(grouped):
        entry = grouped[key]
        conf = sum(entry["confs"]) / len(entry["confs"]) if entry["confs"] else 0.0
        lines.append(
            OcrLine(
                text=" ".join(entry["words"]),
                confidence=conf,
                bbox=entry["box"],
            )
        )
    return lines, best


def _lines_from_plain_text(text: Any) -> Tuple[OcrLine, ...]:
    raw = str(text or "")
    return tuple(
        OcrLine(text=line.strip(), confidence=0.0)
        for line in raw.splitlines()
        if line.strip()
    )


def _safe_int(values: Any, index: int) -> int:
    try:
        return int(values[index])
    except (IndexError, TypeError, ValueError):
        return 0


def _word_box(
    lefts: Any, tops: Any, widths: Any, heights: Any, index: int
) -> Optional[Tuple[int, int, int, int]]:
    try:
        left = int(lefts[index])
        top = int(tops[index])
        width = int(widths[index])
        height = int(heights[index])
    except (IndexError, TypeError, ValueError):
        return None
    return (left, top, left + width, top + height)


def _union_box(
    current: Optional[Tuple[int, int, int, int]],
    addition: Tuple[int, int, int, int],
) -> Tuple[int, int, int, int]:
    if current is None:
        return addition
    return (
        min(current[0], addition[0]),
        min(current[1], addition[1]),
        max(current[2], addition[2]),
        max(current[3], addition[3]),
    )
