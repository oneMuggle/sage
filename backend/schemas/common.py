"""Common API envelope schemas shared across all routers (pydantic 2.x)."""
from typing import Any, Dict, Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiError(BaseModel):
    """Failure envelope - success is always False (by convention, not runtime-enforced).

    Note: pydantic 1.x dropped Literal[False] runtime constraint; callers must set
    success=False manually when using this model.
    """

    class Config:
        extra = "forbid"

    success: bool = False
    error: str
    code: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class ApiResponse(BaseModel, Generic[T]):
    """Unified response envelope (success or failure).

    On success: ``success=True`` and ``data`` carries the payload.
    On failure: ``success=False`` and ``error``/``code``/``details`` describe the cause.
    """

    class Config:
        extra = "forbid"

    success: bool
    data: Optional[T] = None
    error: Optional[str] = None
    code: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
