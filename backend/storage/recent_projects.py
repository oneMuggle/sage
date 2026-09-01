"""Recent wiki projects store — atomic JSON file under user data dir."""

from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel

from backend.wiki.files import secure_atomic_write_file, secure_read_text

MAX_RECENT = 10


class RecentProject(BaseModel):
    path: str
    name: str
    opened_at: float
    intent: Literal["create", "open"]  # type: ignore[valid-type]


def _validate_recent_project(raw: Any) -> RecentProject:
    """Validate a stored entry with either Pydantic major version."""
    validator = getattr(RecentProject, "model_validate", None)
    if callable(validator):
        return validator(raw)
    return RecentProject.parse_obj(raw)


def _dump_recent_project(item: RecentProject) -> Dict[str, Any]:
    """Serialize a recent entry with either Pydantic major version."""
    dumper = getattr(item, "model_dump", None)
    if callable(dumper):
        return dumper()
    return item.dict()


def user_data_dir() -> Path:
    """Return the user-writable data directory.

    Honors ``SAGE_USER_DATA_DIR``; defaults to ``~/.config/sage``.
    """
    raw = os.environ.get("SAGE_USER_DATA_DIR")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".config" / "sage"


def recent_projects_file() -> Path:
    d = user_data_dir()
    if not d.exists():
        d.mkdir(parents=True, exist_ok=True)
    if not d.is_dir() or d.is_symlink():
        raise OSError("recent projects 数据目录必须是实际目录")
    return d / "recent-projects.json"


def _read_raw() -> List[Any]:
    f = recent_projects_file()
    try:
        text = secure_read_text(f.parent, f)
    except (FileNotFoundError, OSError, UnicodeError):
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


def load_recent() -> List[RecentProject]:
    items: List[RecentProject] = []
    for raw in _read_raw():
        try:
            items.append(_validate_recent_project(raw))
        except Exception:
            continue
    return items


def save_recent(items: List[RecentProject]) -> None:
    """Atomic write using a random, exclusive, private temporary file."""
    f = recent_projects_file()
    payload = json.dumps([_dump_recent_project(i) for i in items], ensure_ascii=False, indent=2)
    secure_atomic_write_file(f.parent, f, payload)


def record_recent(path: str, name: str, intent: Literal["create", "open"]) -> None:
    """Add or refresh an entry; dedup by path; truncate to MAX_RECENT."""
    if intent not in ("create", "open"):
        raise ValueError("intent must be 'create' or 'open'")
    items = load_recent()
    items = [i for i in items if i.path != path]
    items.insert(
        0,
        RecentProject(path=path, name=name, opened_at=time.time(), intent=intent),
    )
    items = items[:MAX_RECENT]
    save_recent(items)


def most_recent_parent() -> Optional[str]:
    """Parent directory of the most recent entry, or None if empty/missing."""
    items = load_recent()
    if not items:
        return None
    parent = Path(items[0].path).expanduser().resolve().parent
    if not parent.exists():
        return None
    return str(parent)
