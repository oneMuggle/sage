"""OCR 引擎协议（Python 3.8 安全）。

引擎接收原始图片字节，自行负责解码（避免依赖 Pillow）。``available()``
必须是无副作用的轻量探测，供能力位与自动选择使用。
"""

from __future__ import annotations

from typing import Protocol, Tuple

from .models import OcrOptions, OcrResult


class OcrEngine(Protocol):
    """OCR 引擎接口。"""

    name: str

    def available(self) -> Tuple[bool, str]:
        """返回 ``(可用, 缺失原因)``；缺失原因为空串表示可用。"""
        ...

    def recognize(self, image_bytes: bytes, opts: OcrOptions) -> OcrResult:
        """识别一张图片；失败时应抛出异常，由服务层统一折叠。"""
        ...
