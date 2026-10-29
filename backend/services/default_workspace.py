"""Default workspace resolution (2026-10-29, P0).

Single source of truth for "which directory should this session work in?".

Before this module the decision was split across three places with no shared
fallback: the renderer wrote ``sage-last-workspace-path`` to localStorage,
``store.createSession`` auto-bound from it, and Electron sniffed ``process.cwd()``
for a project root. When all three came up empty the session simply had no
workspace and every workspace-scoped tool failed with 403.

This module replaces that with one ordered chain:

    1. explicit project path — the caller already knows (project.open_project)
    2. session binding       — an existing session's live binding
    3. user preference       — ``preferences`` table; survives reinstall
    4. detected root         — Electron's cwd sniffing, a hint only
    5. scratch workspace     — ``<userData>/workspaces/default``, created lazily
    6. ``None``              — the caller renders the "pick a folder" guide

Step 4 mirrors how mainstream desktop AI tools stay usable without a project
(Cursor falls back to ``$HOME``, Cline to ``~/Desktop``) but keeps the files
in one predictable directory instead of scattering them across the home tree.

The legacy localStorage value is not read here — the frontend migrates it into
``preferences`` on first run, which then makes it visible to step 3.
"""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from backend.data.database import Database, get_database
from backend.data.settings_repo import SettingsRepository
from backend.office.errors import OfficePathError
from backend.office.session_workspace import get_workspace_binding
from backend.office.storage import validate_workspace

logger = logging.getLogger(__name__)

#: ``preferences`` key holding the directory the user last bound explicitly.
#: Persisted server-side so the choice survives a reinstall and follows the
#: user across machines when the profile is synced.
LAST_WORKSPACE_KEY = "last_workspace_path"

#: Scratch workspace layout, relative to the per-user data directory.
SCRATCH_WORKSPACE_SUBPATH = ("workspaces", "default")

#: Base used when ``SAGE_USER_DATA_DIR`` is unset — matches the convention
#: already applied to scheduled tasks and arena state in ``backend/main.py``.
_DEFAULT_USER_DATA_DIR = "backend/data"


class WorkspaceSource(str, Enum):
    """Which step of the priority chain produced a resolved path."""

    PROJECT = "project"
    SESSION_BINDING = "session_binding"
    USER_PREFERENCE = "user_preference"
    DETECTED = "detected"
    SCRATCH = "scratch"


@dataclass(frozen=True)
class WorkspaceResolution:
    """A resolved default workspace plus the provenance of that choice.

    ``is_fallback`` marks resolutions that came from the scratch workspace, so
    the UI can tell the user "you're in the scratch area" without re-deriving
    the decision.
    """

    path: str
    source: WorkspaceSource
    is_fallback: bool = False


class DefaultWorkspaceResolver:
    """Resolve the directory a new session should work in.

    Usage::

        resolver = DefaultWorkspaceResolver()
        resolution = resolver.resolve_default_workspace(project_path="/path/to/repo")
        if resolution is None:
            ...  # show the "pick a folder" guide
    """

    def __init__(
        self,
        db: Optional[Database] = None,
        user_data_dir: Optional[str] = None,
    ) -> None:
        self.db = db or get_database()
        self.settings = SettingsRepository(self.db)
        self._user_data_dir = user_data_dir

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def resolve_default_workspace(
        self,
        project_path: Optional[str] = None,
        session_id: Optional[str] = None,
        detected_root: Optional[str] = None,
    ) -> Optional[WorkspaceResolution]:
        """Walk the priority chain and return the first usable directory.

        Args:
            project_path: An explicit directory the caller already chose
                (e.g. from ``project.open_project``). Takes top priority.
            session_id: An existing session whose live binding should be
                reused, if it still points at a directory that exists.
            detected_root: A project root sniffed by Electron from the
                launch directory. Treated as a *hint*: it only applies when
                the user never bound a workspace themselves, and it is never
                remembered as the user's preference.

        Returns:
            The resolved workspace, or ``None`` when every candidate was
            unusable *and* the scratch workspace could not be created.
        """
        if project_path:
            resolution = self._validate(project_path, WorkspaceSource.PROJECT)
            if resolution is not None:
                return resolution
            logger.warning(
                "default_workspace: explicit project path is unusable, falling through"
            )

        if session_id:
            bound = self._get_session_binding(session_id)
            if bound:
                resolution = self._validate(bound, WorkspaceSource.SESSION_BINDING)
                if resolution is not None:
                    return resolution

        preferred = self.settings.get(LAST_WORKSPACE_KEY)
        if preferred:
            resolution = self._validate(preferred, WorkspaceSource.USER_PREFERENCE)
            if resolution is not None:
                return resolution
            # The remembered directory is unusable right now. Do *not* delete
            # the preference here: this is a read-only resolution path and the
            # cause is often transient (unmounted drive, offline share,
            # permission blip). Only an explicit forget_workspace() or a new
            # user choice may clear it.
            logger.info(
                "default_workspace: remembered workspace unusable, falling through"
            )

        if detected_root:
            resolution = self._validate(detected_root, WorkspaceSource.DETECTED)
            if resolution is not None:
                return resolution
            logger.info(
                "default_workspace: detected project root is unusable, falling through"
            )

        scratch = self._ensure_scratch_workspace()
        if scratch is not None:
            return WorkspaceResolution(
                path=str(scratch),
                source=WorkspaceSource.SCRATCH,
                is_fallback=True,
            )

        logger.error("default_workspace: no usable workspace could be resolved")
        return None

    def remember_workspace(self, workspace_path: str) -> str:
        """Persist an explicitly chosen directory as the user's preference.

        Args:
            workspace_path: The directory the user picked. Must exist.

        Returns:
            The canonical absolute path that was stored.

        Raises:
            OfficePathError: ``workspace_path`` is not an existing directory.
        """
        canonical = validate_workspace(Path(workspace_path))
        self.settings.set(LAST_WORKSPACE_KEY, str(canonical))
        return str(canonical)

    def forget_workspace(self) -> None:
        """Clear the remembered workspace so the next resolution falls back."""
        self.settings.delete(LAST_WORKSPACE_KEY)

    def scratch_workspace_path(self) -> Path:
        """Absolute path of the scratch workspace, without creating it."""
        base = (
            self._user_data_dir
            or os.environ.get("SAGE_USER_DATA_DIR")
            or _DEFAULT_USER_DATA_DIR
        )
        return Path(base).joinpath(*SCRATCH_WORKSPACE_SUBPATH)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _get_session_binding(self, session_id: str) -> Optional[str]:
        """Return the live binding path for a session, or ``None``."""
        try:
            binding = get_workspace_binding(self.db.get_connection(), session_id)
        except Exception:  # noqa: BLE001 — a lookup failure must not abort resolution
            logger.warning(
                "default_workspace: session binding lookup failed",
                exc_info=True,
            )
            return None
        return binding.workspace_path if binding is not None else None

    def _validate(
        self,
        raw_path: str,
        source: WorkspaceSource,
    ) -> Optional[WorkspaceResolution]:
        """Canonicalize a candidate path, or return ``None`` when unusable."""
        try:
            canonical = validate_workspace(Path(raw_path))
        except (OfficePathError, OSError, ValueError) as exc:
            logger.info(
                "default_workspace: candidate path rejected",
                extra={"candidate_source": source.value, "reason": str(exc)},
            )
            return None
        return WorkspaceResolution(path=str(canonical), source=source)

    def _ensure_scratch_workspace(self) -> Optional[Path]:
        """Create the scratch workspace, falling back to a temp directory.

        The primary location lives under the per-user data directory. When
        that is not writable (a locked-down install, a read-only profile),
        a temp directory keeps the app usable instead of leaving the session
        workspace-less.
        """
        candidates = [
            self.scratch_workspace_path(),
            Path(tempfile.gettempdir()) / "sage-workspaces" / "default",
        ]
        for candidate in candidates:
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                return candidate.resolve()
            except OSError as exc:
                logger.warning(
                    "default_workspace: scratch workspace location unusable",
                    extra={"candidate": str(candidate), "reason": str(exc)},
                )
        return None
