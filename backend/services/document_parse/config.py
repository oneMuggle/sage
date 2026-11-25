"""MinerU 配置加载：env > preferences（解密） > 默认值。"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

from backend.domain.document_parse import (
    DEFAULT_MAX_UPLOAD_MB,
    DEFAULT_MIN_QUALITY,
    DEFAULT_TIER,
    DEFAULT_TIMEOUT_SECONDS,
    MineruSettings,
)

logger = logging.getLogger(__name__)

MINERU_CONFIG_KEY = "mineru_service"


def _read_preference() -> Dict[str, Any]:
    try:
        from backend.data.settings_repo import SettingsRepository

        raw = SettingsRepository().get(MINERU_CONFIG_KEY)
        if not raw:
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 — 配置读取失败退回默认值
        return {}


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _as_float(value: Any, default: float, low: float, high: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return min(high, max(low, parsed))


def _as_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(high, max(low, parsed))


def load_mineru_settings() -> MineruSettings:
    try:
        from backend.services.external_services.registry import get_service
        from backend.services.external_services.settings import merge_service_settings

        spec = get_service("mineru")
        stored = _read_preference()
        raw = stored if spec is None else merge_service_settings(spec, stored, os.environ)
        return MineruSettings(
            enabled=_as_bool(raw.get("enabled"), False),
            base_url=str(raw.get("baseUrl") or "").strip(),
            api_key=str(raw.get("apiKey") or "").strip(),
            default_tier=str(raw.get("defaultTier") or DEFAULT_TIER).strip() or DEFAULT_TIER,
            timeout_seconds=_as_float(
                raw.get("timeoutSeconds"), DEFAULT_TIMEOUT_SECONDS, 5.0, 3600.0
            ),
            max_upload_mb=_as_int(raw.get("maxUploadMb"), DEFAULT_MAX_UPLOAD_MB, 1, 200),
            use_in_chat_attachment=_as_bool(raw.get("useInChatAttachment"), True),
            min_quality_threshold=_as_float(
                raw.get("minQualityThreshold"), DEFAULT_MIN_QUALITY, 0.0, 1.0
            ),
        )
    except Exception:  # noqa: BLE001 — 配置异常不得阻断解析链路
        logger.warning("MinerU 配置解析失败，使用默认值", exc_info=True)
        return MineruSettings()
