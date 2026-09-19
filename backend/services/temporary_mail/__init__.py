"""Temporary email providers for Arena account registration."""

from __future__ import annotations

from .base import DEFAULT_CODE_PATTERN, DEFAULT_SUBJECT_PATTERN, Mailbox, TemporaryMailProvider
from .registry import UnknownProviderError, available_providers, create_provider

__all__ = [
    "DEFAULT_CODE_PATTERN",
    "DEFAULT_SUBJECT_PATTERN",
    "Mailbox",
    "TemporaryMailProvider",
    "UnknownProviderError",
    "available_providers",
    "create_provider",
]
