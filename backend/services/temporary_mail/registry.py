"""Provider name → instance registry for temporary mail providers."""

from __future__ import annotations

from typing import Optional

from .base import TemporaryMailProvider


class UnknownProviderError(ValueError):
    """Configured mail_provider name has no implementation."""


def available_providers() -> list:
    """Names usable in arena_automation.yaml ``mail_provider``."""
    return ["mailtm", "tenminmail"]


def create_provider(name: str, api_key: Optional[str] = None) -> TemporaryMailProvider:
    """Build a provider instance by config name.

    ``api_key`` is reserved for providers that need one (mail.tm does not).
    """
    if name == "mailtm":
        from .mailtm import MailTmProvider

        return MailTmProvider()
    if name == "tenminmail":
        from .tenminmail import TenMinMailProvider

        return TenMinMailProvider()
    raise UnknownProviderError(
        f"未知邮箱 provider: {name!r}（可用: {', '.join(available_providers())}）"
    )


def get_provider(name: str) -> TemporaryMailProvider:
    """Production accessor for the batch registration pipeline.

    与 ``create_provider``（注册辅助面板，含人工流程的 provider）不同：
    批量管线只接已完整实现自动化收信的 provider。mailtm 走人工辅助路径，
    经此取用显式报 "not implemented"；其余未知名报 "unknown"。
    """
    if name == "tenminmail":
        from .tenminmail import TenMinMailProvider

        return TenMinMailProvider()
    if name == "mailtm":
        raise ValueError(
            f"mail provider {name!r} is not implemented for the batch pipeline"
        )
    raise ValueError(f"unknown mail provider: {name!r}")
