"""文档解析编排：路由、熔断、缓存。仅依赖领域契约与注入的引擎/缓存。"""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from typing import Callable, Optional, Protocol

from backend.domain.document_parse import (
    ENGINE_AUTO,
    ENGINE_CHOICES,
    ENGINE_LOCAL,
    ENGINE_MINERU,
    MineruSettings,
    ParseEngine,
    ParseRequest,
    ParseResult,
)

logger = logging.getLogger(__name__)


class ParseCache(Protocol):
    def get(self, content_hash: str, engine: str) -> Optional[ParseResult]: ...

    def put(self, content_hash: str, engine: str, result: ParseResult) -> None: ...


class CircuitBreaker:
    """MinerU 连续失败熔断（冷却期内不再尝试）。"""

    def __init__(
        self,
        threshold: int = 3,
        cooldown_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._threshold = threshold
        self._cooldown = cooldown_seconds
        self._clock = clock
        self._failures = 0
        self._opened_at: Optional[float] = None

    def closed(self) -> bool:
        if self._opened_at is None:
            return True
        if self._clock() - self._opened_at >= self._cooldown:
            self._opened_at = None
            self._failures = 0
            return True
        return False

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold:
            self._opened_at = self._clock()


class DocumentParseService:
    def __init__(
        self,
        *,
        local: ParseEngine,
        mineru_factory: Callable[[MineruSettings], ParseEngine],
        cache: ParseCache,
        settings_loader: Callable[[], MineruSettings],
        breaker: Optional[CircuitBreaker] = None,
    ) -> None:
        self._local = local
        self._mineru_factory = mineru_factory
        self._cache = cache
        self._load_settings = settings_loader
        self._breaker = breaker or CircuitBreaker()
        self._mineru_engine: Optional[ParseEngine] = None
        self._mineru_signature: Optional[tuple] = None

    async def parse(self, request: ParseRequest) -> ParseResult:
        settings = self._load_settings()
        hint = (
            request.engine_hint if request.engine_hint in ENGINE_CHOICES else ENGINE_AUTO
        )

        if hint == ENGINE_MINERU:
            if self._block_reason(settings, request, None, hint) is None:
                done = await self._try_mineru(settings, request)
                if done is not None:
                    return done
            local = await self._cached_parse(self._local, request, ENGINE_LOCAL)
            return local.with_warning("mineru_failed")

        local = await self._cached_parse(self._local, request, ENGINE_LOCAL)
        if self._block_reason(settings, request, local.quality_score, hint) is not None:
            return local
        done = await self._try_mineru(settings, request)
        if done is not None:
            return done
        return local.with_warning("mineru_failed")

    # ── 内部 ────────────────────────────────────────────────────
    def _block_reason(  # noqa: PLR0911 — 每条早退对应一种明确的阻断原因
        self,
        settings: MineruSettings,
        request: ParseRequest,
        local_score: Optional[float],
        hint: str,
    ) -> Optional[str]:
        if hint == ENGINE_LOCAL:
            return "local_hint"
        if request.extension != "pdf":
            return "non_pdf"
        if not settings.enabled:
            return "disabled"
        if not settings.configured:
            return "not_configured"
        if len(request.content_bytes) > settings.max_upload_mb * 1024 * 1024:
            return "too_large"
        if not self._breaker.closed():
            return "circuit_open"
        if local_score is not None and local_score >= settings.min_quality_threshold:
            return "quality_ok"
        return None

    async def _cached_parse(
        self, engine: ParseEngine, request: ParseRequest, engine_name: str
    ) -> ParseResult:
        key = request.content_hash()
        cached = self._cache.get(key, engine_name)
        if cached is not None:
            return replace(cached, cached=True)
        result = await engine.parse(request)
        self._cache.put(key, engine_name, result)
        return result

    def _engine(self, settings: MineruSettings) -> ParseEngine:
        signature = (
            settings.base_url,
            settings.api_key,
            settings.default_tier,
            settings.timeout_seconds,
        )
        if self._mineru_engine is None or self._mineru_signature != signature:
            self._mineru_engine = self._mineru_factory(settings)
            self._mineru_signature = signature
        return self._mineru_engine

    async def _try_mineru(
        self, settings: MineruSettings, request: ParseRequest
    ) -> Optional[ParseResult]:
        key = request.content_hash()
        cached = self._cache.get(key, ENGINE_MINERU)
        if cached is not None:
            return replace(cached, cached=True)
        try:
            result = await self._engine(settings).parse(request)
        except Exception as exc:  # noqa: BLE001 — 升级失败必须回退本地
            self._breaker.record_failure()
            logger.warning(
                "MinerU 解析失败，回退本地: %s: %s", type(exc).__name__, exc
            )
            return None
        self._breaker.record_success()
        self._cache.put(key, ENGINE_MINERU, result)
        return result
