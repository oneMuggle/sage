"""Abstract base for temporary email providers."""

from __future__ import annotations

import abc
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, Dict, List, Optional


@dataclass
class Mailbox:
    """A disposable email address obtained from a provider."""
    email: str
    password: str = field(repr=False)
    provider_token: str = field(repr=False)
    provider: str
    created_at: datetime = field(default_factory=datetime.utcnow)


#: Default regex used to detect verification emails
DEFAULT_SUBJECT_PATTERN = r"verification|verify|code|confirm"

#: Default regex used to extract a 4-8 digit code from message body
DEFAULT_CODE_PATTERN = r"\b(\d{4,8})\b"


class TemporaryMailProvider(abc.ABC):
    """Subclass this to add a new provider. Implementations live in their own
    modules (e.g. mailtm.py, guerrilla.py) and register themselves via the
    registry module."""

    #: Provider name used in config (e.g. "mailtm", "guerrilla", "<your-name>")
    name: ClassVar[str] = ""

    @abc.abstractmethod
    async def create_mailbox(self) -> Mailbox:
        """Create a new disposable mailbox. Returns the credentials."""

    @abc.abstractmethod
    async def wait_for_code(
        self,
        mailbox: Mailbox,
        subject_pattern: str = DEFAULT_SUBJECT_PATTERN,
        timeout_sec: int = 120,
        poll_interval_sec: int = 5,
    ) -> Optional[str]:
        """Poll the inbox for a message matching subject_pattern and extract
        a verification code from the body. Returns None on timeout."""

    async def wait_for_message(
        self,
        mailbox: Mailbox,
        subject_pattern: str = DEFAULT_SUBJECT_PATTERN,
        body_pattern: Optional[str] = None,
        timeout_sec: int = 120,
        poll_interval_sec: int = 5,
    ) -> Optional[Dict[str, Any]]:
        """Poll the inbox for a message matching subject_pattern; when
        body_pattern is given the message body must also match.

        Returns the full message dict (with body), or None on timeout.
        Shared implementation on top of _fetch_messages — providers only
        need to implement fetching. Cancelled externally by closing the
        provider's HTTP client (poll loop sees the error and returns None).
        """
        import asyncio
        import time

        body_re = re.compile(body_pattern) if body_pattern else None
        subject_re = re.compile(subject_pattern, re.IGNORECASE)

        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            try:
                messages = await self._fetch_messages(mailbox)
            except Exception:  # noqa: BLE001 — provider 网络抖动：继续轮询直至超时
                messages = []
            for message in messages:
                if not subject_re.search(str(message.get("subject") or "")):
                    continue
                if body_re is not None and not body_re.search(
                    str(message.get("body") or "")
                ):
                    continue
                return message
            await asyncio.sleep(max(1, poll_interval_sec))
        return None

    @abc.abstractmethod
    async def destroy_mailbox(self, mailbox: Mailbox) -> None:
        """Best-effort cleanup. Must never raise."""

    @abc.abstractmethod
    async def _fetch_messages(
        self, mailbox: Mailbox, since_timestamp: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Provider-specific message fetch. Returned dicts have at least
        {id, subject, body, received_at}."""

    # -- shared helper ----------------------------------------------------

    async def _extract_code(
        self, body: str, code_pattern: str = DEFAULT_CODE_PATTERN
    ) -> Optional[str]:
        """Extract the first matching verification code from message body."""
        if not body:
            return None
        match = re.search(code_pattern, body)
        return match.group(1) if match else None
