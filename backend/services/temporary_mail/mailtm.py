"""Mail.tm REST adapter for TemporaryMailProvider.

Uses the public mail.tm API (https://docs.mail.tm):
    GET  /domains          → available domains
    POST /accounts         → create account {address, password}
    POST /token            → {token} JWT for subsequent calls
    GET  /me               → account id (needed for deletion)
    GET  /messages         → message list (Bearer)
    GET  /messages/{id}    → full message incl. text/html body (Bearer)
    DELETE /accounts/{id}  → delete account (Bearer)

Rate limited to 8 QPS per IP upstream — the registration assist flow is
single-mailbox by design, so this is not a concern in practice.

The HTTP client is injectable via ``transport`` (httpx.MockTransport) for tests.
"""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
import string
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from .base import DEFAULT_SUBJECT_PATTERN, Mailbox, TemporaryMailProvider

logger = logging.getLogger(__name__)

_API_BASE = "https://api.mail.tm"
_TIMEOUT = httpx.Timeout(15.0)


class MailTmError(RuntimeError):
    """Raised when the mail.tm API returns an unexpected response."""


class MailTmProvider(TemporaryMailProvider):
    """Single-mailbox-at-a-time adapter. One instance == one client."""

    name = "mailtm"

    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None):
        self._client = httpx.AsyncClient(
            base_url=_API_BASE, timeout=_TIMEOUT, transport=transport
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- TemporaryMailProvider --------------------------------------------

    async def create_mailbox(self) -> Mailbox:
        domain = await self._pick_domain()
        local_part = "".join(
            secrets.choice(string.ascii_lowercase + string.digits) for _ in range(12)
        )
        address = f"{local_part}@{domain}"
        # mailbox password: random, only used to (re)fetch the JWT — never shown
        mailbox_password = secrets.token_urlsafe(18)
        r = await self._client.post(
            "/accounts", json={"address": address, "password": mailbox_password}
        )
        if r.status_code not in (200, 201):
            raise MailTmError(f"mail.tm 创建邮箱失败 HTTP {r.status_code}: {r.text[:120]}")
        token = await self._login(address, mailbox_password)
        return Mailbox(
            email=address,
            password=mailbox_password,
            provider_token=token,
            provider=self.name,
        )

    async def wait_for_code(
        self,
        mailbox: Mailbox,
        subject_pattern: str = DEFAULT_SUBJECT_PATTERN,
        timeout_sec: int = 120,
        poll_interval_sec: int = 5,
    ) -> Optional[str]:
        subject_re = re.compile(subject_pattern, re.IGNORECASE)
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            try:
                messages = await self._fetch_messages(mailbox)
            except Exception:  # noqa: BLE001 — 抖动继续轮询直至超时
                messages = []
            for message in messages:
                if not subject_re.search(str(message.get("subject") or "")):
                    continue
                code = await self._extract_code(str(message.get("body") or ""))
                if code:
                    return code
            await asyncio.sleep(max(1, poll_interval_sec))
        return None

    async def destroy_mailbox(self, mailbox: Mailbox) -> None:
        try:
            account_id = await self._account_id(mailbox)
            if not account_id:
                return
            r = await self._client.delete(
                f"/accounts/{account_id}",
                headers=self._auth(mailbox),
            )
            if r.status_code not in (200, 204, 404):
                logger.debug("mail.tm 销毁邮箱返回 HTTP %s（忽略）", r.status_code)
        except Exception as exc:  # noqa: BLE001 — best-effort by contract
            logger.debug("mail.tm 销毁邮箱失败（忽略）: %s", exc)

    async def _fetch_messages(
        self, mailbox: Mailbox, since_timestamp: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        r = await self._client.get("/messages", headers=self._auth(mailbox))
        if r.status_code == 401:
            # JWT 过期（约 1 天）——用邮箱密码换新 token 再试一次
            mailbox.provider_token = await self._login(mailbox.email, mailbox.password)
            r = await self._client.get("/messages", headers=self._auth(mailbox))
        if r.status_code != 200:
            raise MailTmError(f"mail.tm 拉取消息列表失败 HTTP {r.status_code}")
        data = r.json()
        if isinstance(data, dict):
            # API Platform 集合：JSON-LD 用 "hydra:member"，新版用 "member"
            items = data.get("member") or data.get("hydra:member") or []
        else:
            items = data or []
        if not isinstance(items, list):
            return []
        out: List[Dict[str, Any]] = []
        for item in items:
            message_id = str(item.get("id") or "")
            if not message_id:
                continue
            out.append(await self._hydrate(mailbox, message_id, item))
        return out

    # -- internal ----------------------------------------------------------

    def _auth(self, mailbox: Mailbox) -> Dict[str, str]:
        return {"Authorization": f"Bearer {mailbox.provider_token}"}

    async def _pick_domain(self) -> str:
        r = await self._client.get("/domains", params={"page": 1})
        if r.status_code != 200:
            raise MailTmError(f"mail.tm 拉取域名失败 HTTP {r.status_code}")
        data = r.json()
        if isinstance(data, dict):
            members = data.get("member") or data.get("hydra:member") or []
        else:
            members = data or []
        for item in members or []:
            if item.get("isActive", item.get("active", True)) and item.get("domain"):
                return str(item["domain"])
        raise MailTmError("mail.tm 无可用域名")

    async def _login(self, address: str, password: str) -> str:
        r = await self._client.post("/token", json={"address": address, "password": password})
        if r.status_code != 200:
            raise MailTmError(f"mail.tm 换取 token 失败 HTTP {r.status_code}")
        token = str(r.json().get("token") or "")
        if not token:
            raise MailTmError("mail.tm token 响应为空")
        return token

    async def _account_id(self, mailbox: Mailbox) -> Optional[str]:
        r = await self._client.get("/me", headers=self._auth(mailbox))
        if r.status_code != 200:
            return None
        return str(r.json().get("id") or "") or None

    async def _hydrate(
        self, mailbox: Mailbox, message_id: str, list_item: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Fetch the full message body; fall back to list metadata on error."""
        try:
            r = await self._client.get(
                f"/messages/{message_id}", headers=self._auth(mailbox)
            )
            full = r.json() if r.status_code == 200 else {}
        except Exception:  # noqa: BLE001 — 单条失败不影响整体轮询
            full = {}
        text = str(full.get("text") or "")
        html = full.get("html")
        if isinstance(html, list):
            html = "\n".join(str(part) for part in html)
        body = text or str(html or "")
        return {
            "id": message_id,
            "subject": str(full.get("subject") or list_item.get("subject") or ""),
            "body": body,
            "received_at": full.get("createdAt") or list_item.get("createdAt"),
        }
