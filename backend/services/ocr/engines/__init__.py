"""本地 OCR 引擎实现（Tesseract / RapidOCR）。"""

from .rapidocr import RapidOcrEngine
from .tesseract import TesseractEngine

__all__ = ["RapidOcrEngine", "TesseractEngine"]
