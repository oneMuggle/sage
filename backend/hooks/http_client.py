"""HTTP Hook 客户端 (Phase 5)。

HTTP hooks 是用户显式配置的外部回调:

- 只允许 http/https URL (配置层已校验);
- 请求体为与 shell hook 相同的 JSON payload;
- headers 支持 ``${env:NAME}`` 环境变量替换, 不支持把 secret 写进配置;
- 响应必须是 JSON object, 决策字段由 runner 统一解析;
- 超时 / 网络错误 / 非 JSON / 超大响应全部 fail-open。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

MAX_RESPONSE_BYTES = 256 * 1024
_ALLOWED_METHODS = ("GET", "POST", "PUT", "PATCH")


def resolve_header_value(value: str) -> str:
    """替换 ``${env:NAME}`` 占位符; 未设置环境变量替换为空串。"""
    result = value
    marker = "${env:"
    while marker in result:
        start = result.find(marker)
        end = result.find("}", start + len(marker))
        if end < 0:
            break
        name = result[start + len(marker) : end]
        result = result[:start] + os.environ.get(name, "") + result[end + 1 :]
    return result


def resolve_headers(raw: Any) -> Dict[str, str]:
    """解析并脱离原对象复制 header 字典。"""
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): resolve_header_value(value)
        for key, value in raw.items()
        if isinstance(key, str) and isinstance(value, str)
    }


async def send_http_hook(  # noqa: PLR0911 — fail-open 分支式守卫, 每路 return 都清晰
    url: str,
    payload: Dict[str, Any],
    *,
    method: str = "POST",
    headers: Any = None,
    timeout_seconds: float = 10.0,
) -> Optional[Dict[str, Any]]:
    """发送 HTTP hook 请求并返回 JSON object; 失败返回 None (fail-open)。"""
    if method not in _ALLOWED_METHODS:
        logger.warning("hooks: unsupported HTTP method %r (fail-open)", method)
        return None
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        logger.warning("hooks: unsupported HTTP URL (fail-open): %r", url)
        return None

    request_headers = {"Content-Type": "application/json"}
    request_headers.update(resolve_headers(headers))
    try:
        timeout = httpx.Timeout(timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await client.request(
                method,
                url,
                json=payload,
                headers=request_headers,
            )
        if len(response.content) > MAX_RESPONSE_BYTES:
            logger.warning("hooks: HTTP response exceeds %d bytes (fail-open)", MAX_RESPONSE_BYTES)
            return None
        if response.status_code < 200 or response.status_code >= 300:
            logger.warning("hooks: HTTP hook returned status %s (fail-open)", response.status_code)
            return None
        data = response.json()
        if not isinstance(data, dict):
            logger.warning("hooks: HTTP hook returned non-object JSON (fail-open)")
            return None
        return data
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.warning("hooks: HTTP hook request failed (fail-open): %s", exc)
        return None
    except Exception as exc:  # pragma: no cover — 防御性
        logger.warning("hooks: HTTP hook unexpected failure (fail-open): %s", exc)
        return None
