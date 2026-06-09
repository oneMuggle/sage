"""LLM 通用代理路由。

解决问题:浏览器在跨源场景下无法直接调用远端 LLM(Ollama / OpenAI 等),
即便 Ollama 配 ``OLLAMA_ORIGINS=*`` 也常因 webview / 网络 / 监听地址
等问题仍然被拦截。本路由让前端永远只跟本机 FastAPI 对话,
由后端用 ``httpx`` 透传到 ``X-LLM-Provider-Url`` 头部指定的上游,
完全绕开 CORS。

设计要点(见 ``docs/technical/21-llm-proxy.md``):

- 上游 URL **通过 header 传**,不进环境变量,支持多端点共存
- 路由是**通用 byte-passthrough**,不解析 OpenAI 协议体
- 错误模型:5 类结构化 detail + 上游原始状态码透传

安全边界(本地桌面 app 假定):

- 上游 URL 由用户在前端「端点」UI 自行输入,后端不做 IP allowlist —
  强行限制会打断用户主用例(局域网内的 Ollama)
- 但拒绝带 userinfo 的 URL(``http://user:pass@host``),防止凭据在 log 中泄露
- ``..`` 路径段会被 ``posixpath.normpath`` 规范化,若试图逃出上游根则 400
"""

from __future__ import annotations

import logging
import posixpath
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request, Response

logger = logging.getLogger(__name__)

router = APIRouter()

# 透传请求 / 响应头时需过滤的 hop-by-hop 头(RFC 7230 §6.1)
HOP_BY_HOP_HEADERS: frozenset[str] = frozenset(
    {
        "host",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "content-length",
    }
)

# 代理专用、不应回流到上游的 header
PROXY_INTERNAL_HEADERS: frozenset[str] = frozenset({"x-llm-provider-url"})

PROXY_TIMEOUT_SECONDS: float = 60.0


def _filter_request_headers(request: Request) -> dict[str, str]:
    """复制请求头到 dict,过滤 hop-by-hop 与代理内部头。"""
    return {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in HOP_BY_HOP_HEADERS and k.lower() not in PROXY_INTERNAL_HEADERS
    }


def _filter_response_headers(headers: httpx.Headers) -> dict[str, str]:
    """复制上游响应头到 dict,过滤 hop-by-hop。"""
    return {k: v for k, v in headers.items() if k.lower() not in HOP_BY_HOP_HEADERS}


def _safe_url_for_log(provider_url: str, max_len: int = 80) -> str:
    """生成 log-safe URL 表示:剥 userinfo、限长。

    ``http://user:secret@host:11434`` → ``http://host:11434``
    """
    try:
        p = urlparse(provider_url)
    except ValueError:
        return "<unparseable>"
    host = p.hostname or ""
    port = f":{p.port}" if p.port else ""
    safe = f"{p.scheme}://{host}{port}"
    if len(safe) > max_len:
        safe = safe[: max_len - 3] + "..."
    return safe


@router.api_route(
    "/llm/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    # 透传路由,接受任意 path,OpenAPI schema 表达不出语义,隐藏避免重复 ID 警告
    include_in_schema=False,
)
async def proxy_to_llm(path: str, request: Request) -> Response:
    """把任意 HTTP 方法透传到 ``X-LLM-Provider-Url`` 指定的上游。

    请求示例::

        POST /api/v1/llm/v1/chat/completions
        X-LLM-Provider-Url: http://192.168.1.10:11434
        Authorization: Bearer sk-...   (可空)
        Content-Type: application/json

        {"model": "llama3", "messages": [...]}

    错误模型(``detail`` 是结构化 dict):

    - ``{"type": "missing_provider_url", ...}`` → 400
    - ``{"type": "invalid_provider_url", ...}`` → 400
    - ``{"type": "upstream_timeout", ...}`` → 504
    - ``{"type": "upstream_unreachable", ...}`` → 502
    - ``{"type": "upstream_transport_error", ...}`` → 502
    - 上游 4xx / 5xx 透传(状态码 + body)
    """
    # 1. 提取并校验上游 URL
    provider_url = request.headers.get("X-LLM-Provider-Url", "").strip()
    if not provider_url:
        raise HTTPException(
            status_code=400,
            detail={
                "type": "missing_provider_url",
                "message": "X-LLM-Provider-Url header is required",
            },
        )
    if not (provider_url.startswith("http://") or provider_url.startswith("https://")):
        raise HTTPException(
            status_code=400,
            detail={
                "type": "invalid_provider_url",
                "message": (
                    f"X-LLM-Provider-Url must start with http:// or https://, "
                    f"got: {_safe_url_for_log(provider_url)!r}"
                ),
            },
        )
    # 拒绝带 userinfo 的 URL(http://user:pass@host)— 凭据会泄露到 log
    try:
        parsed = urlparse(provider_url)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "type": "invalid_provider_url",
                "message": f"X-LLM-Provider-Url unparseable: {exc!s}",
            },
        ) from exc
    if parsed.username or parsed.password:
        raise HTTPException(
            status_code=400,
            detail={
                "type": "invalid_provider_url",
                "message": "X-LLM-Provider-Url must not contain userinfo (user:pass@)",
            },
        )

    # 2. 规范化 path(``posixpath.normpath`` 把 ``..``/``.`` 折叠,但永远不产生 ``/..`` —
    #    路径在语法上被约束在上游根内,不会"逃出")。空 path → ``/``。
    raw_path = path or ""
    normalized = posixpath.normpath("/" + raw_path.lstrip("/"))

    # 3. 重建上游 URL(保留查询串,去掉上游末尾斜杠避免双斜杠)
    base = provider_url.rstrip("/")
    qs = request.url.query
    upstream_url = f"{base}{normalized}"
    if qs:
        upstream_url = f"{upstream_url}?{qs}"

    # 4. 透传头部与 body
    fwd_headers = _filter_request_headers(request)
    body: bytes | None = (
        await request.body() if request.method in {"POST", "PUT", "PATCH"} else None
    )

    # 5. 代理请求
    logger.info(
        "llm_proxy: %s %s -> %s",
        request.method,
        request.url.path,
        _safe_url_for_log(upstream_url),
    )
    async with httpx.AsyncClient(timeout=httpx.Timeout(PROXY_TIMEOUT_SECONDS)) as client:
        try:
            upstream_resp = await client.request(
                method=request.method,
                url=upstream_url,
                headers=fwd_headers,
                content=body,
            )
        except httpx.TimeoutException as exc:
            logger.warning("llm_proxy timeout: %s", _safe_url_for_log(upstream_url))
            raise HTTPException(
                status_code=504,
                detail={
                    "type": "upstream_timeout",
                    "message": f"Upstream timeout after {PROXY_TIMEOUT_SECONDS}s: {exc!s}",
                },
            ) from exc
        except httpx.ConnectError as exc:
            logger.warning(
                "llm_proxy connect error: %s — %s",
                _safe_url_for_log(upstream_url),
                exc,
            )
            raise HTTPException(
                status_code=502,
                detail={
                    "type": "upstream_unreachable",
                    "message": f"Cannot connect to upstream: {exc!s}",
                },
            ) from exc
        except httpx.TransportError as exc:
            # 兜底:其它传输层错误(half-close、协议错、网络错)统一 502
            logger.warning(
                "llm_proxy transport error: %s — %s",
                _safe_url_for_log(upstream_url),
                exc,
            )
            raise HTTPException(
                status_code=502,
                detail={
                    "type": "upstream_transport_error",
                    "message": f"Upstream transport error: {exc!s}",
                },
            ) from exc

    # 6. 透传响应(过滤 hop-by-hop 响应头)
    resp_headers = _filter_response_headers(upstream_resp.headers)
    return Response(
        content=upstream_resp.content,
        status_code=upstream_resp.status_code,
        headers=resp_headers,
    )
