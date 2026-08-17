"""LLM adapter 共享工具（A2）。

集中各 provider adapter 共用的错误分类逻辑，与
``backend.core.legacy.llm_client.LLMClient._raise_classified_error``
保持同一套分类规则，前端的中文化错误提示因此对所有 provider 一致。
"""

from __future__ import annotations

import logging

import httpx

from backend.core.errors import LLMError, LLMErrorType

logger = logging.getLogger(__name__)


def raise_classified_error(exc: Exception) -> None:
    """把底层异常映射为分类的 ``LLMError`` 并抛出（本方法总是抛异常）。

    分类规则（与 legacy LLMClient 一致）：

    - ``httpx.TimeoutException``    → TIMEOUT
    - ``httpx.ConnectError``        → NETWORK
    - ``httpx.HTTPStatusError``     → AUTH_FAILED (401/403) / RATE_LIMITED (429)
                                      / SERVER_ERROR (5xx) / UNKNOWN (其余)
    - ``ValueError`` / ``KeyError`` → PARSING（``json.JSONDecodeError`` 是
                                      ValueError 子类）
    - 已是 ``LLMError``             → 原样重抛
    - 其余异常                      → UNKNOWN
    """
    if isinstance(exc, LLMError):
        raise exc
    if isinstance(exc, httpx.TimeoutException):
        logger.error("LLM 请求超时: %s", exc)
        raise LLMError(LLMErrorType.TIMEOUT, f"请求 LLM 超时: {exc}") from exc
    if isinstance(exc, httpx.ConnectError):
        logger.error("LLM 连接失败: %s", exc)
        raise LLMError(LLMErrorType.NETWORK, f"无法连接 LLM: {exc}") from exc
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in (401, 403):
            raise LLMError(
                LLMErrorType.AUTH_FAILED, "API Key 无效或过期", status_code=status
            ) from exc
        if status == 429:
            retry_after = None
            try:
                retry_after = int(exc.response.headers.get("retry-after", "0")) or None
            except (ValueError, TypeError):
                retry_after = None
            raise LLMError(
                LLMErrorType.RATE_LIMITED,
                "请求过于频繁，请稍后再试",
                retry_after=retry_after,
            ) from exc
        if 500 <= status < 600:
            raise LLMError(
                LLMErrorType.SERVER_ERROR,
                f"LLM 服务端错误 (HTTP {status})",
                status_code=status,
            ) from exc
        raise LLMError(
            LLMErrorType.UNKNOWN, f"LLM HTTP 错误: {status}", status_code=status
        ) from exc
    if isinstance(exc, (ValueError, KeyError)):  # noqa: UP038  (Py3.8: isinstance 不支持 X | Y)
        logger.error("LLM 响应解析失败: %s", exc)
        raise LLMError(LLMErrorType.PARSING, f"LLM 响应格式异常: {exc}") from exc
    logger.error("LLM 请求未知失败: %s", exc)
    raise LLMError(LLMErrorType.UNKNOWN, f"LLM 请求失败: {exc}") from exc
