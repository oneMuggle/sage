"""Three-layer storage for Word rule packs (M2a).

- built-in: :mod:`backend.office.word_rulepack_builtin` (read-only)
- workspace: ``<workspace>/.sage/word-rulepacks/<id>.json``
- inline: supplied directly in an audit request (handled by the route)

Workspace files are JSON records ``{"version": 1, "pack": {...},
"updated_at": "<ISO-8601>"}``. Built-in ids cannot be overwritten or deleted.
"""

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

from .word_audit import validate_rulepack
from .word_rulepack_builtin import builtin_rulepacks
from .word_rulepack_models import WordRulePack

DEFAULT_RULEPACK_ID = "general-quality"

_RULEPACK_DIR = Path(".sage") / "word-rulepacks"
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_MAX_RULEPACK_BYTES = 256 * 1024


def _validate_name(pack_id: str) -> str:
    value = (pack_id or "").strip()
    if not _NAME_RE.match(value):
        raise OfficeParseError("规则包 id 只能是 1–64 位字母/数字/点/下划线/连字符")
    return value


def _workspace(workspace: Path) -> Path:
    root = Path(workspace).resolve()
    if not root.is_dir():
        raise OfficeParseError("工作区目录不存在")
    return root


def _rulepacks_dir(root: Path, *, create: bool = False) -> Path:
    directory = root / _RULEPACK_DIR
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    return directory


def _rulepack_path(root: Path, pack_id: str) -> Path:
    safe_id = _validate_name(pack_id)
    try:
        return resolve_within(root, _rulepacks_dir(root) / f"{safe_id}.json")
    except OfficePathError as exc:
        raise OfficeParseError("规则包路径不在工作区内") from exc


def _builtin_by_id() -> Dict[str, WordRulePack]:
    return {pack.id: pack for pack in builtin_rulepacks()}


def _summary(pack: WordRulePack, origin: str) -> Dict[str, Any]:
    return {
        "id": pack.id,
        "name": pack.name,
        "version": pack.version,
        "description": pack.description,
        "source": pack.source,
        "origin": origin,
        "rule_count": len(pack.rules),
    }


def _load_record(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise OfficeFileNotFoundError(path)
    if path.stat().st_size > _MAX_RULEPACK_BYTES:
        raise OfficeParseError("规则包文件过大")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OfficeParseError(f"无法读取规则包: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("pack"), dict):
        raise OfficeParseError("规则包格式无效")
    return data


def list_rulepacks(workspace: Optional[Path]) -> Dict[str, Any]:
    """List built-in packs plus workspace packs (workspace optional)."""
    packs: List[Dict[str, Any]] = [
        _summary(pack.model_copy(deep=True), "builtin")
        for pack in builtin_rulepacks()
    ]
    warnings: List[Dict[str, str]] = []
    if workspace is None:
        return {"packs": packs, "warnings": warnings}

    root = _workspace(workspace)
    builtin_ids = set(_builtin_by_id())
    directory = _rulepacks_dir(root)
    if not directory.is_dir():
        return {"packs": packs, "warnings": warnings}
    for path in sorted(directory.glob("*.json")):
        try:
            resolved = path.resolve()
            if not resolved.is_file():
                continue
            data = _load_record(resolved)
            pack = WordRulePack.model_validate(data["pack"])
            if pack.id in builtin_ids:
                warnings.append(
                    {
                        "code": "builtin_id_shadowed",
                        "message": f"工作区规则包 {pack.id} 与内置包同名，已忽略（内置优先）",
                    }
                )
                continue
            packs.append(_summary(pack, "workspace"))
        except (OSError, ValueError, OfficeParseError) as exc:
            warnings.append(
                {
                    "code": "rulepack_read_error",
                    "message": f"无法读取 {path.name}: {exc}",
                }
            )
    return {"packs": packs, "warnings": warnings}


def load_rulepack(workspace: Optional[Path], pack_id: str) -> Dict[str, Any]:
    """Load a workspace pack first, then fall back to a built-in pack."""
    safe_id = _validate_name(pack_id)
    if workspace is not None:
        root = _workspace(workspace)
        path = _rulepack_path(root, safe_id)
        if path.is_file():
            data = _load_record(path)
            pack = WordRulePack.model_validate(data["pack"])
            if pack.id in _builtin_by_id():
                raise OfficeParseError("工作区规则包不能使用内置规则包 id")
            return {"origin": "workspace", "pack": pack}
    builtin = _builtin_by_id().get(safe_id)
    if builtin is not None:
        return {"origin": "builtin", "pack": builtin.model_copy(deep=True)}
    raise OfficeFileNotFoundError(Path(f"{safe_id}.json"))


def save_rulepack(workspace: Path, pack: WordRulePack) -> WordRulePack:
    """Persist a workspace rule pack after full validation."""
    validate_rulepack(pack)
    if pack.id in _builtin_by_id():
        raise OfficeParseError("内置规则包不可覆盖；请使用新的规则包 id")
    root = _workspace(workspace)
    safe_id = _validate_name(pack.id)
    directory = _rulepacks_dir(root, create=True)
    try:
        resolve_within(root, directory)
    except OfficePathError as exc:
        raise OfficeParseError("规则包目录不在工作区内") from exc
    path = _rulepack_path(root, safe_id)
    record = {
        "version": 1,
        "pack": pack.model_dump(mode="json"),
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),  # noqa: UP017 — py38
    }
    text = json.dumps(record, ensure_ascii=False, indent=2)
    if len(text.encode("utf-8")) > _MAX_RULEPACK_BYTES:
        raise OfficeParseError("规则包内容过大")
    temporary = path.with_suffix(".json.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        with suppress(OSError):
            temporary.unlink()
        raise OfficeParseError(f"保存规则包失败: {exc}") from exc
    return pack


def delete_rulepack(workspace: Path, pack_id: str) -> Dict[str, Any]:
    """Delete a workspace rule pack; built-in packs are protected."""
    safe_id = _validate_name(pack_id)
    if safe_id in _builtin_by_id():
        raise OfficeParseError("内置规则包不可删除")
    root = _workspace(workspace)
    path = _rulepack_path(root, safe_id)
    if not path.is_file():
        raise OfficeFileNotFoundError(path)
    try:
        path.unlink()
    except OSError as exc:
        raise OfficeParseError(f"删除规则包失败: {exc}") from exc
    return {"ok": True, "id": safe_id}


__all__ = [
    "DEFAULT_RULEPACK_ID",
    "delete_rulepack",
    "list_rulepacks",
    "load_rulepack",
    "save_rulepack",
]
