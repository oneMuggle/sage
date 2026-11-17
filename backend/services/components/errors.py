"""Component package errors with stable machine-readable codes."""

from __future__ import annotations


class ComponentError(Exception):
    """Raised when a ``.sagepkg`` cannot be verified or installed."""

    def __init__(self, message: str, code: str = "component_error") -> None:
        super().__init__(message)
        self.code = code
