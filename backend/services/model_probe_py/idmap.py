"""Inspired by arena-model-probe/src/idmap.js (Python 3.8 compatible).

UUID → model name resolution. The map is populated by fetching Arena's
leaderboard RSC payload periodically.
"""

from __future__ import annotations

import logging
import re
from typing import Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)


#: Module-level model map. Mutated by refreshModelMap().
_model_map: Dict[str, str] = {}


#: UUID v4 format (8-4-4-4-12 hex)
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def isUuid(s: str) -> bool:
    """True if s is a UUID-shaped string."""
    if not isinstance(s, str) or not s:
        return False
    return bool(_UUID_RE.match(s))


def resolveModelId(identifier: str, known_map: Optional[Dict] = None) -> Optional[str]:
    """If identifier is a UUID in the map, return the canonical model name.

    Otherwise return identifier unchanged (passthrough for plain model names).
    """
    if not identifier:
        return identifier
    mapping = known_map if known_map is not None else _model_map
    if isUuid(identifier) and identifier in mapping:
        return mapping[identifier]
    return identifier


async def refreshModelMap(
    fetcher: Optional[Callable[[], Awaitable[Dict]]] = None,
) -> Dict:
    """Refresh the UUID → model name map.

    If fetcher is provided, call it and replace the map. If not, no-op
    (the caller is expected to manage when to fetch in production).
    """
    if fetcher is None:
        return {"loaded": len(_model_map), "updated": False}
    try:
        new_map = await fetcher()
        if isinstance(new_map, dict):
            _model_map.clear()
            _model_map.update(new_map)
            logger.info("idmap refreshed: %d entries", len(new_map))
            return {"loaded": len(new_map), "updated": True}
    except Exception as e:  # noqa: BLE001
        logger.warning("idmap refresh failed: %s", e)
        return {"loaded": len(_model_map), "updated": False, "error": str(e)}
    return {"loaded": len(_model_map), "updated": False}


def mapStats() -> Dict:
    """Return current map statistics."""
    return {"loaded": len(_model_map)}
