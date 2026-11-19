"""File-backed iteration message store (per project).

Messages are stored at ``<base_dir>/<project_id>/messages.json`` alongside
the project's ``v<N>.html`` artifacts, mirroring the ``source.json``
convention used by the live-artifact engine. No database migration needed.
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel

from backend.compat.win7.pydantic_compat import ConfigDict

logger = logging.getLogger(__name__)

__all__ = ["IterationMessage", "MessageStore"]


class IterationMessage(BaseModel):
    """One design iteration chat message."""

    model_config = ConfigDict(extra="forbid")

    id: str
    role: Literal["user", "assistant"]
    content: str
    artifact_id: Optional[str] = None
    artifact_version: Optional[int] = None
    created_at: str


class MessageStore:
    """Persist iteration messages under ``<base_dir>/<project_id>``."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._lock = threading.Lock()

    def _path(self, project_id: str) -> Path:
        return self._base_dir / Path(project_id).name / "messages.json"

    def list(self, project_id: str) -> List[IterationMessage]:
        """Read all messages; missing or corrupt files yield an empty list."""
        path = self._path(project_id)
        if not path.exists():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("Unreadable design messages file: %s", path)
            return []
        if not isinstance(raw, list):
            return []
        messages: List[IterationMessage] = []
        for item in raw:
            try:
                messages.append(IterationMessage(**item))
            except (TypeError, ValueError):
                continue
        return messages

    def append(
        self,
        project_id: str,
        role: str,
        content: str,
        *,
        artifact_id: Optional[str] = None,
        artifact_version: Optional[int] = None,
    ) -> IterationMessage:
        """Append one message and atomically rewrite the file."""
        message = IterationMessage(
            id=str(uuid.uuid4()),
            role=role,  # type: ignore[arg-type]
            content=content,
            artifact_id=artifact_id,
            artifact_version=artifact_version,
            created_at=datetime.now(timezone.utc).isoformat(),  # noqa: UP017
        )
        with self._lock:
            messages = self.list(project_id)
            messages.append(message)
            path = self._path(project_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(
                    [m.model_dump() for m in messages],
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
            tmp.replace(path)
        return message
