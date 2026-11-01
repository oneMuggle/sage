#!/usr/bin/env python3
"""Tesseract real-engine smoke (CI / local).

生成一张英文合成图，直接调用 Sage 的 TesseractEngine，验证：
- Tesseract 可执行文件可定位（PATH 或 SAGE_TESSERACT_PATH）；
- 语言包 eng 可用；
- 识别结果包含预期文字。

依赖：Pillow + pytesseract + Tesseract 二进制（含 eng 语言包）。
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXPECTED_TOKENS = ("SAGE", "OCR", "12345")


def _font():
    from PIL import ImageFont

    for candidate in (
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, 48)
        except OSError:
            continue
    return ImageFont.load_default()


def _image_bytes() -> bytes:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (900, 220), "white")
    draw = ImageDraw.Draw(image)
    draw.text((40, 70), "SAGE OCR 12345", fill="black", font=_font())
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def main() -> int:
    from backend.services.ocr.engines.tesseract import TesseractEngine
    from backend.services.ocr.models import OcrOptions

    engine = TesseractEngine()
    available, reason = engine.available()
    if not available:
        print(f"tesseract unavailable: {reason}")
        return 2

    result = engine.recognize(
        _image_bytes(),
        OcrOptions(lang="en", min_confidence=0.2, timeout_s=30.0),
    )
    text = (result.text or "").strip()
    print(f"engine={result.engine} quality={result.quality} text={text!r}")

    upper = text.upper()
    missing = [token for token in EXPECTED_TOKENS if token not in upper]
    if missing or not result.ok:
        print(f"tesseract smoke failed: missing={missing} error={result.error}")
        return 1
    print("tesseract smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
