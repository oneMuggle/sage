"""MinerU 引擎适配：调用客户端并把 docx/html 产物与图片落 MediaStore。"""

from __future__ import annotations

import json
import time
from typing import Callable, Dict, Optional

from backend.domain.document_parse import (
    ENGINE_MINERU,
    OUTPUT_DOCX,
    OUTPUT_HTML,
    OUTPUT_STRUCTURED,
    EngineHealth,
    ParseRequest,
    ParseResult,
)

from .mineru_client import MineruClient


class MineruParseEngine:
    name = ENGINE_MINERU

    def __init__(
        self,
        client: MineruClient,
        tier: str = "standard",
        media_store_factory: Optional[Callable[[], object]] = None,
    ) -> None:
        self._client = client
        self._tier = tier
        self._media_store_factory = media_store_factory
        self._store = None

    def _media_store(self):
        if self._store is None:
            from backend.services.multimodal.media_store import (
                MEDIA_ROOT,
                MediaKind,
                MediaStore,
            )

            self._store = (
                self._media_store_factory()
                if self._media_store_factory is not None
                else MediaStore(root=MEDIA_ROOT)
            )
            self._media_kind = MediaKind
        return self._store

    async def parse(self, request: ParseRequest) -> ParseResult:
        started = time.monotonic()
        if request.output_format == OUTPUT_DOCX:
            formats = ["docx"]
        elif request.output_format == OUTPUT_HTML:
            formats = ["html"]
        else:
            formats = ["default"]
        target_tier = request.tier or self._tier
        output = await self._client.parse_bytes(
            request.content_bytes,
            request.filename,
            page_range=request.page_range,
            output_formats=formats,
            tier=target_tier,
            timeout_seconds=request.timeout_seconds,
        )
        warnings = ["partial_result"] if output.status == "partial" else []
        store = self._media_store()
        if output.file_bytes is not None and output.file_ext:
            ref = store.save(
                content=output.file_bytes,
                kind=self._media_kind.DOCUMENT,
                source="mineru_parse",
                metadata={"original_filename": request.filename},
                ext=output.file_ext,
            )
            return ParseResult(
                text="",
                engine_used=ENGINE_MINERU,
                tier_used=target_tier,
                quality_score=1.0,
                duration_ms=int((time.monotonic() - started) * 1000),
                warnings=warnings,
                media_url=ref.api_url,
            )
        assets: Dict[str, str] = {}
        for name, data in output.images.items():
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else None
            ref = store.save(
                content=data,
                kind=self._media_kind.IMAGE,
                source="mineru_parse",
                metadata={"archive_name": name},
                ext=ext,
            )
            assets[name] = ref.api_url
        text = output.markdown
        if request.output_format == OUTPUT_STRUCTURED and output.structured is not None:
            text = json.dumps(output.structured, ensure_ascii=False)
        return ParseResult(
            text=text,
            engine_used=ENGINE_MINERU,
            structured=output.structured,
            tier_used=target_tier,
            quality_score=1.0,
            duration_ms=int((time.monotonic() - started) * 1000),
            warnings=warnings,
            assets=assets,
        )

    async def health(self) -> EngineHealth:
        info = await self._client.probe()
        return EngineHealth(
            available=bool(info.get("reachable")),
            detail=str(info.get("reason") or info.get("serverAuthMode") or ""),
            server_tiers=info.get("serverTiers"),
            server_version=info.get("serverVersion"),
        )
