"""Wiki LLM 凭据兜底解析。

渲染层从 ``GET /api/v1/settings`` 拿到的 ``endpoint.apiKey`` 已被脱敏为空串
(``backend/data/settings_canonicalizer.py::redact_secrets``)。前端启动时通常会
从 localStorage 缓存恢复真实 key，但缓存丢失/换机/首次启动时 wiki 请求会带空
key 直接打上游(401) —— 而聊天主链路走后端 ``llm_factory`` 从持久化设置解析,
不受影响。

本模块在请求 key 为空时，从后端持久化的 ``app_settings`` 按 ``baseUrl``
兜底解析真实 key，保证 wiki ingest/chat/research 与聊天主链路同源。
"""

from __future__ import annotations

import logging
from typing import Any, List

logger = logging.getLogger(__name__)


def _normalize_base_url(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().rstrip("/").lower()


def _stored_endpoints() -> List[Any]:
    try:
        from backend.data.settings_canonicalizer import to_camel
        from backend.data.settings_repo import SettingsRepository

        raw = SettingsRepository().get_json("app_settings")
    except Exception as exc:  # DB 不可用/损坏 — 降级为空, 不阻断请求
        logger.warning("wiki_credentials: failed to read app_settings: %s", exc)
        return []
    if not isinstance(raw, dict):
        return []
    endpoints = to_camel(raw).get("endpoints")
    return endpoints if isinstance(endpoints, list) else []


def resolve_llm_api_key(base_url: str, provided_key: str) -> str:
    """返回请求携带的 key；为空时按 ``baseUrl`` 从 app_settings 兜底解析。

    非空 key 直接透传（尊重用户刚在 UI 输入、尚未落库的新 key）。
    匹配不到或读取失败时原样返回 ``provided_key``（可能为空串）。
    """
    if isinstance(provided_key, str) and provided_key.strip():
        return provided_key
    target = _normalize_base_url(base_url)
    if not target:
        return provided_key or ""
    for endpoint in _stored_endpoints():
        if not isinstance(endpoint, dict):
            continue
        if _normalize_base_url(endpoint.get("baseUrl")) != target:
            continue
        stored = endpoint.get("apiKey")
        if isinstance(stored, str) and stored:
            return stored
    return provided_key or ""
