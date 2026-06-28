"""主题存储 — 单文件 JSON 原子读写"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ("id", "name", "css", "appearance")
VALID_APPEARANCES = frozenset({"light", "dark"})


class ThemeStorage:
    """JSON 文件持久化 — 每主题一个文件 <id>.json"""

    def __init__(self, storage_dir: Path | str | None = None) -> None:
        if storage_dir is None:
            storage_dir = Path(__file__).resolve().parent.parent / "data" / "themes"
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, theme_id: str) -> Path:
        return self._dir / f"{theme_id}.json"

    def _validate(self, payload: dict) -> None:
        for field in REQUIRED_FIELDS:
            if field not in payload:
                raise ValueError(f"Missing required field: {field!r}")
        if payload["appearance"] not in VALID_APPEARANCES:
            raise ValueError(
                f"Invalid appearance: {payload['appearance']!r}, "
                f"must be one of {VALID_APPEARANCES}"
            )

    def save(self, payload: dict) -> str:
        """原子写入 payload，返回 id"""
        self._validate(payload)
        target = self._path(payload["id"])
        # 原子写：temp file + rename
        fd, tmp_path_str = tempfile.mkstemp(dir=self._dir, suffix=".tmp")
        tmp_path = Path(tmp_path_str)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            tmp_path.replace(target)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink()
            raise
        return payload["id"]

    def list(self) -> list[dict]:
        """列出所有主题，跳过损坏文件（记录 warning）"""
        results: list[dict] = []
        for path in self._dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                results.append(data)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("跳过损坏的主题文件 %s: %s", path.name, exc)
        return results

    def get(self, theme_id: str) -> dict | None:
        """按 id 获取主题"""
        path = self._path(theme_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("读取主题文件失败 %s: %s", path.name, exc)
            return None

    def delete(self, theme_id: str) -> bool:
        """按 id 删除主题，返回是否成功"""
        path = self._path(theme_id)
        if not path.exists():
            return False
        path.unlink()
        return True
