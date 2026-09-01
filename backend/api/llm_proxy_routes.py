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

import asyncio
import atexit
import hmac
import logging
import os
import posixpath
import socket
import ssl
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from ipaddress import ip_address
from typing import Dict, FrozenSet, Optional
from urllib.parse import urlparse

import httpcore
import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from httpcore._backends.auto import AutoBackend

from backend.api.local_auth import get_local_auth_token

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
PROXY_INTERNAL_HEADERS: FrozenSet[str] = frozenset(
    {"x-llm-provider-url", "x-sage-local-authorization"}
)

PROXY_TIMEOUT_SECONDS: float = 60.0
DNS_TIMEOUT_SECONDS: float = 5.0
DNS_MAX_CONCURRENCY: int = 16
_DNS_EXECUTOR = ThreadPoolExecutor(
    max_workers=DNS_MAX_CONCURRENCY,
    thread_name_prefix="sage-dns",
)
_DNS_SEMAPHORE: Optional[asyncio.Semaphore] = None


def _dns_executor() -> ThreadPoolExecutor:
    """Return the active pool, recreating it after a lifespan restart."""
    global _DNS_EXECUTOR
    if _DNS_EXECUTOR is None:
        _DNS_EXECUTOR = ThreadPoolExecutor(
            max_workers=DNS_MAX_CONCURRENCY,
            thread_name_prefix="sage-dns",
        )
    return _DNS_EXECUTOR


def shutdown_dns_executor() -> None:
    """Release the DNS pool without waiting for stuck resolver calls.

    ``getaddrinfo`` is a blocking OS call and cancelling its asyncio Future cannot
    interrupt the worker thread.  ``wait=False`` therefore keeps application
    shutdown from blocking; the bounded pool still limits the number of such
    lingering calls.  This function is idempotent and is also registered for
    interpreter shutdown as a safety net.
    """
    global _DNS_EXECUTOR
    executor, _DNS_EXECUTOR = _DNS_EXECUTOR, None
    if executor is not None:
        try:
            # ``cancel_futures`` was added in Python 3.9; retain Win7/Python
            # 3.8 compatibility while still never waiting on stuck getaddrinfo.
            executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:  # pragma: no cover - Python 3.8 fallback
            executor.shutdown(wait=False)


atexit.register(shutdown_dns_executor)
# httpx==0.26.0 resolves to httpcore==1.0.9 in the supported environments.
_SUPPORTED_HTTPCORE_VERSION = "1.0.9"

# Local/private providers require an explicit host allowlist.  Public DNS names
# are still resolved before connecting so a DNS-rebinding answer cannot turn an
# otherwise public-looking name into a private destination.
LOCAL_PROVIDER_ALLOWLIST_ENV = "SAGE_LLM_PROXY_ALLOWED_HOSTS"
_DANGEROUS_NETWORK_ERROR = "The upstream target is not allowed."


def _configured_allowed_hosts() -> frozenset[str]:
    return frozenset(
        item.strip().lower().rstrip(".")
        for item in os.environ.get(LOCAL_PROVIDER_ALLOWLIST_ENV, "").split(",")
        if item.strip()
    )


def _is_dangerous_address(host: str) -> bool:
    try:
        address = ip_address(host)
    except ValueError:
        return False
    return (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
        or host == "169.254.169.254"
    )


def _resolve_addresses(host: str, port: int):
    """Resolve a host in a worker thread so async routes never block on DNS."""
    return socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)


async def _resolve_and_validate_upstream_host(parsed) -> str:
    """Resolve once off the event loop and return the pinned address."""
    global _DNS_SEMAPHORE
    if _DNS_SEMAPHORE is None:
        _DNS_SEMAPHORE = asyncio.Semaphore(DNS_MAX_CONCURRENCY)
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise HTTPException(
            status_code=400,
            detail={
                "type": "invalid_provider_url",
                "message": "X-LLM-Provider-Url must include a host",
            },
        )
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    loop = asyncio.get_running_loop()
    semaphore = _DNS_SEMAPHORE
    # Reject immediately when all bounded resolver workers are occupied.  A
    # timed-out getaddrinfo cannot be interrupted; never queue unbounded work.
    if semaphore.locked():
        raise socket.gaierror("DNS resolution capacity exhausted")
    await semaphore.acquire()
    try:
        executor = _dns_executor()
        try:
            infos = await asyncio.wait_for(
                loop.run_in_executor(executor, _resolve_addresses, host, port),
                timeout=DNS_TIMEOUT_SECONDS,
            )
        except (asyncio.TimeoutError, TimeoutError, socket.gaierror, OSError):  # noqa: UP041
            raise socket.gaierror("upstream DNS resolution failed") from None
    finally:
        semaphore.release()
    addresses = {info[4][0] for info in infos}
    if not addresses:
        raise socket.gaierror("no addresses found")
    allowed = _configured_allowed_hosts()
    if host not in allowed and (
        _is_dangerous_address(host)
        or any(_is_dangerous_address(address) for address in addresses)
    ):
        raise HTTPException(
            status_code=403,
            detail={
                "type": "blocked_provider_target",
                "message": _DANGEROUS_NETWORK_ERROR,
            },
        )
    return sorted(addresses)[0]


# httpx 0.26.0 is paired with httpcore 1.x in requirements.txt.  The public
# httpx transport constructor does not expose httpcore's network_backend, so
# this small adapter intentionally uses the pinned httpcore pool attribute.
# Keep this isolated and guarded: an httpcore upgrade must update this code and
# its tests rather than silently reintroducing hostname resolution.
class _FixedIPNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, address: str) -> None:
        self._address = address
        self._delegate = AutoBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        return await self._delegate.connect_tcp(
            self._address,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        return await self._delegate.connect_unix_socket(
            path, timeout=timeout, socket_options=socket_options
        )

    async def sleep(self, seconds):
        await self._delegate.sleep(seconds)


def _client_for_resolved_address(address: str) -> httpx.AsyncClient:
    # Build through AsyncClient so respx and other transport instrumentation keep
    # working.  Mutate only the pinned httpcore pool's backend afterwards.
    if httpcore.__version__ != _SUPPORTED_HTTPCORE_VERSION:
        raise RuntimeError(
            "Unsupported httpcore version: fixed-IP transport unavailable"
        )
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(PROXY_TIMEOUT_SECONDS),
        trust_env=False,
    )
    transport = getattr(client, "_transport", None)
    pool = getattr(transport, "_pool", None)
    if pool is None or not hasattr(pool, "_network_backend"):
        raise RuntimeError("Unsupported httpcore version: fixed-IP transport unavailable")
    pool._network_backend = _FixedIPNetworkBackend(address)
    return client

# Bound every byte buffer owned by the proxy.  These limits are deliberately
# local to this route; they do not change provider protocol semantics.
MAX_REQUEST_BODY_BYTES: int = 10 * 1024 * 1024
MAX_RESPONSE_BODY_BYTES: int = 10 * 1024 * 1024

# Upstream failures may contain URLs, credentials, tokens, or response bodies.
# Keep the public diagnostics deliberately stable and free of provider data.
_SAFE_UPSTREAM_MESSAGES = {
    "upstream_timeout": "The upstream request timed out.",
    "upstream_unreachable": "The upstream service could not be reached.",
    "upstream_transport_error": "The upstream request failed during transport.",
    "tls_certificate_failed": "The upstream TLS certificate could not be verified.",
    "request_body_too_large": "The request body exceeds the maximum allowed size.",
    "response_body_too_large": "The upstream response exceeds the maximum allowed size.",
}


async def _read_request_body(request: Request) -> bytes:
    """Read a request body with a hard cap, never buffering an unbounded body."""
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_REQUEST_BODY_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail={
                        "type": "request_body_too_large",
                        "message": _SAFE_UPSTREAM_MESSAGES["request_body_too_large"],
                    },
                )
        except ValueError:
            pass

    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_REQUEST_BODY_BYTES:
            raise HTTPException(
                status_code=413,
                detail={
                    "type": "request_body_too_large",
                    "message": _SAFE_UPSTREAM_MESSAGES["request_body_too_large"],
                },
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def _read_response_body_limited(response: httpx.Response) -> bytes:
    """Read an upstream response only up to the configured memory limit."""
    content_length = response.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_RESPONSE_BODY_BYTES:
                raise ValueError("response exceeds configured limit")
        except ValueError as exc:
            if str(exc) == "response exceeds configured limit":
                raise

    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_raw():
        size += len(chunk)
        if size > MAX_RESPONSE_BODY_BYTES:
            raise ValueError("response exceeds configured limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _safe_upstream_error_message(status_code: int) -> str:
    """Return a status-only upstream error without reflecting response data."""
    return f"Upstream returned HTTP {status_code}."


# CA bundle 不可用时上报 — 用于结构化 detail.type; 不泄露具体路径
_CA_BUNDLE_ENV_VARS: FrozenSet[str] = frozenset(
    {"SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"}
)


def _is_ca_bundle_available() -> bool:  # noqa: PLR0911 — 多分支表驱动早返,提取会破坏可读性
    """检测 CA bundle 是否可用.

    优先检查 ``SSL_CERT_FILE`` / ``REQUESTS_CA_BUNDLE`` / ``CURL_CA_BUNDLE``
    三个环境变量 (由 ``main.configure_ssl_ca_bundle`` 注入 certifi.where 路径).
    兜底探测 ``ssl.get_default_verify_paths().cafile / capath``: 系统级 bundle
    (OpenSSL ``/etc/ssl/certs`` / Windows cert store 派生文件) 也是合法 CA 源,
    在公司代理只配系统 bundle 不设 env vars 的环境里必须认.

    任一来源存在且路径可读 → True; 全部未设 / 路径缺失 / 不可读 → False.

    Semantics: 一旦用户**显式**设置了任一 env var(非空字符串),就视为用户选择,
    不再 fallback 到 ``ssl.get_default_verify_paths()``. 这避免 certifi 注入后
    系统默认 cafile 覆盖用户故意设置的"空文件 / 损坏 bundle"(典型场景:测试
    隔离环境故意 mock 一个空 cert 来强制走非 TLS 路径;以及用户手动
    ``SSL_CERT_FILE=/tmp/empty.pem`` 表示"我已知风险,继续").
    """
    from pathlib import Path

    any_env_set = False
    for variable in _CA_BUNDLE_ENV_VARS:
        path_str = os.environ.get(variable)
        if not path_str:
            continue
        any_env_set = True
        path = Path(path_str)
        try:
            if path.is_file() and path.stat().st_size > 0:
                return True
            if path.is_dir() and any(path.iterdir()):
                # capath 是目录, 含已哈希链接的 cert 文件; 任意文件存在即视为可用.
                return True
        except OSError:
            continue

    if any_env_set:
        # 用户显式设置了 env var 但都不可用 → 不再 fallback,直接 False.
        return False

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


def _is_local_capability_authorization(value: str, local_token: str) -> bool:
    """Return whether a header is exactly the local Bearer capability."""
    scheme, separator, supplied = value.partition(" ")
    return bool(
        separator
        and scheme.lower() == "bearer"
        and supplied
        and hmac.compare_digest(supplied, local_token)
    )


def _filter_request_headers(
    request: Request, local_token: Optional[str] = None
) -> Dict[str, str]:
    """Copy request headers, excluding proxy internals and the local capability."""
    capability = local_token if local_token is not None else get_local_auth_token()
    forwarded: Dict[str, str] = {}
    for key, value in request.headers.items():
        lower_key = key.lower()
        if lower_key in HOP_BY_HOP_HEADERS or lower_key in PROXY_INTERNAL_HEADERS:
            continue
        if lower_key == "authorization" and _is_local_capability_authorization(
            value, capability
        ):
            continue
        forwarded[key] = value
    return forwarded


def _filter_response_headers(headers: httpx.Headers) -> Dict[str, str]:
    """复制上游响应头到 dict,过滤 hop-by-hop。"""
    return {k: v for k, v in headers.items() if k.lower() not in HOP_BY_HOP_HEADERS}


def _safe_url_for_log(provider_url: str, max_len: int = 80) -> str:
    """生成 log-safe URL 表示:剥 userinfo、限长。

    ``http://user:secret@host:11434`` → ``http://host:11434``
    """
    try:
        p = urlparse(provider_url)
        host = p.hostname or ""
        try:
            port = f":{p.port}" if p.port else ""
        except ValueError:
            port = ""
        safe = f"{p.scheme}://{host}{port}"
    except (TypeError, ValueError):
        return "<unparseable>"
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
        # Accessing ``port`` validates malformed port values without exposing them.
        _ = parsed.port
    except ValueError as exc:
        # ``str(exc)`` can echo a credential-bearing URL (for example a bad port).
        raise HTTPException(
            status_code=400,
            detail={
                "type": "invalid_provider_url",
                "message": "X-LLM-Provider-Url is not a valid URL",
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
    try:
        resolved_address = await _resolve_and_validate_upstream_host(parsed)
    except socket.gaierror:
        # No address means no safe destination; let the request fail closed.
        raise HTTPException(
            status_code=502,
            detail={
                "type": "upstream_unreachable",
                "message": _SAFE_UPSTREAM_MESSAGES["upstream_unreachable"],
            },
        ) from None

    # 2. 重建上游 URL — 委托给 ``build_upstream_url``,自动去重 ``/v1`` 段
    #    (用户 baseURL 已含 ``/v1`` 时,避免 ``/v1/v1/models``)。
    upstream_url = build_upstream_url(provider_url, path, request.url.query)

    # 4. 透传头部与 body
    fwd_headers = _filter_request_headers(request, get_local_auth_token())
    body: bytes | None = (
        await _read_request_body(request)
        if request.method in {"POST", "PUT", "PATCH"}
        else None
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
        "llm_proxy: %s %s -> %s%s",
        request.method,
        request.url.path,
        _safe_url_for_log(upstream_url),
        " (streaming)" if is_streaming else "",
    )

    if is_streaming:
        return await _proxy_streaming(
            upstream_url, request.method, fwd_headers, body, resolved_address
        )

    # 非流式路径：也需要强制 Accept-Encoding: identity，避免上游返回压缩响应
    # 导致 httpx 自动解压时出错（Error -3 while decompressing data: incorrect header check）
    non_streaming_headers = {**fwd_headers, "Accept-Encoding": "identity"}
    try:
        async with _client_for_resolved_address(resolved_address) as client, client.stream(
            method=request.method,
            url=upstream_url,
            headers=non_streaming_headers,
            content=body,
        ) as upstream_resp:
            if upstream_resp.is_success:
                response_body = await _read_response_body_limited(upstream_resp)
            else:
                response_body = b""
    except ValueError as exc:
        if str(exc) == "response exceeds configured limit":
            raise HTTPException(
                status_code=502,
                detail={
                    "type": "response_body_too_large",
                    "message": _SAFE_UPSTREAM_MESSAGES["response_body_too_large"],
                },
            ) from exc
        raise
    except httpx.TimeoutException as exc:
        logger.warning("llm_proxy timeout: %s", _safe_url_for_log(upstream_url))
        raise HTTPException(
            status_code=504,
            detail={
                "type": "upstream_timeout",
                "message": _SAFE_UPSTREAM_MESSAGES["upstream_timeout"],
            },
        ) from exc
    except httpx.ConnectError as exc:
        safe_url = _safe_url_for_log(upstream_url)
        if _is_tls_certificate_error(exc):
            logger.warning("llm_proxy TLS certificate failed: %s", safe_url)
            raise HTTPException(
                status_code=502,
                detail={
                    "type": "tls_certificate_failed",
                    "message": _SAFE_UPSTREAM_MESSAGES["tls_certificate_failed"],
                },
            ) from exc
        if not _is_ca_bundle_available():
            logger.warning("llm_proxy CA bundle unavailable: %s", safe_url)
            raise HTTPException(
                status_code=502,
                detail={
                    "type": "ca_bundle_unavailable",
                    "message": "No usable CA bundle found; TLS verification is enforced.",
                },
            ) from exc
        logger.warning("llm_proxy connect error: %s", safe_url)
        raise HTTPException(
            status_code=502,
            detail={
                "type": "upstream_unreachable",
                "message": _SAFE_UPSTREAM_MESSAGES["upstream_unreachable"],
            },
        ) from exc
    except httpx.TransportError as exc:
        logger.warning("llm_proxy transport error: %s", _safe_url_for_log(upstream_url))
        raise HTTPException(
            status_code=502,
            detail={
                "type": "upstream_transport_error",
                "message": _SAFE_UPSTREAM_MESSAGES["upstream_transport_error"],
            },
        ) from exc

    if not upstream_resp.is_success:
        raise HTTPException(
            status_code=upstream_resp.status_code,
            detail={
                "type": "upstream_error",
                "message": _safe_upstream_error_message(upstream_resp.status_code),
            },
        )

    # 6. 透传响应(过滤 hop-by-hop 响应头)
    resp_headers = _filter_response_headers(upstream_resp.headers)
    return Response(
        content=response_body,
        status_code=upstream_resp.status_code,
        headers=resp_headers,
    )


async def _proxy_streaming(
    upstream_url: str,
    method: str,
    fwd_headers: Dict[str, str],
    body: bytes | None,
    resolved_address: str | None = None,
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
    client = (
        _client_for_resolved_address(resolved_address)
        if resolved_address is not None
        else httpx.AsyncClient(
            timeout=httpx.Timeout(PROXY_TIMEOUT_SECONDS),
            trust_env=False,
        )
    )
    client_closed = False
    await client.__aenter__()
    try:
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
                    "message": _SAFE_UPSTREAM_MESSAGES["upstream_timeout"],
                },
            ) from exc
        except httpx.ConnectError as exc:
            # Task 1 (2026-08-23): 与非流式分支对齐 — TLS 错误必须映射到
            # ``tls_certificate_failed`` / ``ca_bundle_unavailable``, 不能被
            # 通用 ``upstream_unreachable`` 淹没.
            safe_url = _safe_url_for_log(upstream_url)
            if _is_tls_certificate_error(exc):
                logger.warning(
                    "llm_proxy (streaming) TLS certificate failed: %s",
                    safe_url,
                )
                raise HTTPException(
                    status_code=502,
                    detail={
                        "type": "tls_certificate_failed",
                        "message": _SAFE_UPSTREAM_MESSAGES["tls_certificate_failed"],
                    },
                ) from exc
            if not _is_ca_bundle_available():
                logger.warning(
                    "llm_proxy (streaming) CA bundle unavailable: %s",
                    safe_url,
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
                "llm_proxy (streaming) connect error: %s",
                safe_url,
            )
            raise HTTPException(
                status_code=502,
                detail={
                    "type": "upstream_unreachable",
                    "message": _SAFE_UPSTREAM_MESSAGES["upstream_unreachable"],
                },
            ) from exc
        except httpx.TransportError as exc:
            raise HTTPException(
                status_code=502,
                detail={
                    "type": "upstream_transport_error",
                    "message": _SAFE_UPSTREAM_MESSAGES["upstream_transport_error"],
                },
            ) from exc

        if not upstream_resp.is_success:
            # 上游 4xx/5xx:还没 yield 任何 chunk,可以直接抛 HTTPException 把
            # 错误体交给 FastAPI(调用方拿到的还是 JSON,不是 SSE)。
            try:
                await _read_response_body_limited(upstream_resp)
            except ValueError as exc:
                raise HTTPException(
                    status_code=502,
                    detail={
                        "type": "response_body_too_large",
                        "message": _SAFE_UPSTREAM_MESSAGES["response_body_too_large"],
                    },
                ) from exc
            finally:
                await req_ctx.__aexit__(None, None, None)
                await client.__aexit__(None, None, None)
                client_closed = True
            raise HTTPException(
                status_code=upstream_resp.status_code,
                detail={
                    "type": "upstream_error",
                    "message": _safe_upstream_error_message(upstream_resp.status_code),
                },
            )

        # 上游 2xx:流式转发
        resp_headers = _filter_response_headers(upstream_resp.headers)

        async def stream_iter() -> AsyncIterator[bytes]:
            total_bytes = 0
            request_context_closed = False
            try:
                # 用 aiter_raw 透传原始字节,把解压责任交给调用方。
                async for chunk in upstream_resp.aiter_raw():
                    remaining = MAX_RESPONSE_BODY_BYTES - total_bytes
                    if remaining <= 0:
                        logger.warning(
                            "llm_proxy streaming response exceeded limit: %s",
                            _safe_url_for_log(upstream_url),
                        )
                        break
                    if len(chunk) > remaining:
                        yield chunk[:remaining]
                        total_bytes += remaining
                        logger.warning(
                            "llm_proxy streaming response exceeded limit: %s",
                            _safe_url_for_log(upstream_url),
                        )
                        await req_ctx.__aexit__(None, None, None)
                        request_context_closed = True
                        break
                    yield chunk
                    total_bytes += len(chunk)
                    if total_bytes >= MAX_RESPONSE_BODY_BYTES:
                        logger.warning(
                            "llm_proxy streaming response reached limit: %s",
                            _safe_url_for_log(upstream_url),
                        )
                        await req_ctx.__aexit__(None, None, None)
                        request_context_closed = True
                        break
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
                    },
                )
                await req_ctx.__aexit__(type(exc), exc, exc.__traceback__)
                request_context_closed = True
                raise
            finally:
                if not request_context_closed:
                    await req_ctx.__aexit__(None, None, None)
                await client.__aexit__(None, None, None)

        return StreamingResponse(
            stream_iter(),
            status_code=upstream_resp.status_code,
            headers=resp_headers,
        )
    except BaseException:
        if not client_closed:
            await client.__aexit__(None, None, None)
        raise
