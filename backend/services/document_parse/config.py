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


def _pick(raw: Dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in raw:
            return raw[name]
    return None


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


def _env_str(name: str) -> str:
    return os.environ.get(name, "").strip()


def load_mineru_settings() -> MineruSettings:
    try:
        raw = _read_preference()
        base_url = _env_str("SAGE_MINERU_BASE_URL") or str(
            _pick(raw, "baseUrl", "base_url") or ""
        ).strip()
        api_key = _env_str("SAGE_MINERU_API_KEY") or str(
            _pick(raw, "apiKey", "api_key") or ""
        ).strip()
        tier = _env_str("SAGE_MINERU_TIER") or str(
            _pick(raw, "defaultTier", "default_tier") or DEFAULT_TIER
        ).strip()
        timeout_raw = _env_str("SAGE_MINERU_TIMEOUT_SECONDS")
        timeout = _as_float(
            timeout_raw or _pick(raw, "timeoutSeconds", "timeout_seconds"),
            DEFAULT_TIMEOUT_SECONDS,
            5.0,
            3600.0,
        )
        return MineruSettings(
            enabled=_as_bool(_pick(raw, "enabled"), False),
            base_url=base_url,
            api_key=api_key,
            default_tier=tier or DEFAULT_TIER,
            timeout_seconds=timeout,
            max_upload_mb=_as_int(
                _pick(raw, "maxUploadMb", "max_upload_mb"),
                DEFAULT_MAX_UPLOAD_MB,
                1,
                200,
            ),
            use_in_chat_attachment=_as_bool(
                _pick(raw, "useInChatAttachment", "use_in_chat_attachment"), True
            ),
            min_quality_threshold=_as_float(
                _pick(raw, "minQualityThreshold", "min_quality_threshold"),
                DEFAULT_MIN_QUALITY,
                0.0,
                1.0,
            ),
        )
    except Exception:  # noqa: BLE001 — 配置异常不得阻断解析链路
        logger.warning("MinerU 配置解析失败，使用默认值", exc_info=True)
        return MineruSettings()
