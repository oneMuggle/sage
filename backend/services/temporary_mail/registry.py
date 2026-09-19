"""Provider name → instance registry for temporary mail providers."""

from __future__ import annotations

from typing import Optional

from .base import TemporaryMailProvider


class UnknownProviderError(ValueError):
    """Configured mail_provider name has no implementation."""


def available_providers() -> list:
    """Names usable in arena_automation.yaml ``mail_provider``."""
    return ["mailtm"]


def create_provider(name: str, api_key: Optional[str] = None) -> TemporaryMailProvider:
    """Build a provider instance by config name.

    ``api_key`` is reserved for providers that need one (mail.tm does not).
    """
    if name == "mailtm":
        from .mailtm import MailTmProvider

        return MailTmProvider()
    raise UnknownProviderError(
        f"未知邮箱 provider: {name!r}（可用: {', '.join(available_providers())}）"
    )
