"""Common API envelope schemas shared across all routers (pydantic 2.x)."""
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ApiError(BaseModel):
    """Failure envelope - success is always False (by convention, not runtime-enforced).

    Note: pydantic 2.x dropped Literal[False] runtime constraint; callers must set
    success=False manually when using this model.
    """

    model_config = ConfigDict(extra="forbid")

    success: bool = False
    error: str
    code: str | None = None
    details: dict[str, Any] | None = None


class ApiResponse(BaseModel, Generic[T]):
    """Unified response envelope (success or failure).

    On success: ``success=True`` and ``data`` carries the payload.
    On failure: ``success=False`` and ``error``/``code``/``details`` describe the cause.
    """

    model_config = ConfigDict(extra="forbid")

    success: bool
    data: T | None = None
    error: str | None = None
    code: str | None = None
    details: dict[str, Any] | None = None
