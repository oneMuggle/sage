"""Playbook share service (2026-11-03).

Orchestrates share-link creation and consumption. Thin layer between the
HTTP routes and the two repositories (shares + library).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from backend.data.playbook_library_repo import PlaybookLibraryRepository
from backend.data.playbook_share_repo import (
    DEFAULT_EXPIRY_DAYS,
    PlaybookShareRepository,
)


class PlaybookShareError(Exception):
    """Base error for share operations."""


class PlaybookNotFoundError(PlaybookShareError):
    """Raised when the library playbook does not exist."""


class ShareTokenExpiredError(PlaybookShareError):
    """Raised when the share token has expired."""


class ShareTokenInvalidError(PlaybookShareError):
    """Raised when the share token does not exist."""


@dataclass
class ShareLinkResult:
    """Result of creating a share link."""

    token: str
    playbook_id: str
    playbook_name: str
    expires_at: int
    share_url: str


def create_share_link(
    playbook_id: str,
    *,
    expiry_days: int = DEFAULT_EXPIRY_DAYS,
    base_url: str = "",
) -> ShareLinkResult:
    """Create a new share link for a library playbook.

    Parameters
    ----------
    playbook_id:
        UUID of the playbook in ``playbook_library``.
    expiry_days:
        Number of days until the link expires (default 7).
    base_url:
        Optional base URL for constructing the share URL. When empty, the
        URL contains only the path portion.
    """
    library = PlaybookLibraryRepository().get(playbook_id)
    if library is None:
        raise PlaybookNotFoundError(f"规程库条目不存在: {playbook_id}")

    share = PlaybookShareRepository().create(playbook_id, expiry_days=expiry_days)
    path = f"/share/playbook/{share.token}"
    share_url = f"{base_url.rstrip('/')}{path}" if base_url else path

    return ShareLinkResult(
        token=share.token,
        playbook_id=playbook_id,
        playbook_name=library.name,
        expires_at=share.expires_at,
        share_url=share_url,
    )


def resolve_share_token(token: str) -> Dict[str, Any]:
    """Resolve a share token to the playbook spec.

    Returns a dict with keys: ``playbook_id``, ``playbook_name``, ``spec``,
    ``shared_at``, ``expires_at``.

    Raises ``ShareTokenInvalidError`` if the token is not found, or
    ``ShareTokenExpiredError`` if it has expired.
    """
    share = PlaybookShareRepository().get_by_token(token)
    if share is None:
        raise ShareTokenInvalidError("分享链接无效或已被删除")
    if share.is_expired:
        raise ShareTokenExpiredError("分享链接已过期")

    library = PlaybookLibraryRepository().get(share.playbook_id)
    if library is None:
        raise PlaybookNotFoundError("该规程已被删除")

    return {
        "playbook_id": library.id,
        "playbook_name": library.name,
        "spec": library.spec,
        "shared_at": share.created_at,
        "expires_at": share.expires_at,
    }


__all__ = [
    "PlaybookShareError",
    "PlaybookNotFoundError",
    "ShareLinkResult",
    "ShareTokenExpiredError",
    "ShareTokenInvalidError",
    "create_share_link",
    "resolve_share_token",
]
