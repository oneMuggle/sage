"""Workspace health checks (2026-10-29, P2).

A resolved workspace path is not the same thing as a *usable* workspace. The
default-workspace resolver only guarantees that a path was a directory at
resolution time; by the time the user opens a session it may have been
deleted, replaced by a file, or become read-only (an unmounted drive, a
chmod'ed folder, a network share that went away).

This module answers the question "can we still work here?" without touching
the database, so the UI can colour the workspace chip and warn the user
before a tool call fails with a confusing error.

The checks are deliberately cheap and side-effect free — no writes, no
directory creation — because they run on every session load.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger(__name__)


class WorkspaceHealth(str, Enum):
    """Outcome of a workspace health check."""

    #: The directory exists, is a directory, and is readable.
    HEALTHY = "healthy"
    #: The path does not exist (deleted folder, unmounted drive).
    MISSING = "missing"
    #: The path exists but is a file, not a directory.
    NOT_A_DIRECTORY = "not_a_directory"
    #: The directory exists but the process cannot read/traverse it.
    INACCESSIBLE = "inaccessible"
    #: Readable but not writable — usable for reading, not for saving.
    READ_ONLY = "read_only"


@dataclass(frozen=True)
class WorkspaceHealthStatus:
    """The health of one workspace path.

    ``health`` carries the verdict; ``detail`` carries a human-readable
    reason for anything other than :attr:`WorkspaceHealth.HEALTHY`.
    """

    path: str
    health: WorkspaceHealth
    detail: Optional[str] = None
    writable: bool = False

    @property
    def is_usable(self) -> bool:
        """True when the workspace can at least be read from."""
        return self.health in (
            WorkspaceHealth.HEALTHY,
            WorkspaceHealth.READ_ONLY,
        )


class WorkspaceHealthChecker:
    """Check whether a workspace directory is still usable.

    Usage::

        status = WorkspaceHealthChecker().check("/path/to/workspace")
        if not status.is_usable:
            ...  # warn the user
    """

    def check(self, workspace_path: Union[str, Path]) -> WorkspaceHealthStatus:
        """Inspect ``workspace_path`` and report its health.

        Never raises: every failure mode is reported as a status so a broken
        workspace can never take the session down with it.
        """
        try:
            path = Path(workspace_path)
        except (TypeError, ValueError):
            return WorkspaceHealthStatus(
                path=str(workspace_path),
                health=WorkspaceHealth.INACCESSIBLE,
                detail="invalid path",
                writable=False,
            )

        try:
            return self._probe(path)
        except OSError as exc:
            logger.warning(
                "workspace_health: check failed",
                extra={"path": str(path), "reason": str(exc)},
            )
            return WorkspaceHealthStatus(
                path=str(path),
                health=WorkspaceHealth.INACCESSIBLE,
                detail=str(exc),
                writable=False,
            )

    @staticmethod
    def _probe(path: Path) -> WorkspaceHealthStatus:
        """Classify a well-formed path; may raise ``OSError``."""
        if not path.exists():
            return WorkspaceHealthStatus(
                path=str(path),
                health=WorkspaceHealth.MISSING,
                detail="directory does not exist",
                writable=False,
            )

        if not path.is_dir():
            return WorkspaceHealthStatus(
                path=str(path),
                health=WorkspaceHealth.NOT_A_DIRECTORY,
                detail="path is not a directory",
                writable=False,
            )

        if not os.access(path, os.R_OK | os.X_OK):
            return WorkspaceHealthStatus(
                path=str(path),
                health=WorkspaceHealth.INACCESSIBLE,
                detail="directory is not readable",
                writable=False,
            )

        if not os.access(path, os.W_OK):
            return WorkspaceHealthStatus(
                path=str(path),
                health=WorkspaceHealth.READ_ONLY,
                detail="directory is read-only",
                writable=False,
            )

        return WorkspaceHealthStatus(
            path=str(path),
            health=WorkspaceHealth.HEALTHY,
            writable=True,
        )
