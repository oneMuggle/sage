"""File-backed tweaks store (per project).

Tweaks are user-adjustable design parameters (accent color, border radius,
font scale, density) that modify the preview without regenerating the artifact.
Stored at <workspace>/design/<project_id>/tweaks.json.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

__all__ = ["ProjectTweaks", "TweaksStore"]


class ProjectTweaks(BaseModel):
    """User-adjustable design parameters."""

    model_config = ConfigDict(extra="forbid")

    accent: Optional[str] = None  # CSS color, e.g. "#1a56db"
    radius: Optional[float] = None  # border-radius in px, e.g. 6.0
    font_size: Optional[float] = None  # font-size-base in px, e.g. 16.0
    density: Optional[float] = None  # space-4 in px, e.g. 16.0
    font_family: Optional[str] = None  # CSS font stack, e.g. "Georgia, serif"


class TweaksStore:
    """Persist tweaks under <base_dir>/<project_id>/tweaks.json."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._lock = threading.Lock()

    def _path(self, project_id: str) -> Path:
        return self._base_dir / Path(project_id).name / "tweaks.json"

    def get(self, project_id: str) -> Optional[ProjectTweaks]:
        """Read tweaks; returns None if file missing or corrupt."""
        path = self._path(project_id)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return ProjectTweaks(**raw)
        except (OSError, ValueError, TypeError):
            logger.warning("Unreadable design tweaks file: %s", path)
            return None

    def put(self, project_id: str, tweaks: ProjectTweaks) -> ProjectTweaks:
        """Write tweaks atomically."""
        with self._lock:
            path = self._path(project_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(tweaks.model_dump(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(path)
        return tweaks

    def clear(self, project_id: str) -> ProjectTweaks:
        """Reset all overrides (write an empty tweaks object)."""
        return self.put(project_id, ProjectTweaks())

    def update(
        self,
        project_id: str,
        *,
        accent: Optional[str] = None,
        radius: Optional[float] = None,
        font_size: Optional[float] = None,
        density: Optional[float] = None,
        font_family: Optional[str] = None,
    ) -> ProjectTweaks:
        """Merge partial tweaks into existing; write back."""
        existing = self.get(project_id) or ProjectTweaks()
        merged = existing.model_copy(
            update={
                k: v
                for k, v in {
                    "accent": accent,
                    "radius": radius,
                    "font_size": font_size,
                    "density": density,
                    "font_family": font_family,
                }.items()
                if v is not None
            }
        )
        return self.put(project_id, merged)
