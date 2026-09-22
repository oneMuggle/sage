"""10minutemail.one temporary-mail provider (catch-all, registration-free).

Logic re-implemented from the field-tested reference
(reference/ArenCard/arena_core.py:235-323) per the porting discipline in
docs/technical/50-arena-source-license-audit.md: borrow the protocol knowledge
and measured constants, write the code from scratch.

Measured rules that MUST be preserved:

* Mail traffic always goes **direct** — the provider blacklists some
  datacenter/proxy IPs (about 4 of 10 proxied attempts had TLS dropped) and it
  does not need a proxy: only the arena side requires a consistent exit IP.
* The site JWT is embedded in the HTML of ``https://10minutemail.one/zh``
  (~23 h validity). An API ``401`` means the JWT expired → refresh once, retry.
* Addresses are never registered: any ``{10-char local}@{catch-all domain}``
  receives mail, so ``create_mailbox`` only mints a local name.
* 100 concurrent inbox polls showed no rate limiting; the registration
  bottleneck is mail delivery, hence the recommended concurrency of 3~5.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import string
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

import httpx

from .base import (
    DEFAULT_CODE_PATTERN,
    DEFAULT_SUBJECT_PATTERN,
    Mailbox,
    TemporaryMailProvider,
)

logger = logging.getLogger(__name__)


class TenMinMailError(RuntimeError):
    """Temporary-mail provider failure (JWT unavailable, API error, ...)."""


#: Site JWT pattern — HS256 JWT embedded in the page HTML.
JWT_RE = re.compile(r"eyJhbGciOiJIUzI1NiJ9\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")

#: Verification-link pattern（默认宽匹配任意 http(s) 链接，调用方可收紧）
DEFAULT_LINK_PATTERN = r"https?://[^\s\"'<>]+"


class TenMinMailProvider(TemporaryMailProvider):
    """Catch-all disposable mailboxes from 10minutemail.one."""

    name = "tenminmail"

    SITE = "https://10minutemail.one/zh"
    API = "https://web.10minutemail.one/api/v1"
    ORIGIN = "https://10minutemail.one"

    #: Catch-all domains rotated per mailbox (reference measured list).
    DOMAINS: Sequence[str] = ("dbwot.com", "ygwpr.com", "imxwe.com")

    #: Local-part alphabet and length used by the reference implementation.
    LOCAL_ALPHABET = string.ascii_lowercase + string.digits
    LOCAL_LENGTH = 10

    def __init__(
        self,
        domains: Optional[Sequence[str]] = None,
        timeout_sec: float = 25.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        jwt_attempts: int = 3,
    ) -> None:
        self._domains = tuple(domains) if domains else tuple(self.DOMAINS)
        if not self._domains:
            raise ValueError("tenminmail requires at least one catch-all domain")
        self._timeout = float(timeout_sec)
        self._transport = transport
        self._jwt_attempts = max(1, int(jwt_attempts))
        self._client: Optional[httpx.AsyncClient] = None
        self._jwt = ""
        self._lock = asyncio.Lock()
        self._domain_cursor = 0

    # -- http plumbing ----------------------------------------------------

    def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            # No custom User-Agent on purpose: we are not impersonating a
            # browser here, and the provider does not require one.
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
                follow_redirects=False,
            )
        return self._client

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": "Bearer " + self._jwt,
            "Content-Type": "application/json",
            "X-Request-ID": uuid.uuid4().hex,
            "X-Timestamp": str(int(time.time())),
            "Origin": self.ORIGIN,
            "Referer": self.ORIGIN + "/",
            "Accept": "application/json, text/plain, */*",
        }

    async def _refresh_jwt(self) -> str:
        client = self._http()
        last_error: Optional[BaseException] = None
        for attempt in range(1, self._jwt_attempts + 1):
            try:
                response = await client.get(self.SITE)
                match = JWT_RE.search(response.text or "")
                if match:
                    self._jwt = match.group(0)
                    return self._jwt
                last_error = TenMinMailError(
                    f"no JWT in page HTML (HTTP {response.status_code})"
                )
            except Exception as exc:  # noqa: BLE001 — network/parse hiccups are retried
                last_error = exc
                logger.debug("tenminmail JWT attempt %d failed: %s", attempt, exc)
            if attempt < self._jwt_attempts:
                await asyncio.sleep(2.0)
        raise TenMinMailError(f"cannot obtain 10minutemail JWT: {last_error}")

    async def _ensure_jwt(self) -> str:
        if self._jwt:
            return self._jwt
        async with self._lock:
            if not self._jwt:
                await self._refresh_jwt()
        return self._jwt

    def _next_domain(self) -> str:
        domain = self._domains[self._domain_cursor % len(self._domains)]
        self._domain_cursor += 1
        return domain

    def _local_name(self) -> str:
        return "".join(random.choices(self.LOCAL_ALPHABET, k=self.LOCAL_LENGTH))  # noqa: S311

    # -- provider API -----------------------------------------------------

    async def create_mailbox(self) -> Mailbox:
        jwt = await self._ensure_jwt()
        email = f"{self._local_name()}@{self._next_domain()}"
        return Mailbox(
            email=email,
            password="",
            provider_token=jwt,
            provider=self.name,
        )

    async def _get_mailbox(self, email: str) -> List[Dict[str, Any]]:
        client = self._http()
        url = f"{self.API}/mailbox/{email}"
        response = await client.get(url, headers=self._headers())
        if response.status_code == 401:
            # JWT expired (23 h lifetime) — refresh once and retry.
            async with self._lock:
                await self._refresh_jwt()
            response = await client.get(url, headers=self._headers())
        if response.status_code != 200:
            raise TenMinMailError(f"mailbox list HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError:
            return []
        return data if isinstance(data, list) else []

    async def _get_body(self, email: str, mail_id: Any) -> str:
        client = self._http()
        response = await client.get(
            f"{self.API}/mailbox/{email}/{mail_id}", headers=self._headers()
        )
        return response.text if response.status_code == 200 else ""

    async def _fetch_messages(
        self, mailbox: Mailbox, since_timestamp: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        entries = await self._get_mailbox(mailbox.email)
        messages: List[Dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            mail_id = entry.get("id")
            if mail_id is None:
                continue
            body = await self._get_body(mailbox.email, mail_id)
            received = (
                entry.get("received_at")
                or entry.get("createdAt")
                or entry.get("date")
                or ""
            )
            messages.append(
                {
                    "id": mail_id,
                    "subject": str(entry.get("subject") or ""),
                    "body": body,
                    "received_at": received,
                }
            )
        return messages

    async def wait_for_code(
        self,
        mailbox: Mailbox,
        subject_pattern: str = DEFAULT_SUBJECT_PATTERN,
        timeout_sec: int = 120,
        poll_interval_sec: int = 5,
    ) -> Optional[str]:
        deadline = time.monotonic() + max(1, int(timeout_sec))
        while time.monotonic() < deadline:
            try:
                messages = await self._fetch_messages(mailbox)
            except Exception as exc:  # noqa: BLE001 — keep polling through hiccups
                logger.debug("tenminmail wait_for_code fetch failed: %s", exc)
                messages = []
            for message in messages:
                if subject_pattern and not re.search(
                    subject_pattern, str(message.get("subject") or ""), re.I
                ):
                    continue
                code = await self._extract_code(
                    str(message.get("body") or ""), DEFAULT_CODE_PATTERN
                )
                if code:
                    return code
            await asyncio.sleep(max(0.5, float(poll_interval_sec)))
        return None

    async def wait_for_link(
        self,
        mailbox: Mailbox,
        link_pattern: str = DEFAULT_LINK_PATTERN,
        timeout_sec: int = 90,
        poll_interval_sec: int = 5,
        subject_pattern: str = "",
    ) -> Optional[str]:
        """Poll until a message body contains a verification link.

        邮件 HTML 里的 ``&`` 常被转义成 ``\\u0026``，必须还原，否则链接
        第一个查询参数之后会被截断。超时返回 None（调用方决定重试/放弃）。
        """
        deadline = time.monotonic() + max(1, int(timeout_sec))
        link_re = re.compile(link_pattern)
        while time.monotonic() < deadline:
            try:
                messages = await self._fetch_messages(mailbox)
            except Exception as exc:  # noqa: BLE001 — keep polling through hiccups
                logger.debug("tenminmail wait_for_link fetch failed: %s", exc)
                messages = []
            for message in messages:
                if subject_pattern and not re.search(
                    subject_pattern, str(message.get("subject") or ""), re.I
                ):
                    continue
                match = link_re.search(str(message.get("body") or ""))
                if match:
                    return match.group(0).replace("\\u0026", "&")
            await asyncio.sleep(max(0.5, float(poll_interval_sec)))
        return None

    async def destroy_mailbox(self, mailbox: Mailbox) -> None:
        """No-op: catch-all addresses are never registered, so nothing to tear down."""

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
