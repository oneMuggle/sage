"""OCR 服务：引擎选择、图片解码、缓存、失败折叠。

关键语义：
- **失败不抛出**：``recognize_*`` 永远返回 ``OcrResult``；调用方按
  ``result.ok / quality / error`` 决定展示，聊天链路不会因 OCR 崩溃；
- **无 Pillow 依赖**：引擎自行解码（RapidOCR/OpenCV 或 tesseract 临时文件）；
- **配置动态读取**：每次调用读取 ``ocr_config``，设置修改无需重启；
- **进程内 LRU 缓存**：键为 (sha256, engine, lang, min_confidence)，只存
  文本与元数据，不落盘。
"""

from __future__ import annotations

import base64
import hashlib
import threading
import time
from collections import OrderedDict
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .config import OcrConfig, load_ocr_config
from .engine import OcrEngine
from .engines.rapidocr import RapidOcrEngine
from .engines.tesseract import TesseractEngine
from .models import (
    MAX_IMAGE_BYTES,
    QUALITY_FAILED,
    OcrOptions,
    OcrResult,
)

_CACHE_LIMIT = 128


class OcrService:
    """统一 OCR 入口。"""

    def __init__(
        self,
        engines: Optional[List[OcrEngine]] = None,
        config_provider: Optional[Callable[[], OcrConfig]] = None,
    ) -> None:
        self._engines: List[OcrEngine] = (
            list(engines)
            if engines is not None
            else [RapidOcrEngine(), TesseractEngine()]
        )
        self._config_provider = config_provider or load_ocr_config
        self._cache: OrderedDict[Tuple[Any, ...], OcrResult] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def config(self) -> OcrConfig:
        return self._config_provider()

    def _find_engine(self, name: str) -> Optional[OcrEngine]:
        for engine in self._engines:
            if engine.name == name:
                return engine
        return None

    def _select_engine(self, config: OcrConfig) -> Tuple[Optional[OcrEngine], str]:
        """按配置选择引擎；返回 ``(engine, 不可用原因)``。"""
        if config.engine != "auto":
            engine = self._find_engine(config.engine)
            if engine is None:
                return None, f"未知 OCR 引擎: {config.engine}"
            ok, reason = engine.available()
            return (engine, "") if ok else (None, reason)
        reasons: List[str] = []
        for engine in self._engines:
            ok, reason = engine.available()
            if ok:
                return engine, ""
            if reason:
                reasons.append(f"{engine.name}: {reason}")
        return None, "; ".join(reasons) or "没有可用的 OCR 引擎"

    def capabilities(self) -> Dict[str, Any]:
        config = self.config
        selected, reason = self._select_engine(config)
        engine_status = []
        for engine in self._engines:
            ok, engine_reason = engine.available()
            engine_status.append(
                {"name": engine.name, "available": ok, "reason": engine_reason}
            )
        languages = None
        if selected is not None and getattr(selected, "name", "") == "tesseract":
            try:
                languages = selected.languages()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 — 枚举失败不影响能力位
                languages = None
        return {
            "enabled": config.enabled,
            "engine": config.engine,
            "selected_engine": selected.name if selected is not None else None,
            "available": bool(config.enabled and selected is not None),
            "reason": reason,
            "lang": config.lang,
            "prefer_local_for_images": config.prefer_local_for_images,
            "engines": engine_status,
            "languages": languages,
        }

    def is_available(self) -> bool:
        return bool(self.capabilities().get("available"))

    def recognize_bytes(  # noqa: PLR0911 — 守卫链逐条 return 更直观
        self,
        image_bytes: bytes,
        *,
        source: str = "",
        lang: Optional[str] = None,
        min_confidence: Optional[float] = None,
        timeout_s: Optional[float] = None,
    ) -> OcrResult:
        """识别原始图片字节；任何异常都折叠为失败结果。"""
        config = self.config
        if not config.enabled:
            return _failure("", lang or config.lang, "", "ocr_disabled")
        if not image_bytes:
            return _failure("", lang or config.lang, "", "empty_image")
        if len(image_bytes) > MAX_IMAGE_BYTES:
            return _failure("", lang or config.lang, "", "image_too_large")

        digest = hashlib.sha256(image_bytes).hexdigest()
        engine, reason = self._select_engine(config)
        if engine is None:
            return _failure("", lang or config.lang, digest, reason)

        opts = OcrOptions(
            lang=(lang or config.lang),
            min_confidence=(
                config.min_confidence if min_confidence is None else min_confidence
            ),
            max_side=config.max_side,
            timeout_s=config.timeout_s if timeout_s is None else timeout_s,
        )
        cache_key = (digest, engine.name, opts.lang, round(opts.min_confidence, 4))
        cached = self._cache_get(cache_key)
        if cached is not None:
            return replace(cached, cached=True)

        started = time.monotonic()
        try:
            result = engine.recognize(image_bytes, opts)
        except Exception as exc:  # noqa: BLE001 — OCR 故障不升级
            duration_ms = int((time.monotonic() - started) * 1000)
            return _failure(engine.name, opts.lang, digest, str(exc), duration_ms)

        duration_ms = int((time.monotonic() - started) * 1000)
        result = replace(
            result,
            engine=result.engine or engine.name,
            lang=result.lang or opts.lang,
            duration_ms=duration_ms,
            image_sha256=digest,
        )
        if result.ok:
            self._cache_put(cache_key, result)
        return result

    def recognize_data_url(self, data_url: str, **kwargs: Any) -> OcrResult:
        """识别 ``data:image/...;base64,...``。"""
        if not isinstance(data_url, str) or not data_url.startswith("data:image/"):
            return _failure("", kwargs.get("lang") or "auto", "", "invalid_image_data_url")
        try:
            _, _, payload = data_url.partition(",")
            if not payload:
                raise ValueError("missing base64 payload")
            image_bytes = base64.b64decode(payload, validate=True)
        except Exception as exc:  # noqa: BLE001
            return _failure("", kwargs.get("lang") or "auto", "", str(exc))
        return self.recognize_bytes(image_bytes, source="data_url", **kwargs)

    def recognize_path(self, path: str, **kwargs: Any) -> OcrResult:
        """识别本地图片路径（调用方负责工作区边界校验）。"""
        try:
            file_path = Path(path)
            size = file_path.stat().st_size
            if size > MAX_IMAGE_BYTES:
                return _failure("", kwargs.get("lang") or "auto", "", "image_too_large")
            image_bytes = file_path.read_bytes()
        except OSError as exc:
            return _failure("", kwargs.get("lang") or "auto", "", str(exc))
        return self.recognize_bytes(image_bytes, source="path", **kwargs)

    # -- cache ---------------------------------------------------------

    def _cache_get(self, key: Tuple[Any, ...]) -> Optional[OcrResult]:
        with self._lock:
            value = self._cache.get(key)
            if value is None:
                return None
            self._cache.move_to_end(key)
            return value

    def _cache_put(self, key: Tuple[Any, ...], value: OcrResult) -> None:
        with self._lock:
            self._cache[key] = value
            self._cache.move_to_end(key)
            while len(self._cache) > _CACHE_LIMIT:
                self._cache.popitem(last=False)

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()


def _failure(
    engine: str,
    lang: str,
    image_sha256: str,
    error: str,
    duration_ms: int = 0,
) -> OcrResult:
    return OcrResult(
        engine=engine,
        lang=lang or "auto",
        image_sha256=image_sha256,
        duration_ms=duration_ms,
        quality=QUALITY_FAILED,
        error=error,
    )


_global_service: Optional[OcrService] = None
_global_lock = threading.Lock()


def get_ocr_service() -> OcrService:
    """进程级单例；配置每次调用动态读取。"""
    global _global_service
    if _global_service is None:
        with _global_lock:
            if _global_service is None:
                _global_service = OcrService()
    return _global_service


def init_ocr_service(service: Optional[OcrService] = None) -> OcrService:
    """显式装配（测试 / lifespan 用）。"""
    global _global_service
    with _global_lock:
        _global_service = service or OcrService()
    return _global_service


def reset_ocr_service() -> None:
    """清空单例（测试用）。"""
    global _global_service
    with _global_lock:
        _global_service = None
