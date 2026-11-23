"""本地解析引擎：复用聊天附件的纯文本提取，质量信号决定是否升级 MinerU。

本地引擎不引入新解析器 —— 与聊天附件共用 ``services.attachment_extract``
的同一份分发表，避免两套 PDF/DOCX 行为漂移。
"""

from __future__ import annotations

import asyncio
import time
from typing import Callable, Optional

from backend.domain.document_parse import (
    ENGINE_LOCAL,
    EngineHealth,
    ParseRequest,
    ParseResult,
)
from backend.services.attachment_extract import extract_attachment_text

from .quality import compute_pdf_signals, score_quality


class LocalEngine:
    """``ParseEngine`` 协议实现：线程池提取 + PDF 质量信号。"""

    name = ENGINE_LOCAL

    def __init__(
        self,
        extractor: Optional[Callable[[bytes, str], str]] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._extractor = extractor or extract_attachment_text
        self._clock = clock

    async def parse(self, request: ParseRequest) -> ParseResult:
        loop = asyncio.get_running_loop()
        started = self._clock()
        text = await loop.run_in_executor(
            None, self._extractor, request.content_bytes, request.extension
        )
        quality = 1.0
        if request.extension == "pdf":
            signals = await loop.run_in_executor(
                None, compute_pdf_signals, request.content_bytes
            )
            if signals is not None:
                quality = score_quality(signals)
        return ParseResult(
            text=text,
            engine_used=ENGINE_LOCAL,
            quality_score=quality,
            duration_ms=int((self._clock() - started) * 1000),
        )

    async def health(self) -> EngineHealth:
        return EngineHealth(available=True, detail="local extractor")
