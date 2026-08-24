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

TLS 行为(Task 1 2026-08-23):

- 始终启用证书校验(``verify`` 默认 True); 绝不设置 ``verify=False``.
- import-time ``main.configure_ssl_ca_bundle(certifi.where)`` 把 certifi CA
  bundle 注入 ``SSL_CERT_FILE`` / ``REQUESTS_CA_BUNDLE`` / ``CURL_CA_BUNDLE``,
  httpx 默认会读取这些变量.
- 上游 TLS 证书校验失败 → 结构化 detail ``tls_certificate_failed`` (502),
  不是被吞成 ``upstream_unreachable`` 淹没错误信号.
- CA bundle 不可用 (certifi 缺失 / 文件为空 / 读不到) → 结构化 detail
  ``ca_bundle_unavailable`` (502); 仍然 *不* 关闭校验, 让用户立即看到
  TLS 故障而不是沉默降级.
- 所有 detail ``message`` 字段只放已脱敏的错误描述(不含 API key / 凭据).
"""

from __future__ import annotations

import logging
import os
import posixpath
import ssl
from collections.abc import AsyncIterator
from typing import Dict, FrozenSet, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# 透传请求 / 响应头时需过滤的 hop-by-hop 头(RFC 7230 §6.1)
# 额外过滤 content-encoding: 即使 proxy 向上游发 Accept-Encoding: identity,
# 某些上游仍可能返回 Content-Encoding: gzip。如果不把这个 header 过滤掉,
# httpx 客户端会尝试解压响应,导致 zlib.error: Error -3 while decompressing data。
HOP_BY_HOP_HEADERS: FrozenSet[str] = frozenset(
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
        "content-encoding",  # v2: 防止 httpx 尝试解压已处理的响应
    }
)

# 代理专用、不应回流到上游的 header
PROXY_INTERNAL_HEADERS: FrozenSet[str] = frozenset({"x-llm-provider-url"})

PROXY_TIMEOUT_SECONDS: float = 60.0

# CA bundle 不可用时上报 — 用于结构化 detail.type; 不泄露具体路径
_CA_BUNDLE_ENV_VARS: FrozenSet[str] = frozenset(
    {"SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"}
)


def _is_ca_bundle_available() -> bool:
    """检测 CA bundle 是否可用.

    优先检查 ``SSL_CERT_FILE`` / ``REQUESTS_CA_BUNDLE`` / ``CURL_CA_BUNDLE``
    三个环境变量 (由 ``main.configure_ssl_ca_bundle`` 注入 certifi.where 路径).
    兜底探测 ``ssl.get_default_verify_paths().cafile / capath``: 系统级 bundle
    (OpenSSL ``/etc/ssl/certs`` / Windows cert store 派生文件) 也是合法 CA 源,
    在公司代理只配系统 bundle 不设 env vars 的环境里必须认.

    任一来源存在且路径可读 → True; 全部未设 / 路径缺失 / 不可读 → False.
    """
    from pathlib import Path

    for variable in _CA_BUNDLE_ENV_VARS:
        path_str = os.environ.get(variable)
        if not path_str:
            continue
        path = Path(path_str)
        try:
            if path.is_file() and path.stat().st_size > 0:
                return True
            if path.is_dir() and any(path.iterdir()):
                # capath 是目录, 含已哈希链接的 cert 文件; 任意文件存在即视为可用.
                return True
        except OSError:
            continue

    # 兜底: 探测 Python 进程默认的 CA bundle 路径 (OpenSSL ``DEFAULT@`` 区段).
    # get_default_verify_paths() 在所有 CPython 版本 (>= 3.7) 都返回 cafile/capath
    # 字符串; cafile 通常指向 certifi 注入后的 PEM, capath 指向系统 certs 目录.
    try:
        defaults = ssl.get_default_verify_paths()
    except Exception:  # pragma: no cover — ssl 模块不应抛, 兜底保护
        return False
    for candidate in (defaults.cafile, defaults.capath):
        if not candidate:
            continue
        try:
            path = Path(candidate)
        except (TypeError, ValueError):
            continue
        try:
            if path.is_file() and path.stat().st_size > 0:
                return True
            if path.is_dir() and any(path.iterdir()):
                return True
        except OSError:
            continue
    return False


def _is_tls_certificate_error(exc: BaseException) -> bool:
    """判断 httpx 异常是否来自证书校验失败.

    主路径: 沿异常链 (``__cause__`` / ``__context__`` / ``exceptions``) 递归找
    ``ssl.SSLCertVerificationError`` 实例. Python 3.7+ 起
    ``ssl.SSLCertVerificationError`` 是 ``ssl.SSLError`` 子类, 与 ``str(exc)``
    的字符串匹配无关 — 比关键字匹配更可靠, 不会被 i18n / message 格式变化
    误伤.

    兜底: 字符串匹配 "certificate verify failed" 等关键词. 兜底覆盖罕见情况
    (例: httpcore 在某些版本里把 ``SSLCertVerificationError`` 包装成
    ``RemoteProtocolError`` 丢失 ``__cause__`` 链, 但 str() 里仍带关键词).

    httpx.ConnectError / httpcore.ConnectError 通常 ``__cause__`` 链挂
    ``ssl.SSLCertVerificationError`` (Py3.7+); 也有可能挂在 ``ssl.SSLError``
    但 message 含 "CERTIFICATE_VERIFY_FAILED".
    """
    current: Optional[BaseException] = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ssl.SSLCertVerificationError):
            return True
        # 同级: __cause__ (raise X from Y) → __context__ (implicit) → exceptions
        next_exc: BaseException | None = None
        if current.__cause__ is not None and current.__cause__ is not current:
            next_exc = current.__cause__
        elif current.__context__ is not None and current.__context__ is not current:
            next_exc = current.__context__
        # Python 3.11+ ExceptionGroup 兼容: 沿 .exceptions 拆开递归.
        if hasattr(current, "exceptions") and isinstance(
            current.exceptions, tuple
        ):
            for sub in current.exceptions:
                if _is_tls_certificate_error(sub):
                    return True
        current = next_exc

    # 兜底: 字符串匹配 (httpcore 在某些版本里把 SSL 异常包装, 丢 __cause__ 链).
    msg = str(exc).lower()
    return (
        "certificate verify failed" in msg
        or "ssl: certificate_verify_failed" in msg
        or "certverifyfailed" in msg.replace(" ", "")
        or "ssl_cert_verify" in msg
    )


def build_upstream_url(provider_url: str, path: str, query: str = "") -> str:
    """把 ``provider_url`` + ``path`` 拼成上游 URL,自动去重 ``/v1`` 段。

    用户在「端点」UI 填 baseURL,常见两种习惯:

    - **裸 host** —— ``https://api.openai.com``
    - **含 ``/v1``** —— ``https://api.openai.com/v1``(OpenAI 文档示例)

    前端 ``fetchModels`` / ``testChatCompletion`` 固定拼 ``/v1/models``、
    ``/v1/chat/completions``。若 user 填的 baseURL 已含 ``/v1``,朴素拼接
    会得到 ``https://api.openai.com/v1/v1/models``,上游网关返回
    ``Invalid URL (GET /v1/v1/models)`` 404。

    修复:若 provider_url 以 ``/v1`` 结尾,且 path 已含 ``/v1`` 段,则剥掉
    path 的前导 ``/v1``(只在 path 顶层去一次,不递归)。其他 path 段保持
    原样;query string 原样附加在末尾。

    Args:
        provider_url: 上游根 URL,可能含也可能不含 ``/v1`` 后缀。
        path: FastAPI ``path:path`` 捕获的子路径,例如 ``v1/models``。
        query: 完整 query string(不含前导 ``?``),空字符串表示无。

    Returns:
        拼接后的完整上游 URL。
    """
    base = provider_url.rstrip("/")
    raw_path = path or ""
    normalized = posixpath.normpath("/" + raw_path.lstrip("/"))

    # 去重:baseURL 已含 ``/v1`` + path 顶层是 ``/v1...`` → 剥 path 前导 ``/v1``
    if base.endswith("/v1") and (normalized == "/v1" or normalized.startswith("/v1/")):
        normalized = normalized[3:] or "/"

    upstream_url = f"{base}{normalized}"
    if query:
        upstream_url = f"{upstream_url}?{query}"
    return upstream_url


def _filter_request_headers(request: Request) -> Dict[str, str]:
    """复制请求头到 dict,过滤 hop-by-hop 与代理内部头。"""
    return {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in HOP_BY_HOP_HEADERS and k.lower() not in PROXY_INTERNAL_HEADERS
    }


def _filter_response_headers(headers: httpx.Headers) -> Dict[str, str]:
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

    # 2. 重建上游 URL — 委托给 ``build_upstream_url``,自动去重 ``/v1`` 段
    #    (用户 baseURL 已含 ``/v1`` 时,避免 ``/v1/v1/models``)。
    upstream_url = build_upstream_url(provider_url, path, request.url.query)

    # 4. 透传头部与 body
    fwd_headers = _filter_request_headers(request)
    body: bytes | None = (
        await request.body() if request.method in {"POST", "PUT", "PATCH"} else None
    )

    # v2: 检测是否是 SSE/streaming 请求 — `LLMClient.chat_stream` 现在也走 proxy,
    # 需要把上游 chunked 响应原样回传给浏览器/调用方,不能一次性 read body。
    # 触发条件(任一):
    #   1. Accept 头含 text/event-stream (SSE 标准)
    #   2. query string `stream=true` (OpenAI 流式 chat completion 约定)
    accept = request.headers.get("accept", "")
    is_streaming = (
        "text/event-stream" in accept.lower() or request.query_params.get("stream") == "true"
    )

    # 5. 代理请求
    logger.info(
        f"[DEBUG] llm_proxy: {request.method} {request.url.path} -> {upstream_url}"
        f"{'' if not is_streaming else ' (streaming)'}"
        f", headers: X-LLM-Provider-Url={provider_url}, Accept-Encoding={request.headers.get('accept-encoding', 'not set')}"
    )
    logger.info(
        "llm_proxy: %s %s -> %s%s",
        request.method,
        request.url.path,
        _safe_url_for_log(upstream_url),
        " (streaming)" if is_streaming else "",
    )

    if is_streaming:
        return await _proxy_streaming(upstream_url, request.method, fwd_headers, body)

    # 非流式路径：也需要强制 Accept-Encoding: identity，避免上游返回压缩响应
    # 导致 httpx 自动解压时出错（Error -3 while decompressing data: incorrect header check）
    non_streaming_headers = {**fwd_headers, "Accept-Encoding": "identity"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(PROXY_TIMEOUT_SECONDS)) as client:
        try:
            upstream_resp = await client.request(
                method=request.method,
                url=upstream_url,
                headers=non_streaming_headers,
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
            # Task 1 (2026-08-23): 区分证书校验失败与一般连接错误 — TLS 错误
            # 不应被映射成 ``upstream_unreachable`` 淹没信号. 同样, 当 CA bundle
            # 完全不可用时, 报告 ``ca_bundle_unavailable`` 而非沉默降级.
            safe_url = _safe_url_for_log(upstream_url)
            if _is_tls_certificate_error(exc):
                logger.warning(
                    "llm_proxy TLS certificate failed: %s — %s",
                    safe_url,
                    exc,
                )
                raise HTTPException(
                    status_code=502,
                    detail={
                        "type": "tls_certificate_failed",
                        "message": (
                            f"Upstream TLS certificate verification failed: {exc!s}. "
                            "TLS verification is enforced — proxy never disables "
                            "verify. Check the upstream certificate or the CA bundle."
                        ),
                    },
                ) from exc
            if not _is_ca_bundle_available():
                logger.warning(
                    "llm_proxy CA bundle unavailable: %s — %s",
                    safe_url,
                    exc,
                )
                raise HTTPException(
                    status_code=502,
                    detail={
                        "type": "ca_bundle_unavailable",
                        "message": (
                            "No usable CA bundle found in SSL_CERT_FILE / "
                            "REQUESTS_CA_BUNDLE / CURL_CA_BUNDLE. certifi "
                            "bootstrap did not configure a CA file. TLS verification "
                            "is enforced; please install certifi or set SSL_CERT_FILE."
                        ),
                    },
                ) from exc
            logger.warning(
                "llm_proxy connect error: %s — %s",
                safe_url,
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


async def _proxy_streaming(
    upstream_url: str,
    method: str,
    fwd_headers: Dict[str, str],
    body: bytes | None,
) -> StreamingResponse:
    """v2: SSE/chunked 流式透传。

    与非流式分支不同,这里用 ``httpx.AsyncClient.stream()`` 拿到 response 后,
    立刻起一个 async generator 逐 chunk 读 + 逐 chunk yield 给 FastAPI。
    这样上游 chunked 响应能即时回传给调用方,而不是等整条响应读完才返回。

    错误模型保持与非流式一致(超时/连接错误 → 504/502),但因为响应头已发出,
    一旦开始 yield 就不能再改 status code,所以错误处理采用"在第一个 chunk
    之前抛 HTTPException"的策略。如果上游在第一个 chunk 后断开,客户端会看到
    截断的流(由调用方决定如何处理)。

    Args:
        upstream_url: 完整的上游 URL(已包含路径 + 查询串)。
        method: HTTP 方法(POST/GET 等)。
        fwd_headers: 已过滤 hop-by-hop 的转发头。
        body: POST/PUT/PATCH 的 request body;GET/DELETE 为 None。
    """
    # 上游先建流,确认状态码 + 头信息可用,再交给 generator yield。
    # 若上游一上来就 4xx/5xx,直接抛对应 HTTPException 让 FastAPI 序列化 detail。
    #
    # Accept-Encoding: identity — httpx 默认会加 ``Accept-Encoding: gzip, deflate``,
    # 但 SSE 流式响应的 gzip 压缩会让 chunk 边界破坏(a line 可能跨 gzip block),
    # httpx aiter_bytes 自动解压时会抛 ``zlib.error: Error -3 ... incorrect
    # header check``(实测:minimaxi 在某些代理下会响应压缩)。显式 identity 让上游
    # 返回未压缩字节流,SSE 解析才能稳。
    async with httpx.AsyncClient(timeout=httpx.Timeout(PROXY_TIMEOUT_SECONDS)) as client:
        try:
            # 强制 Accept-Encoding: identity — 流式场景下上游的 gzip/deflate
            # 会让 chunk 边界破坏(httpx 的 aiter_lines 在解压时抛
            # ``zlib.error: Error -3 ... incorrect header check``)。
            # 显式 identity 让上游返回未压缩字节流,SSE 解析才稳。
            # 注意:不能仅在 client 默认头上设 identity,因为 fwd_headers 会覆盖;
            # 必须在每个请求的 headers 里显式覆盖。
            req_headers = {**fwd_headers, "Accept-Encoding": "identity"}
            req_ctx = client.stream(
                method=method,
                url=upstream_url,
                headers=req_headers,
                content=body,
            )
            upstream_resp = await req_ctx.__aenter__()
        except httpx.TimeoutException as exc:
            raise HTTPException(
                status_code=504,
                detail={
                    "type": "upstream_timeout",
                    "message": f"Upstream timeout after {PROXY_TIMEOUT_SECONDS}s: {exc!s}",
                },
            ) from exc
        except httpx.ConnectError as exc:
            # Task 1 (2026-08-23): 与非流式分支对齐 — TLS 错误必须映射到
            # ``tls_certificate_failed`` / ``ca_bundle_unavailable``, 不能被
            # 通用 ``upstream_unreachable`` 淹没.
            safe_url = _safe_url_for_log(upstream_url)
            if _is_tls_certificate_error(exc):
                logger.warning(
                    "llm_proxy (streaming) TLS certificate failed: %s — %s",
                    safe_url,
                    exc,
                )
                raise HTTPException(
                    status_code=502,
                    detail={
                        "type": "tls_certificate_failed",
                        "message": (
                            f"Upstream TLS certificate verification failed: {exc!s}. "
                            "TLS verification is enforced — proxy never disables "
                            "verify. Check the upstream certificate or the CA bundle."
                        ),
                    },
                ) from exc
            if not _is_ca_bundle_available():
                logger.warning(
                    "llm_proxy (streaming) CA bundle unavailable: %s — %s",
                    safe_url,
                    exc,
                )
                raise HTTPException(
                    status_code=502,
                    detail={
                        "type": "ca_bundle_unavailable",
                        "message": (
                            "No usable CA bundle found in SSL_CERT_FILE / "
                            "REQUESTS_CA_BUNDLE / CURL_CA_BUNDLE. certifi "
                            "bootstrap did not configure a CA file. TLS verification "
                            "is enforced; please install certifi or set SSL_CERT_FILE."
                        ),
                    },
                ) from exc
            logger.warning(
                "llm_proxy (streaming) connect error: %s — %s",
                safe_url,
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
            raise HTTPException(
                status_code=502,
                detail={
                    "type": "upstream_transport_error",
                    "message": f"Upstream transport error: {exc!s}",
                },
            ) from exc

        if not upstream_resp.is_success:
            # 上游 4xx/5xx:还没 yield 任何 chunk,可以直接抛 HTTPException 把
            # 错误体交给 FastAPI(调用方拿到的还是 JSON,不是 SSE)。
            # 透传上游状态码 + body,detail 字段保持非流式分支一致。
            text = (await upstream_resp.aread()).decode("utf-8", errors="replace")
            await req_ctx.__aexit__(None, None, None)
            raise HTTPException(
                status_code=upstream_resp.status_code,
                detail={
                    "type": "upstream_error",
                    "message": f"Upstream returned {upstream_resp.status_code}: {text[:200]}",
                },
            )

        # 上游 2xx:流式转发
        resp_headers = _filter_response_headers(upstream_resp.headers)

        async def stream_iter() -> AsyncIterator[bytes]:
            try:
                # 用 aiter_raw 而不是 aiter_bytes:后者在 Content-Encoding: gzip
                # 时会自动解压,但 SSE 流边界和 gzip block 边界通常不一致,
                # 会破坏 ``data: {...}\\n\\n`` 行的完整性,导致下游解析失败。
                # aiter_raw 透传原始字节,把解压责任交给调用方(httpx 客户端)。
                async for chunk in upstream_resp.aiter_raw():
                    yield chunk
            except BaseException as exc:
                # Headers/status have already been emitted by StreamingResponse; a
                # mid-stream failure cannot be rewritten as a second HTTP response.
                # Record a structured teardown event and pass the exception through
                # the context manager so the connection is released deterministically.
                logger.warning(
                    "llm_proxy streaming upstream interrupted: %s",
                    _safe_url_for_log(upstream_url),
                    extra={
                        "event": "llm_proxy_stream_error",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
                await req_ctx.__aexit__(type(exc), exc, exc.__traceback__)
                raise
            else:
                # Natural EOF also closes exactly once and releases the connection.
                await req_ctx.__aexit__(None, None, None)

        return StreamingResponse(
            stream_iter(),
            status_code=upstream_resp.status_code,
            headers=resp_headers,
        )
