# ruff: noqa: UP006, UP007, UP035
"""Fileized harness 的 snapshot、diff 与回滚（R84）。

底层路径安全、lock 与 verify 在 ``harness_files``；本模块只负责把已校验
文件集保存为目录 snapshot，并提供差异视图与恢复操作。snapshot 内同时
保存当时的 lock，rollback 后会再次 verify，避免恢复到自相矛盾的状态。
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from backend.application.kernel.harness_config import HARNESS_LOCK_FILE_NAME
from backend.application.kernel.harness_files import (
    MAX_DIFF_TEXT_BYTES,
    MAX_HARNESS_FILES,
    MAX_HARNESS_TOTAL_BYTES,
    SNAPSHOTS_DIR_NAME,
    HarnessFileEntry,
    HarnessFilesError,
    HarnessFileSpec,
    VerificationIssue,
    _atomic_write,
    _build_lock,
    _delete_file,
    _entries_from_files,
    _format_time,
    _load_lock,
    _parse_lock_entry,
    _prepare_root,
    _raise_for_issues,
    _safe_target,
    _scan_files,
    _write_lock,
    infer_harness_component,
    verify_harness_files,
    write_harness_file_specs,
)

SNAPSHOT_SCHEMA_VERSION = 1
SNAPSHOT_KIND = "sage-harness-snapshot"
SNAPSHOT_MANIFEST_NAME = "snapshot.json"
_SNAPSHOT_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")

__all__ = [
    "SNAPSHOT_KIND",
    "SNAPSHOT_MANIFEST_NAME",
    "SNAPSHOT_SCHEMA_VERSION",
    "HarnessDiffEntry",
    "HarnessSnapshotInfo",
    "create_harness_snapshot",
    "harness_diff_view",
    "harness_status_view",
    "list_harness_snapshots",
    "rollback_harness_files",
    "write_harness_files",
]


@dataclass(frozen=True)
class HarnessSnapshotInfo:
    snapshot_id: str
    created_at: str
    file_count: int
    total_size: int
    lock_sha256: Optional[str]
    path: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.snapshot_id,
            "created_at": self.created_at,
            "file_count": self.file_count,
            "total_size": self.total_size,
            "lock_sha256": self.lock_sha256,
            "path": self.path,
        }


@dataclass(frozen=True)
class HarnessDiffEntry:
    path: str
    status: str
    component: str
    before_sha256: Optional[str]
    after_sha256: Optional[str]
    before_size: Optional[int]
    after_size: Optional[int]
    patch: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "path": self.path,
            "status": self.status,
            "component": self.component,
            "before_sha256": self.before_sha256,
            "after_sha256": self.after_sha256,
            "before_size": self.before_size,
            "after_size": self.after_size,
        }
        if self.patch is not None:
            payload["patch"] = self.patch
        return payload



def _validate_snapshot_id(value: Any) -> str:
    snapshot_id = str(value or "").strip()
    if not snapshot_id or not _SNAPSHOT_ID_RE.match(snapshot_id) or snapshot_id.startswith("."):
        raise HarnessFilesError(f"invalid snapshot id: {value!r}")
    return snapshot_id


def _new_snapshot_id(prefix: str = "snapshot") -> str:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:6]}"


def _read_snapshot_manifest(snapshot_dir: Path) -> Dict[str, Any]:
    if snapshot_dir.is_symlink() or not snapshot_dir.is_dir():
        raise HarnessFilesError(f"snapshot does not exist: {snapshot_dir}")
    manifest_path = snapshot_dir / SNAPSHOT_MANIFEST_NAME
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise HarnessFilesError(f"snapshot manifest is missing: {snapshot_dir}")
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise HarnessFilesError(f"invalid snapshot manifest: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise HarnessFilesError("snapshot manifest must be an object")
    if raw.get("schema_version") != SNAPSHOT_SCHEMA_VERSION or raw.get("kind") != SNAPSHOT_KIND:
        raise HarnessFilesError("unsupported snapshot manifest")
    return dict(raw)


def _snapshot_info(snapshot_dir: Path, manifest: Mapping[str, Any]) -> HarnessSnapshotInfo:
    files = manifest.get("files")
    if not isinstance(files, list):
        raise HarnessFilesError("snapshot manifest files must be a list")
    total = 0
    for item in files:
        if isinstance(item, Mapping) and isinstance(item.get("size"), int):
            total += int(item["size"])
    lock_sha = manifest.get("lock_sha256")
    return HarnessSnapshotInfo(
        snapshot_id=_validate_snapshot_id(manifest.get("id") or snapshot_dir.name),
        created_at=str(manifest.get("created_at") or ""),
        file_count=len(files),
        total_size=total,
        lock_sha256=str(lock_sha) if isinstance(lock_sha, str) else None,
        path=str(snapshot_dir),
    )


def list_harness_snapshots(root: Any) -> List[HarnessSnapshotInfo]:
    """列出可用 snapshot（新到旧）；损坏条目跳过。"""
    path = Path(root).expanduser()
    snapshots_dir = path / SNAPSHOTS_DIR_NAME
    if not snapshots_dir.exists():
        return []
    if snapshots_dir.is_symlink() or not snapshots_dir.is_dir():
        raise HarnessFilesError(f"snapshot directory is invalid: {snapshots_dir}")
    result: List[HarnessSnapshotInfo] = []
    for child in snapshots_dir.iterdir():
        if child.name.startswith(".") or child.is_symlink() or not child.is_dir():
            continue
        try:
            result.append(_snapshot_info(child, _read_snapshot_manifest(child)))
        except HarnessFilesError:
            continue
    result.sort(key=lambda item: (item.created_at, item.snapshot_id), reverse=True)
    return result


def _load_snapshot(
    snapshot_dir: Path,
) -> Tuple[HarnessSnapshotInfo, List[HarnessFileEntry], Dict[str, bytes], Optional[bytes]]:
    manifest = _read_snapshot_manifest(snapshot_dir)
    info = _snapshot_info(snapshot_dir, manifest)
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list) or len(raw_files) > MAX_HARNESS_FILES:
        raise HarnessFilesError("snapshot manifest files are invalid")
    entries: List[HarnessFileEntry] = []
    data: Dict[str, bytes] = {}
    issues: List[VerificationIssue] = []
    files_root = snapshot_dir / "files"
    if files_root.is_symlink() or not files_root.is_dir():
        raise HarnessFilesError("snapshot files directory is missing")
    total = 0
    for raw in raw_files:
        if not isinstance(raw, Mapping):
            raise HarnessFilesError("snapshot file entry must be an object")
        path_value = raw.get("path")
        entry_data = dict(raw)
        entry_data.pop("path", None)
        entry = _parse_lock_entry(path_value, entry_data, issues)
        if entry is None:
            _raise_for_issues(issues)
        assert entry is not None
        target = _safe_target(files_root, entry.path)
        if not target.is_file():
            raise HarnessFilesError(f"snapshot file is missing: {entry.path}")
        payload = target.read_bytes()
        total += len(payload)
        if len(payload) != entry.size or hashlib.sha256(payload).hexdigest() != entry.sha256:
            raise HarnessFilesError(f"snapshot file hash mismatch: {entry.path}")
        entries.append(entry)
        data[entry.path] = payload
    if total > MAX_HARNESS_TOTAL_BYTES:
        raise HarnessFilesError("snapshot exceeds total size limit")
    lock_bytes: Optional[bytes] = None
    lock_sha = manifest.get("lock_sha256")
    lock_path = snapshot_dir / HARNESS_LOCK_FILE_NAME
    if lock_sha is not None:
        if lock_path.is_symlink() or not lock_path.is_file():
            raise HarnessFilesError("snapshot lock is missing")
        lock_bytes = lock_path.read_bytes()
        if hashlib.sha256(lock_bytes).hexdigest() != lock_sha:
            raise HarnessFilesError("snapshot lock hash mismatch")
    return info, entries, data, lock_bytes


def _resolve_snapshot(root: Path, snapshot_id: Optional[str]) -> Path:
    if snapshot_id:
        return root / SNAPSHOTS_DIR_NAME / _validate_snapshot_id(snapshot_id)
    snapshots = list_harness_snapshots(root)
    if not snapshots:
        raise HarnessFilesError("no harness snapshot is available")
    return Path(snapshots[0].path)


def create_harness_snapshot(
    root: Any,
    snapshot_id: Optional[str] = None,
    *,
    created_at: Optional[Any] = None,
) -> HarnessSnapshotInfo:
    """为当前托管文件集创建一个经哈希校验的目录 snapshot。"""
    path = _prepare_root(root)
    if not path.exists():
        raise HarnessFilesError(f"harness root does not exist: {path}")
    files, issues = _scan_files(path)
    _raise_for_issues(issues)
    if not files:
        raise HarnessFilesError("cannot snapshot an empty harness file set")
    selected_id = _validate_snapshot_id(snapshot_id) if snapshot_id else _new_snapshot_id()
    snapshots_dir = path / SNAPSHOTS_DIR_NAME
    if snapshots_dir.is_symlink():
        raise HarnessFilesError("snapshot directory must not be a symlink")
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    target = snapshots_dir / selected_id
    if target.exists() or target.is_symlink():
        raise HarnessFilesError(f"snapshot already exists: {selected_id}")

    old_lock, _issues, adopted, _enforced = _load_lock(path)
    entries = _entries_from_files(files, old_lock.by_path if old_lock else {})
    lock_bytes: Optional[bytes] = None
    lock_path = path / HARNESS_LOCK_FILE_NAME
    if adopted and lock_path.is_file() and not lock_path.is_symlink():
        lock_bytes = lock_path.read_bytes()

    staging = snapshots_dir / f".staging-{selected_id}-{uuid.uuid4().hex[:8]}"
    try:
        (staging / "files").mkdir(parents=True, exist_ok=False)
        for rel in sorted(files):
            _atomic_write(staging / "files", rel, files[rel].read_bytes())
        if lock_bytes is not None:
            _atomic_write(staging, HARNESS_LOCK_FILE_NAME, lock_bytes)
        manifest = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "kind": SNAPSHOT_KIND,
            "id": selected_id,
            "created_at": _format_time(created_at),
            "lock_sha256": hashlib.sha256(lock_bytes).hexdigest() if lock_bytes else None,
            "files": [
                {"path": entry.path, **entry.to_dict()}
                for entry in sorted(entries, key=lambda item: item.path)
            ],
        }
        _atomic_write(
            staging,
            SNAPSHOT_MANIFEST_NAME,
            (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
        _load_snapshot(staging)
        staging.replace(target)
    except BaseException:
        if staging.exists():
            shutil.rmtree(str(staging), ignore_errors=True)
        raise
    return _snapshot_info(target, _read_snapshot_manifest(target))



def write_harness_files(
    root: Any,
    specs: Sequence[HarnessFileSpec],
    *,
    force: bool = False,
    create_snapshot: bool = True,
    generated_at: Optional[Any] = None,
    generator: str = "backend.cli.harness files export",
    startup_enforced: bool = True,
) -> Dict[str, Any]:
    """物化 specs、刷新 lock，并按需创建前后 snapshot。"""
    path = _prepare_root(root, create=True)
    existing, issues = _scan_files(path)
    _raise_for_issues(issues)
    pre_snapshot: Optional[HarnessSnapshotInfo] = None
    if existing and force and create_snapshot:
        pre_snapshot = create_harness_snapshot(
            path, _new_snapshot_id("pre-export"), created_at=generated_at
        )
    path, spec_map, lock = write_harness_file_specs(
        path,
        specs,
        force=force,
        generated_at=generated_at,
        generator=generator,
        startup_enforced=startup_enforced,
    )
    snapshot: Optional[HarnessSnapshotInfo] = None
    if create_snapshot:
        snapshot_id = "initial" if not list_harness_snapshots(path) else _new_snapshot_id("export")
        snapshot = create_harness_snapshot(path, snapshot_id, created_at=generated_at)
    return {
        "root": str(path),
        "file_count": len(spec_map),
        "lock": lock.to_dict(),
        "pre_snapshot": pre_snapshot.to_dict() if pre_snapshot else None,
        "snapshot": snapshot.to_dict() if snapshot else None,
    }


def _decode_text(data: Optional[bytes]) -> Optional[str]:
    if data is None:
        return ""
    if len(data) > MAX_DIFF_TEXT_BYTES:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def harness_diff_view(
    root: Any,
    snapshot_id: Optional[str] = None,
    *,
    include_patch: bool = False,
    max_patch_chars: int = 20000,
) -> Dict[str, Any]:
    """构造当前文件集相对 snapshot 的差异视图。"""
    path = _prepare_root(root)
    if not path.exists():
        raise HarnessFilesError(f"harness root does not exist: {path}")
    snapshot_dir = _resolve_snapshot(path, snapshot_id)
    info, before_entries, before_data, _lock = _load_snapshot(snapshot_dir)
    files, issues = _scan_files(path)
    _raise_for_issues(issues)
    after_data = {rel: files[rel].read_bytes() for rel in sorted(files)}
    before_by_path = {entry.path: entry for entry in before_entries}
    after_entries = {
        rel: HarnessFileEntry(
            path=rel,
            sha256=hashlib.sha256(data).hexdigest(),
            size=len(data),
            component=infer_harness_component(rel),
        )
        for rel, data in after_data.items()
    }
    counts = {"added": 0, "modified": 0, "deleted": 0, "unchanged": 0}
    entries: List[HarnessDiffEntry] = []
    for rel in sorted(set(before_data) | set(after_data)):
        before = before_data.get(rel)
        after = after_data.get(rel)
        if before == after:
            counts["unchanged"] += 1
            continue
        status = "added" if before is None else "deleted" if after is None else "modified"
        counts[status] += 1
        patch: Optional[str] = None
        if include_patch:
            before_text = _decode_text(before)
            after_text = _decode_text(after)
            if before_text is not None and after_text is not None:
                patch = "".join(
                    difflib.unified_diff(
                        before_text.splitlines(keepends=True),
                        after_text.splitlines(keepends=True),
                        fromfile=f"a/{rel}",
                        tofile=f"b/{rel}",
                    )
                )
                if len(patch) > max_patch_chars:
                    patch = patch[:max_patch_chars] + "\n... (truncated)\n"
        entries.append(
            HarnessDiffEntry(
                path=rel,
                status=status,
                component=infer_harness_component(rel),
                before_sha256=before_by_path[rel].sha256 if rel in before_by_path else None,
                after_sha256=after_entries[rel].sha256 if rel in after_entries else None,
                before_size=len(before) if before is not None else None,
                after_size=len(after) if after is not None else None,
                patch=patch,
            )
        )
    return {
        "root": str(path),
        "snapshot": info.to_dict(),
        "counts": counts,
        "entries": [entry.to_dict() for entry in entries],
    }



def rollback_harness_files(
    root: Any,
    snapshot_id: Optional[str] = None,
    *,
    create_pre_snapshot: bool = True,
) -> Dict[str, Any]:
    """把托管文件集恢复到指定 snapshot（默认最新）。"""
    path = _prepare_root(root)
    if not path.exists():
        raise HarnessFilesError(f"harness root does not exist: {path}")
    snapshot_dir = _resolve_snapshot(path, snapshot_id)
    info, entries, data, lock_bytes = _load_snapshot(snapshot_dir)
    current, issues = _scan_files(path)
    _raise_for_issues(issues)
    pre_snapshot: Optional[HarnessSnapshotInfo] = None
    if current and create_pre_snapshot:
        pre_snapshot = create_harness_snapshot(path, _new_snapshot_id("pre-rollback"))

    for rel in sorted(current):
        _delete_file(path, rel)
    for rel in sorted(data):
        _atomic_write(path, rel, data[rel])
    if lock_bytes is not None:
        _atomic_write(path, HARNESS_LOCK_FILE_NAME, lock_bytes)
    else:
        _write_lock(
            path,
            _build_lock(entries, generated_at=info.created_at, generator="harness rollback"),
        )
    verification = verify_harness_files(path)
    if not verification.valid:
        _raise_for_issues(verification.issues)
    return {
        "root": str(path),
        "snapshot": info.to_dict(),
        "pre_snapshot": pre_snapshot.to_dict() if pre_snapshot else None,
        "restored_files": len(data),
    }



def harness_status_view(root: Any) -> Dict[str, Any]:
    """构造 lock 状态 + snapshot 摘要视图。"""
    path = Path(root).expanduser()
    verification = verify_harness_files(path)
    lock_by_path = verification.lock.by_path if verification.lock else {}
    file_rows: List[Dict[str, Any]] = []
    for entry in verification.current_files:
        expected = lock_by_path.get(entry.path)
        status = "added"
        if expected is not None:
            status = "unchanged" if expected.sha256 == entry.sha256 and expected.size == entry.size else "modified"
        file_rows.append(
            {
                "path": entry.path,
                "status": status,
                "sha256": entry.sha256,
                "size": entry.size,
                "component": entry.component,
                "provenance": entry.provenance,
                "owner": entry.owner,
                "authority": entry.authority,
            }
        )
    missing = [
        entry.path for entry in (verification.lock.files if verification.lock else ())
        if entry.path not in {item.path for item in verification.current_files}
    ]
    try:
        snapshots = list_harness_snapshots(path)
    except HarnessFilesError:
        snapshots = []
    return {
        "root": str(path),
        "exists": verification.exists,
        "adopted": verification.adopted,
        "valid": verification.valid,
        "enforced": verification.enforced,
        "counts": dict(verification.counts),
        "issues": [issue.to_dict() for issue in verification.issues],
        "lock": verification.lock.to_dict() if verification.lock else None,
        "files": file_rows,
        "missing_files": missing,
        "snapshots": [snapshot.to_dict() for snapshot in snapshots],
    }


