"""OCR 配置读取（preference blob + 环境变量覆盖）。

与 ``backend/memory/embedder_factory`` 同款模式：设置优先、env 兼容、任何
读取失败都回退默认值，不阻塞 OCR 主流程。

preference key: ``ocr_config``（JSON）
- enabled: bool
- engine: "auto" | "rapidocr" | "tesseract"
- lang: "auto" | "ch" | "en"
- prefer_local_for_images: bool
- min_confidence: float (0-1)
- max_side: int
- timeout_s: float
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

#: preference 表 key（SettingsRepository.KEYS 白名单同步加入）
OCR_CONFIG_KEY = "ocr_config"

_VALID_ENGINES = ("auto", "rapidocr", "tesseract")
_VALID_LANGS = ("auto", "ch", "en")


@dataclass(frozen=True)
class OcrConfig:
    """OCR 运行配置。"""

    enabled: bool = True
    engine: str = "auto"
    lang: str = "auto"
    prefer_local_for_images: bool = False
    min_confidence: float = 0.4
    max_side: int = 1280
    timeout_s: float = 30.0
    #: RapidOCR 方向分类；截图默认关闭以提速（扫描件可显式开启）
    use_cls: bool = False


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
    if isinstance(value, (int, float)):  # noqa: UP038 — py3.8 不支持 isinstance(A | B)
        return bool(value)
    return default


def _as_float(value: Any, default: float, *, low: float, high: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, parsed))


def _as_int(value: Any, default: int, *, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, parsed))


def _read_preference() -> Dict[str, Any]:
    """读取 ``ocr_config`` JSON；任何异常都返回空 dict。"""
    try:
        from backend.data.settings_repo import SettingsRepository

        raw = SettingsRepository().get_json(OCR_CONFIG_KEY)
        return raw if isinstance(raw, dict) else {}
    except Exception:  # noqa: BLE001 — settings 不可用属正常路径（测试/首次启动）
        return {}


def _pick(raw: Dict[str, Any], snake: str, camel: str) -> Optional[Any]:
    if snake in raw:
        return raw.get(snake)
    if camel in raw:
        return raw.get(camel)
    return None


def _env_override(raw: Dict[str, Any], env_name: str, key: str) -> Any:
    """env 优先于 preference；未设置返回 preference 值。"""
    env_value = os.environ.get(env_name)
    if env_value is None:
        return raw.get(key)
    return env_value


def load_ocr_config() -> OcrConfig:
    """读取 OCR 配置：preference → env 覆盖 → 默认值。"""
    raw = _read_preference()

    enabled_raw = _env_override(raw, "SAGE_OCR", "enabled")
    enabled = _as_bool(enabled_raw, True)

    engine = str(_pick(raw, "engine", "engine") or "auto").strip().lower()
    if engine not in _VALID_ENGINES:
        engine = "auto"

    lang = str(_env_override(raw, "SAGE_OCR_LANG", "lang") or "auto").strip()
    if not lang:
        lang = "auto"

    prefer_raw = _pick(raw, "prefer_local_for_images", "preferLocalForImages")
    prefer_local = _as_bool(prefer_raw, False)

    default_min = 0.4
    try:
        legacy_min = int(os.environ.get("SAGE_OCR_MIN_CONFIDENCE", "40"))
        default_min = max(0.0, min(1.0, legacy_min / 100.0))
    except (TypeError, ValueError):
        pass
    min_conf_raw = _pick(raw, "min_confidence", "minConfidence")
    min_confidence = _as_float(
        min_conf_raw if min_conf_raw is not None else default_min,
        0.4,
        low=0.0,
        high=1.0,
    )

    max_side = _as_int(
        _pick(raw, "max_side", "maxSide") or 1280, 1280, low=256, high=8192
    )
    timeout_s = _as_float(
        _pick(raw, "timeout_s", "timeoutS") or 30.0, 30.0, low=1.0, high=300.0
    )
    use_cls = _as_bool(_pick(raw, "use_cls", "useCls"), False)

    return OcrConfig(
        enabled=enabled,
        engine=engine,
        lang=lang,
        prefer_local_for_images=prefer_local,
        min_confidence=min_confidence,
        max_side=max_side,
        timeout_s=timeout_s,
        use_cls=use_cls,
    )
