"""Legacy localStorage → preferences migration (2026-10-29, P1).

Before the default-workspace decision chain was centralised, the renderer
remembered the user's last bound directory in ``localStorage`` under
``sage-last-workspace-path``. That value is invisible to the backend and
dies with the browser profile, so a fresh install lost the user's choice.

This module moves the value into the ``preferences`` table, which is the
authoritative store from now on. The frontend drives the migration (only the
renderer can read ``localStorage``) and clears the legacy key once the
backend has accepted the value.

Migration is deliberately conservative:

* it never overwrites an existing preference — the user may have bound a
  workspace explicitly after the upgrade;
* it never persists a path that does not exist (or is not a directory);
* it is idempotent, so a repeated startup costs one cheap lookup.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from backend.office.errors import OfficePathError
from backend.services.default_workspace import (
    LAST_WORKSPACE_KEY,
    DefaultWorkspaceResolver,
)

logger = logging.getLogger(__name__)


class MigrationOutcome(str, Enum):
    """Result of a single migration attempt."""

    MIGRATED = "migrated"
    ALREADY_PRESENT = "already_present"
    REJECTED = "rejected"
    EMPTY = "empty"


@dataclass(frozen=True)
class MigrationResult:
    """Outcome plus the path that ended up in ``preferences`` (if any)."""

    outcome: MigrationOutcome
    path: Optional[str] = None
    reason: Optional[str] = None


def migrate_last_workspace(
    candidate_path: Optional[str],
    resolver: Optional[DefaultWorkspaceResolver] = None,
) -> MigrationResult:
    """Move a legacy localStorage value into the ``preferences`` table.

    Args:
        candidate_path: The path the renderer read from localStorage. May be
            ``None`` or empty when the user never bound a workspace.
        resolver: Resolver used for the preference lookup/write. Defaults to
            one bound to the current database.

    Returns:
        A :class:`MigrationResult` describing what happened. This function
        never raises: a failed migration must not block app startup.
    """
    if not candidate_path:
        return MigrationResult(outcome=MigrationOutcome.EMPTY)

    active = resolver or DefaultWorkspaceResolver()

    try:
        existing = active.settings.get(LAST_WORKSPACE_KEY)
    except Exception:  # noqa: BLE001 — a lookup failure must not abort startup
        logger.warning("workspace_migration: preference lookup failed", exc_info=True)
        existing = None

    if existing:
        # The user already has a preference — it is newer than the
        # localStorage value, so leave it alone.
        return MigrationResult(
            outcome=MigrationOutcome.ALREADY_PRESENT,
            path=existing,
        )

    try:
        canonical = active.remember_workspace(candidate_path)
    except OfficePathError as exc:
        logger.info(
            "workspace_migration: legacy path rejected",
            extra={"reason": str(exc)},
        )
        return MigrationResult(
            outcome=MigrationOutcome.REJECTED,
            reason=str(exc),
        )
    except Exception:  # noqa: BLE001 — never break startup on a bad legacy value
        logger.warning("workspace_migration: legacy path could not be stored", exc_info=True)
        return MigrationResult(
            outcome=MigrationOutcome.REJECTED,
            reason="unexpected error",
        )

    logger.info("workspace_migration: legacy workspace path migrated")
    return MigrationResult(outcome=MigrationOutcome.MIGRATED, path=canonical)
