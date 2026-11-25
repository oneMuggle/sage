"""内置外部服务声明 —— 当前仅 MinerU 文档解析。"""

from __future__ import annotations

from typing import Any, Dict

from backend.domain.document_parse import (
    DEFAULT_MAX_UPLOAD_MB,
    DEFAULT_MIN_QUALITY,
    DEFAULT_TIER,
    DEFAULT_TIMEOUT_SECONDS,
)
from backend.services.external_services.registry import register_service
from backend.services.external_services.spec import EnvBinding, ExternalServiceSpec, SecretField


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


async def _probe_mineru(values: Dict[str, Any]) -> Dict[str, Any]:
    # 惰性导入：探活只在状态查询时触发，避免注册表加载拖入 httpx 依赖链。
    from backend.adapters.out.document_parse.mineru_client import MineruClient

    client = MineruClient(
        base_url=str(values.get("baseUrl") or ""),
        api_key=str(values.get("apiKey") or ""),
        timeout_seconds=_as_float(values.get("timeoutSeconds"), DEFAULT_TIMEOUT_SECONDS),
    )
    return await client.probe()


MINERU_SPEC = ExternalServiceSpec(
    name="mineru",
    preference_key="mineru_service",
    title="MinerU 文档解析",
    api_prefix="mineru",
    defaults={
        "enabled": False,
        "baseUrl": "",
        "apiKey": "",
        "defaultTier": DEFAULT_TIER,
        "timeoutSeconds": DEFAULT_TIMEOUT_SECONDS,
        "maxUploadMb": DEFAULT_MAX_UPLOAD_MB,
        "useInChatAttachment": True,
        "minQualityThreshold": DEFAULT_MIN_QUALITY,
    },
    aliases={
        "baseUrl": ["base_url"],
        "apiKey": ["api_key"],
        "defaultTier": ["default_tier"],
        "timeoutSeconds": ["timeout_seconds"],
        "maxUploadMb": ["max_upload_mb"],
        "useInChatAttachment": ["use_in_chat_attachment"],
        "minQualityThreshold": ["min_quality_threshold"],
    },
    env_bindings=[
        EnvBinding("baseUrl", "SAGE_MINERU_BASE_URL"),
        EnvBinding("apiKey", "SAGE_MINERU_API_KEY"),
        EnvBinding("defaultTier", "SAGE_MINERU_TIER"),
        EnvBinding("timeoutSeconds", "SAGE_MINERU_TIMEOUT_SECONDS"),
    ],
    secret_fields=[SecretField("apiKey", "mineru:api_key")],
    probe=_probe_mineru,
)

register_service(MINERU_SPEC)
