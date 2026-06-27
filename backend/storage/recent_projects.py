"""Recent wiki projects store — atomic JSON file under user data dir."""

from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

MAX_RECENT = 10


class RecentProject(BaseModel):
    path: str
    name: str
    opened_at: float
    intent: Literal["create", "open"]  # type: ignore[valid-type]


def user_data_dir() -> Path:
    """Return the user-writable data directory.

    Honors ``SAGE_USER_DATA_DIR``; defaults to ``~/.config/sage``.
    """
    raw = os.environ.get("SAGE_USER_DATA_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.home() / ".config" / "sage"


def recent_projects_file() -> Path:
    d = user_data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / "recent-projects.json"


def _read_raw() -> list[dict]:
    f = recent_projects_file()
    if not f.exists():
        return []
    try:
        text = f.read_text(encoding="utf-8")
    except OSError:
        return []
    if not text.strip():
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Corrupted file: back it up and start fresh
        with contextlib.suppress(OSError):
            f.rename(f.with_suffix(f.suffix + ".bak"))
        return []
    if not isinstance(data, list):
        return []
    return data


def load_recent() -> list[RecentProject]:
    items: list[RecentProject] = []
    for raw in _read_raw():
        try:
            items.append(RecentProject.model_validate(raw))
        except Exception:
            continue
    return items


def save_recent(items: list[RecentProject]) -> None:
    """Atomic write: serialize to tmp file then rename."""
    f = recent_projects_file()
    tmp = f.with_suffix(f.suffix + ".tmp")
    payload = json.dumps([i.model_dump() for i in items], ensure_ascii=False, indent=2)
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(f)


def record_recent(path: str, name: str, intent: str) -> None:
    """Add or refresh an entry; dedup by path; truncate to MAX_RECENT."""
    items = load_recent()
    items = [i for i in items if i.path != path]
    items.insert(
        0,
        RecentProject(path=path, name=name, opened_at=time.time(), intent=intent),
    )
    items = items[:MAX_RECENT]
    save_recent(items)


def most_recent_parent() -> str | None:
    """Parent directory of the most recent entry, or None if empty/missing."""
    items = load_recent()
    if not items:
        return None
    parent = Path(items[0].path).expanduser().resolve().parent
    if not parent.exists():
        return None
    return str(parent)
