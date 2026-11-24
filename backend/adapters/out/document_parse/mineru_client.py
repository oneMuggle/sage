"""MinerU v1 REST 异步客户端：create → upload → poll → download。"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, Optional, Sequence, Tuple
from urllib.parse import quote, urljoin, urlparse

import httpx

from .mineru_errors import (
    MineruAuthError,
    MineruConfigError,
    MineruRemoteError,
    MineruTimeoutError,
    MineruUnavailableError,
)
from .mineru_models import (
    TERMINAL_STATUSES,
    MineruOutput,
    TaskSnapshot,
    build_create_body,
    parse_task_snapshot,
    unpack_result_payload,
)

_RETRYABLE_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 3
_BASE_DELAY = 0.25
_MAX_DELAY = 2.0
_MAX_REDIRECTS = 6
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


def _origin(url: str) -> Tuple[str, str, int]:
    parsed = urlparse(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), port


class MineruClient:
    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        timeout_seconds: float = 300.0,
        poll_interval: float = 1.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self._api_key = (api_key or "").strip()
        self._timeout = timeout_seconds
        self._poll_interval = poll_interval
        self._transport = transport
        self._sleep = sleep

    # ── 请求构造 ────────────────────────────────────────────────
    def _auth_headers(self) -> Dict[str, str]:
        return {"Authorization": "Bearer " + self._api_key} if self._api_key else {}

    def _headers_for(self, url: str) -> Dict[str, str]:
        """跨源绝不转发 Authorization（上传 URL 可能是别的主机）。"""
        if _origin(url) != _origin(self.base_url):
            return {}
        return self._auth_headers()

    def _url(self, path: str) -> str:
        return urljoin(self.base_url + "/", path.lstrip("/"))

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout, connect=30.0),
            trust_env=False,
            follow_redirects=False,
            transport=self._transport,
        )

    # ── 错误映射 ────────────────────────────────────────────────
    @staticmethod
    def _raise_for_response(response: httpx.Response) -> Dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code < 400:
            if not isinstance(payload, dict):
                raise MineruRemoteError("invalid_response", "response must be a JSON object")
            return payload
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            code = str(error.get("code") or "unknown")
            message = str(error.get("message") or code)
            raw_param = error.get("param")
            param = str(raw_param) if raw_param is not None else None
        else:
            code = "http_error"
            message = "HTTP " + str(response.status_code)
            param = None
        if response.status_code in (401, 403) or code == "invalid_api_key":
            raise MineruAuthError(
                code, message, param=param, status_code=response.status_code
            )
        raise MineruRemoteError(
            code, message, param=param, status_code=response.status_code
        )

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        content: Optional[bytes] = None,
        headers: Optional[Dict[str, str]] = None,
        retry: bool = False,
    ) -> Dict[str, Any]:
        attempts = _MAX_ATTEMPTS if retry else 1
        for attempt in range(1, attempts + 1):
            merged = dict(headers if headers is not None else self._headers_for(url))
            try:
                response = await client.request(
                    method, url, json=json_body, content=content, headers=merged
                )
            except httpx.HTTPError as exc:
                if attempt == attempts:
                    raise MineruUnavailableError("unavailable", str(exc)) from exc
                await self._sleep(self._delay(attempt))
                continue
            if response.status_code in _RETRYABLE_STATUSES and attempt < attempts:
                await self._sleep(self._delay(attempt))
                continue
            return self._raise_for_response(response)
        raise MineruUnavailableError("unavailable", "retry budget exhausted")

    @staticmethod
    def _delay(attempt: int) -> float:
        return min(_MAX_DELAY, _BASE_DELAY * (2 ** (attempt - 1)))

    # ── 四步协议 ────────────────────────────────────────────────
    async def _create(
        self, client: httpx.AsyncClient, body: Dict[str, Any]
    ) -> TaskSnapshot:
        payload = await self._request(
            client, "POST", self._url("/v1/tasks"), json_body=body, retry=False
        )
        return parse_task_snapshot(payload)

    async def _query(self, client: httpx.AsyncClient, task_id: str) -> TaskSnapshot:
        payload = await self._request(
            client, "GET", self._url("/v1/tasks/" + quote(task_id, safe="")), retry=True
        )
        return parse_task_snapshot(payload)

    async def _upload(
        self,
        client: httpx.AsyncClient,
        snapshot: TaskSnapshot,
        content: bytes,
    ) -> TaskSnapshot:
        target = snapshot.files[0].upload
        if snapshot.files[0].status != "waiting-file" or target is None:
            return snapshot
        url = urljoin(self.base_url + "/", target.url.lstrip("/"))
        headers = dict(target.headers)
        headers.update(self._headers_for(url))
        last_error: Optional[BaseException] = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = await client.request(
                    "PUT", url, content=content, headers=headers
                )
                if response.status_code >= 400:
                    self._raise_for_response(response)
                return await self._query(client, snapshot.task_id)
            except MineruAuthError:
                raise
            except MineruRemoteError as exc:
                if exc.status_code not in _RETRYABLE_STATUSES:
                    raise
                last_error = exc
            except MineruUnavailableError as exc:
                last_error = exc
            if attempt == _MAX_ATTEMPTS:
                break
            await self._sleep(self._delay(attempt))
            snapshot = await self._query(client, snapshot.task_id)
            target = snapshot.files[0].upload
            if snapshot.files[0].status != "waiting-file" or target is None:
                return snapshot
            url = urljoin(self.base_url + "/", target.url.lstrip("/"))
            headers = dict(target.headers)
            headers.update(self._headers_for(url))
        raise MineruUnavailableError(
            "upload_failed", str(last_error or "upload failed")
        )

    async def _download(self, client: httpx.AsyncClient, result_url: str) -> bytes:
        url = urljoin(self.base_url + "/", result_url.lstrip("/"))
        for _ in range(_MAX_REDIRECTS):
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                try:
                    response = await client.get(url, headers=self._headers_for(url))
                except httpx.HTTPError as exc:
                    if attempt == _MAX_ATTEMPTS:
                        raise MineruUnavailableError("unavailable", str(exc)) from exc
                    await self._sleep(self._delay(attempt))
                    continue
                if (
                    response.status_code in _RETRYABLE_STATUSES
                    and attempt < _MAX_ATTEMPTS
                ):
                    await self._sleep(self._delay(attempt))
                    continue
                break
            if response.status_code in _REDIRECT_STATUSES:
                location = response.headers.get("location")
                if not location:
                    raise MineruRemoteError(
                        "invalid_response", "download redirect missing Location"
                    )
                url = urljoin(url, location)
                continue
            if response.status_code >= 400:
                self._raise_for_response(response)
            return response.content
        raise MineruRemoteError("invalid_response", "too many download redirects")

    async def cancel(self, task_id: str) -> None:
        try:
            async with self._client() as client:
                await client.post(
                    self._url("/v1/tasks/" + quote(task_id, safe="") + "/cancel"),
                    headers=self._auth_headers(),
                    timeout=5.0,
                )
        except httpx.HTTPError:
            return

    async def parse_bytes(
        self,
        content: bytes,
        filename: str,
        *,
        page_range: Optional[str] = None,
        output_formats: Sequence[str] = ("default",),
        tier: Optional[str] = None,
        ocr_mode: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> MineruOutput:
        if not self.base_url:
            raise MineruConfigError("not_configured", "MinerU baseUrl is empty")
        timeout = self._timeout if timeout_seconds is None else timeout_seconds
        body = build_create_body(
            filename=filename,
            content=content,
            page_range=page_range,
            output_formats=output_formats,
            tier=tier,
            ocr_mode=ocr_mode,
        )
        async with self._client() as client:
            snapshot = await self._create(client, body)
            snapshot = await self._upload(client, snapshot, content)
            deadline = time.monotonic() + timeout
            while snapshot.status not in TERMINAL_STATUSES:
                if time.monotonic() >= deadline:
                    await self.cancel(snapshot.task_id)
                    raise MineruTimeoutError(
                        "timeout", "task " + snapshot.task_id + " did not finish"
                    )
                await self._sleep(self._poll_interval)
                snapshot = await self._query(client, snapshot.task_id)
                snapshot = await self._upload(client, snapshot, content)
            if snapshot.status in ("failed", "canceled"):
                raise MineruRemoteError(
                    snapshot.error_code or snapshot.status,
                    snapshot.error_message or ("task " + snapshot.status),
                )
            if snapshot.files[0].status != "completed":
                raise MineruRemoteError("parse_failed", "task file did not complete")
            result_url = snapshot.files[0].result_url
            if not result_url:
                raise MineruRemoteError(
                    "invalid_response", "completed task missing result_url"
                )
            payload = await self._download(client, result_url)
        return unpack_result_payload(payload, output_formats, snapshot.status)

    # ── 健康探测 ────────────────────────────────────────────────
    async def probe(self) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "reachable": False,
            "serverAuthMode": "unknown",
            "serverTiers": None,
            "serverVersion": None,
            "reason": "",
            "accessLevel": None,
        }
        if not self.base_url:
            base["reason"] = "not_configured"
            return base
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(8.0, connect=5.0),
                trust_env=False,
                transport=self._transport,
            ) as client:
                usage = await client.get(
                    self._url("/v1/usage"), headers=self._auth_headers()
                )
                if usage.status_code == 200:
                    data = usage.json() if usage.content else {}
                    base.update(
                        reachable=True,
                        serverAuthMode="bearer" if self._api_key else "anonymous",
                        accessLevel=data.get("access_level")
                        if isinstance(data, dict)
                        else None,
                    )
                    return base
                if usage.status_code in (401, 403):
                    base.update(
                        reachable=True,
                        serverAuthMode="required",
                        reason="api_key_required_or_invalid",
                    )
                    return base
                for path, key in (
                    ("/v1/tiers", "serverTiers"),
                    ("/v1/health", "serverVersion"),
                ):
                    response = await client.get(self._url(path))
                    if response.status_code != 200:
                        continue
                    try:
                        data = response.json()
                    except ValueError:
                        continue
                    if not isinstance(data, dict):
                        continue
                    base["reachable"] = True
                    if key == "serverTiers":
                        tiers = data.get("tiers") or data.get("available_tiers")
                        if isinstance(tiers, list):
                            base["serverTiers"] = [str(t) for t in tiers]
                    else:
                        version = data.get("version")
                        if isinstance(version, str):
                            base["serverVersion"] = version
                if base["reachable"]:
                    return base
                base["reason"] = "unreachable"
                return base
        except (httpx.HTTPError, ValueError):
            base["reason"] = "unreachable"
            return base
