"""Shared security helpers for outbound HTTP requests.

Provides DNS resolution, private address detection, and bounded response reading
to prevent SSRF, DNS rebinding, and memory exhaustion attacks.
"""

from __future__ import annotations

import asyncio
import socket
from ipaddress import ip_address

import httpcore
import httpx

# DNS resolution limits (shared across all outbound requests)
DNS_MAX_CONCURRENCY = 8
DNS_TIMEOUT_SECONDS = 5.0

# Response body limit (10 MiB)
MAX_RESPONSE_BODY_BYTES: int = 10 * 1024 * 1024

# Error message for blocked dangerous targets (deliberately vague)
_DANGEROUS_NETWORK_ERROR = "Upstream target is not reachable from this network."

_dns_semaphore: asyncio.Semaphore | None = None
_dns_executor_instance = None


def _get_dns_executor():
    """Lazy-init the shared DNS thread pool executor."""
    global _dns_executor_instance
    if _dns_executor_instance is None:
        from concurrent.futures import ThreadPoolExecutor

        _dns_executor_instance = ThreadPoolExecutor(
            max_workers=DNS_MAX_CONCURRENCY,
            thread_name_prefix="sage-dns",
        )
    return _dns_executor_instance


def _configured_allowed_hosts() -> frozenset[str]:
    """Hosts explicitly allowed (e.g., localhost for testing). Empty by default."""
    import os

    raw = os.environ.get("SAGE_ALLOWED_UPSTREAM_HOSTS", "")
    if not raw:
        return frozenset()
    return frozenset(h.strip().lower() for h in raw.split(",") if h.strip())


def _is_dangerous_address(host: str) -> bool:
    """Check if an IP address is private, loopback, link-local, or reserved."""
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
        or host == "169.254.169.254"  # AWS metadata endpoint
    )


def _resolve_addresses(host: str, port: int):
    """Resolve a host in a worker thread so async routes never block on DNS."""
    return socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)


async def resolve_and_validate_upstream_host(parsed) -> str:
    """Resolve DNS once off the event loop and return the pinned address.

    Raises ValueError if the host is dangerous (private/loopback/link-local)
    and not in the allowed list.
    """
    global _dns_semaphore
    if _dns_semaphore is None:
        _dns_semaphore = asyncio.Semaphore(DNS_MAX_CONCURRENCY)

    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise ValueError("URL must include a host")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    loop = asyncio.get_running_loop()
    semaphore = _dns_semaphore

    # Reject immediately when all bounded resolver workers are occupied
    if semaphore.locked():
        raise ValueError("DNS resolution capacity exhausted")

    await semaphore.acquire()
    try:
        executor = _get_dns_executor()
        try:
            infos = await asyncio.wait_for(
                loop.run_in_executor(executor, _resolve_addresses, host, port),
                timeout=DNS_TIMEOUT_SECONDS,
            )
        except (asyncio.TimeoutError, TimeoutError, socket.gaierror, OSError):
            raise ValueError("DNS resolution failed") from None
    finally:
        semaphore.release()

    addresses = {info[4][0] for info in infos}
    if not addresses:
        raise ValueError("no addresses found")

    allowed = _configured_allowed_hosts()
    if host not in allowed and (
        _is_dangerous_address(host)
        or any(_is_dangerous_address(address) for address in addresses)
    ):
        raise ValueError(_DANGEROUS_NETWORK_ERROR)

    return sorted(addresses)[0]


_SUPPORTED_HTTPCORE_VERSION = "1.0.0"


class _FixedIPNetworkBackend(httpcore.AsyncNetworkBackend):
    """httpcore network backend that connects to a pinned IP address.

    Prevents DNS rebinding by ignoring the hostname during TCP connect.
    """

    def __init__(self, address: str) -> None:
        self._address = address
        # Use the default auto backend
        from httpcore._backends.auto import AutoBackend

        self._delegate = AutoBackend()

    async def connect_tcp(
        self, host, port, timeout=None, local_address=None, socket_options=None
    ):
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


def client_for_resolved_address(
    address: str, timeout_seconds: float = 30.0
) -> httpx.AsyncClient:
    """Create an httpx client pinned to a specific IP address.

    The client will always connect to ``address`` regardless of the hostname
    in the URL, preventing DNS rebinding attacks.
    """
    # Check httpcore version compatibility
    if not httpcore.__version__.startswith(_SUPPORTED_HTTPCORE_VERSION):
        raise RuntimeError(
            f"Unsupported httpcore version {httpcore.__version__}: "
            "fixed-IP transport unavailable"
        )

    client = httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_seconds),
        trust_env=False,
    )
    transport = getattr(client, "_transport", None)
    pool = getattr(transport, "_pool", None)
    if pool is None or not hasattr(pool, "_network_backend"):
        raise RuntimeError("Unsupported httpcore version: fixed-IP transport unavailable")
    pool._network_backend = _FixedIPNetworkBackend(address)
    return client


async def read_response_body_limited(
    response: httpx.Response, max_bytes: int = MAX_RESPONSE_BODY_BYTES
) -> bytes:
    """Read an upstream response with a hard cap to prevent memory exhaustion.

    Raises ValueError if the response exceeds the limit.
    """
    content_length = response.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise ValueError("response exceeds configured limit")
        except ValueError as exc:
            if "response exceeds configured limit" in str(exc):
                raise

    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > max_bytes:
            raise ValueError("response exceeds configured limit")
        chunks.append(chunk)
    return b"".join(chunks)
