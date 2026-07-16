"""Office document exception hierarchy.

All office-domain errors inherit from OfficeError. A FastAPI exception handler
(registered in backend/api/office_routes.py) maps each subclass to the
appropriate HTTP status code so callers get structured errors instead of 500s.

Error → HTTP status mapping:
- OfficeFileNotFound     → 404
- OfficePathError        → 400 (path traversal, outside workspace, etc.)
- OfficeParseError       → 422 (file exists but unreadable / wrong format)
- OfficeGenerateError    → 500 (we tried to write but failed)
- OfficeSizeLimitError   → 413 (file too large)
- OfficeError (base)     → 500 (catch-all)
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


class OfficeError(Exception):
    """Base class for all office-domain errors."""

    def __init__(self, message: str, *, file_path: Optional[Path] = None) -> None:
        super().__init__(message)
        self.message = message
        self.file_path = file_path

    def __str__(self) -> str:
        if self.file_path is not None:
            return f"{self.message} (file: {self.file_path})"
        return self.message


class OfficeFileNotFoundError(OfficeError):
    """The requested file does not exist."""

    def __init__(self, file_path: Path) -> None:
        super().__init__(f"Office file not found: {file_path}", file_path=file_path)


class OfficePathError(OfficeError):
    """Path validation failed (path traversal, outside workspace, etc.)."""

    def __init__(self, message: str, *, file_path: Optional[Path] = None) -> None:
        super().__init__(message, file_path=file_path)


class OfficeParseError(OfficeError):
    """File exists but cannot be parsed (corrupt, wrong format, missing deps)."""

    def __init__(self, message: str, *, file_path: Optional[Path] = None) -> None:
        super().__init__(message, file_path=file_path)


class OfficeGenerateError(OfficeError):
    """Tried to write a document but the generator failed."""

    def __init__(self, message: str, *, file_path: Optional[Path] = None) -> None:
        super().__init__(message, file_path=file_path)


class OfficeSizeLimitError(OfficeError):
    """File exceeds the configured size limit."""

    def __init__(
        self,
        actual_size: int,
        max_size: int,
        *,
        file_path: Optional[Path] = None,
    ) -> None:
        super().__init__(
            f"File too large: {actual_size} bytes (max {max_size} bytes)",
            file_path=file_path,
        )
        self.actual_size = actual_size
        self.max_size = max_size


def office_error_to_http_status(error: OfficeError) -> int:
    """Map an OfficeError to its HTTP status code.

    Used by the FastAPI exception handler in office_routes.py.
    """
    if isinstance(error, OfficeFileNotFoundError):
        return 404
    if isinstance(error, OfficePathError):
        return 400
    if isinstance(error, OfficeParseError):
        return 422
    if isinstance(error, OfficeSizeLimitError):
        return 413
    if isinstance(error, OfficeGenerateError):
        return 500
    return 500  # base OfficeError or unknown subclass
