"""Workspace-scoped LaTeX compliance profile library (JSON files)."""

from __future__ import annotations

import json
import re
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.office.errors import (
    OfficeFileNotFoundError,
    OfficeParseError,
    OfficePathError,
)
from backend.office.path_safety import resolve_within

from .compliance import normalize_profile

_PROFILE_DIR = Path(".sage") / "latex-profiles"
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_MAX_PROFILE_BYTES = 256 * 1024


def _validate_name(name: str) -> str:
    value = (name or "").strip()
    if not _NAME_RE.match(value):
        raise OfficeParseError(
            "profile 名称只能是 1–64 位字母/数字/点/下划线/连字符"
        )
    return value


def _workspace(workspace: Path) -> Path:
    root = Path(workspace).resolve()
    if not root.is_dir():
        raise OfficeParseError("工作区目录不存在")
    return root


def _profiles_dir(root: Path, *, create: bool = False) -> Path:
    directory = root / _PROFILE_DIR
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    return directory


def _profile_path(root: Path, name: str) -> Path:
    safe_name = _validate_name(name)
    try:
        return resolve_within(root, _profiles_dir(root) / f"{safe_name}.json")
    except OfficePathError as exc:
        raise OfficeParseError("profile 路径不在工作区内") from exc


def _record(
    name: str,
    profile: Dict[str, Any],
    *,
    source: str = "",
    evidence: Optional[List[Dict[str, Any]]] = None,
    updated_at: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "version": 1,
        "name": name,
        "profile": normalize_profile(profile),
        "source": source,
        "evidence": evidence or [],
        "updated_at": updated_at
        or datetime.now(timezone.utc).isoformat(timespec="seconds"),  # noqa: UP017 — py38
    }


def _inside(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def list_latex_profiles(workspace: Path) -> Dict[str, Any]:
    """List saved profiles; invalid files are reported as warnings."""
    root = _workspace(workspace)
    directory = _profiles_dir(root)
    profiles: List[Dict[str, Any]] = []
    warnings: List[Dict[str, str]] = []
    if not directory.is_dir():
        return {"profiles": profiles, "warnings": warnings}
    for path in sorted(directory.glob("*.json")):
        try:
            resolved = path.resolve()
            if not resolved.is_file() or not _inside(root, resolved):
                continue
            if resolved.stat().st_size > _MAX_PROFILE_BYTES:
                warnings.append(
                    {
                        "code": "profile_too_large",
                        "message": f"跳过过大档案: {path.name}",
                    }
                )
                continue
            data = json.loads(resolved.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("profile"), dict):
                raise ValueError("profile 字段缺失")
            profiles.append(
                {
                    "name": str(data.get("name") or path.stem),
                    "profile": normalize_profile(data["profile"]),
                    "source": str(data.get("source") or ""),
                    "evidence": list(data.get("evidence") or []),
                    "updated_at": str(data.get("updated_at") or ""),
                }
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            warnings.append(
                {
                    "code": "profile_read_error",
                    "message": f"无法读取 {path.name}: {exc}",
                }
            )
    return {"profiles": profiles, "warnings": warnings}


def load_latex_profile(workspace: Path, name: str) -> Dict[str, Any]:
    root = _workspace(workspace)
    path = _profile_path(root, name)
    if not path.is_file():
        raise OfficeFileNotFoundError(path)
    if path.stat().st_size > _MAX_PROFILE_BYTES:
        raise OfficeParseError("profile 文件过大")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OfficeParseError(f"无法读取 profile: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("profile"), dict):
        raise OfficeParseError("profile 格式无效")
    return {
        "name": str(data.get("name") or path.stem),
        "profile": normalize_profile(data["profile"]),
        "source": str(data.get("source") or ""),
        "evidence": list(data.get("evidence") or []),
        "updated_at": str(data.get("updated_at") or ""),
    }


def save_latex_profile(
    workspace: Path,
    name: str,
    profile: Dict[str, Any],
    *,
    source: str = "",
    evidence: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    root = _workspace(workspace)
    safe_name = _validate_name(name)
    if not isinstance(profile, dict):
        raise OfficeParseError("profile 必须是对象")
    directory = _profiles_dir(root, create=True)
    try:
        resolve_within(root, directory)
    except OfficePathError as exc:
        raise OfficeParseError("profile 目录不在工作区内") from exc
    path = _profile_path(root, safe_name)
    record = _record(safe_name, profile, source=source, evidence=evidence)
    text = json.dumps(record, ensure_ascii=False, indent=2)
    if len(text.encode("utf-8")) > _MAX_PROFILE_BYTES:
        raise OfficeParseError("profile 内容过大")
    temporary = path.with_suffix(".json.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        with suppress(OSError):
            temporary.unlink()
        raise OfficeParseError(f"保存 profile 失败: {exc}") from exc
    return record


def delete_latex_profile(workspace: Path, name: str) -> Dict[str, Any]:
    root = _workspace(workspace)
    path = _profile_path(root, name)
    if not path.is_file():
        raise OfficeFileNotFoundError(path)
    try:
        path.unlink()
    except OSError as exc:
        raise OfficeParseError(f"删除 profile 失败: {exc}") from exc
    return {"ok": True, "name": path.stem}


__all__ = [
    "delete_latex_profile",
    "list_latex_profiles",
    "load_latex_profile",
    "save_latex_profile",
]
