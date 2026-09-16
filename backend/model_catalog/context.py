"""Choose a safe effective context window from resolved limits."""

from .schemas import ContextLimits

_UNKNOWN_AUTOMATIC_WINDOW = 4096


def effective_window(limits: ContextLimits, automatic: bool, fixed: int) -> int:
    """Automatic ignores fixed; manual caps fixed by every known limit."""
    if not isinstance(automatic, bool):
        raise ValueError("automatic must be a boolean")
    if isinstance(fixed, bool) or not isinstance(fixed, int) or fixed <= 0:
        raise ValueError("fixed context window must be a positive integer")
    known = [value for value in (limits.native, limits.service) if value is not None]
    if automatic:
        return min(known, default=_UNKNOWN_AUTOMATIC_WINDOW)
    return min([fixed, *known])
