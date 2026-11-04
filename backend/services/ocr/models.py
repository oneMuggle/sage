"""OCR 领域模型（纯 dataclass，Python 3.8 安全）。

设计约束：
- 不依赖 Pillow / pydantic / 任何第三方库；
- 所有字段可 JSON 序列化，便于 REST / 工具 / 前端复用；
- ``quality`` 是给 UI 与 LLM 的粗粒度质量信号，不承诺逐字准确率。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

#: 单张图片解码前的字节上限（与聊天图片 5 MiB 对齐，留出编码余量）
MAX_IMAGE_BYTES = 10 * 1024 * 1024

#: 质量信号
QUALITY_OK = "ok"
QUALITY_LOW_CONFIDENCE = "low_confidence"
QUALITY_EMPTY = "empty"
QUALITY_FAILED = "failed"


@dataclass(frozen=True)
class OcrLine:
    """一行识别结果。"""

    text: str
    confidence: float = 0.0
    bbox: Optional[Tuple[int, int, int, int]] = None


@dataclass(frozen=True)
class OcrResult:
    """一次 OCR 的完整结果。"""

    text: str = ""
    lines: Tuple[OcrLine, ...] = ()
    engine: str = ""
    lang: str = "auto"
    duration_ms: int = 0
    image_sha256: str = ""
    cached: bool = False
    quality: str = QUALITY_OK
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.quality != QUALITY_FAILED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "lines": [
                {
                    "text": line.text,
                    "confidence": round(float(line.confidence), 4),
                    "bbox": list(line.bbox) if line.bbox else None,
                }
                for line in self.lines
            ],
            "engine": self.engine,
            "lang": self.lang,
            "duration_ms": self.duration_ms,
            "image_sha256": self.image_sha256,
            "cached": self.cached,
            "quality": self.quality,
            "error": self.error,
        }


@dataclass(frozen=True)
class OcrOptions:
    """单次识别的参数（由 OcrConfig 派生，也可调用方覆盖）。"""

    lang: str = "auto"
    min_confidence: float = 0.4
    max_side: int = 1280
    timeout_s: float = 30.0
    #: RapidOCR 方向分类；截图通常正向，关闭可省 ~30-50% 时间
    use_cls: bool = False
