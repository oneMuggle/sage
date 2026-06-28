"""Atomic JSON persistence for theme presets and active theme (py3.10+, pydantic 2.x)."""
import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

from backend.schemas.theme import ActiveTheme, ThemePreset

logger = logging.getLogger(__name__)

DEFAULTS_FILENAME = "themes.defaults.json"
RUNTIME_FILENAME = "themes.json"
ACTIVE_FILENAME = "active_theme.json"


class ThemeStorage:
    """File-backed theme store with atomic writes and corruption recovery."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_path = self.data_dir / RUNTIME_FILENAME
        self.defaults_path = self.data_dir / DEFAULTS_FILENAME
        self.active_path = self.data_dir / ACTIVE_FILENAME

    # ---------- internal ----------

    def _ensure_runtime_file(self) -> None:
        """Seed themes.json from defaults on first run, or recover from corruption."""
        if self.runtime_path.exists():
            try:
                json.loads(self.runtime_path.read_text(encoding="utf-8"))
                return  # valid file, no action
            except json.JSONDecodeError:
                # Corrupted: back up and re-seed
                backup = self.data_dir / f"themes.json.bak.{datetime.now().isoformat()}"
                self.runtime_path.rename(backup)
                logger.error("themes.json corrupted, backed up to %s", backup)

        if not self.defaults_path.exists():
            # No defaults and no runtime: write empty list
            self._atomic_write_json(self.runtime_path, [])
            return

        defaults_raw = json.loads(self.defaults_path.read_text(encoding="utf-8"))
        self._atomic_write_json(self.runtime_path, defaults_raw)

    def _atomic_write_json(self, path: Path, payload) -> None:
        """Write JSON atomically: temp file + rename."""
        dir_name = str(path.parent)
        # NamedTemporaryFile with delete=False ensures we can rename it
        fd, tmp_name = tempfile.mkstemp(dir=dir_name, prefix=".tmp_", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_name, str(path))
        except Exception:
            # Clean up temp file on any failure
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    # ---------- presets ----------

    def list(self) -> list[ThemePreset]:
        self._ensure_runtime_file()
        raw = json.loads(self.runtime_path.read_text(encoding="utf-8"))
        return [ThemePreset(**item) for item in raw]

    def get(self, theme_id: str) -> ThemePreset | None:
        for p in self.list():
            if p.id == theme_id:
                return p
        return None

    def save(self, preset: ThemePreset) -> ThemePreset:
        existing = self.list()
        # Replace if id exists, else append
        new_list = [p for p in existing if p.id != preset.id] + [preset]
        self._atomic_write_json(self.runtime_path, [p.model_dump() for p in new_list])
        return preset

    def delete(self, theme_id: str) -> bool:
        existing = self.list()
        filtered = [p for p in existing if p.id != theme_id]
        if len(filtered) == len(existing):
            return False
        self._atomic_write_json(self.runtime_path, [p.model_dump() for p in filtered])
        return True

    # ---------- active ----------

    def get_active(self) -> ActiveTheme:
        if not self.active_path.exists():
            return ActiveTheme(presetId="light")
        try:
            raw = json.loads(self.active_path.read_text(encoding="utf-8"))
            return ActiveTheme(**raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            logger.warning("active_theme.json corrupted, returning default")
            return ActiveTheme(presetId="light")

    def save_active(self, active: ActiveTheme) -> ActiveTheme:
        self._atomic_write_json(self.active_path, active.model_dump())
        return active
