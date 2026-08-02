# backend/data/artifact_reader.py
"""读取 artifact 文件内容并支持在文件管理器中显示。"""

from __future__ import annotations

import base64
import subprocess
import sys
from pathlib import Path

from backend.data import artifact_repo

MAX_TEXT_BYTES = 500_000
MAX_IMAGE_BYTES = 10_000_000

_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}


def read_text(artifact_id: str, max_bytes: int = MAX_TEXT_BYTES) -> dict:
    """读取文本类产物内容,超长截断。"""
    artifact = artifact_repo.get_artifact(artifact_id)
    if artifact is None:
        return {"ok": False, "error": "artifact not found"}

    path = Path(artifact.path)
    if not path.is_file():
        return {"ok": False, "error": "file not found"}

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"ok": False, "error": "binary file cannot be previewed"}

    encoded = text.encode("utf-8")
    truncated = len(encoded) > max_bytes
    if truncated:
        text = encoded[:max_bytes].decode("utf-8", errors="ignore")

    return {"ok": True, "kind": artifact.kind, "content": text, "truncated": truncated}


def read_image(artifact_id: str, max_bytes: int = MAX_IMAGE_BYTES) -> dict:
    """读取图片类产物,返回 base64 data URL。"""
    artifact = artifact_repo.get_artifact(artifact_id)
    if artifact is None:
        return {"ok": False, "error": "artifact not found"}

    path = Path(artifact.path)
    if not path.is_file():
        return {"ok": False, "error": "file not found"}

    if path.stat().st_size > max_bytes:
        return {"ok": False, "error": "file too large"}

    mime = _IMAGE_MIME.get(path.suffix.lower(), "application/octet-stream")
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"ok": True, "kind": "image", "data_url": f"data:{mime};base64,{data}"}


def reveal_in_file_manager(artifact_id: str) -> dict:
    """在系统文件管理器中显示文件(macOS/Windows/Linux)。"""
    artifact = artifact_repo.get_artifact(artifact_id)
    if artifact is None:
        return {"ok": False, "error": "artifact not found"}

    path = Path(artifact.path)
    if not path.is_file():
        return {"ok": False, "error": "file not found"}

    try:
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", str(path)], check=True)
        elif sys.platform == "win32":
            subprocess.run(["explorer", f"/select,{path}"], check=True)
        else:
            subprocess.run(["xdg-open", str(path.parent)], check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        return {"ok": False, "error": str(exc)}

    return {"ok": True}
