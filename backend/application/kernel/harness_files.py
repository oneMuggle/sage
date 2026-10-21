# ruff: noqa: UP006, UP007, UP017, UP035
"""Fileized harness 的 lock、快照、diff 与回滚机制（R84）。

本模块只处理一个小型文本文件集，不认识 prompt、tools 或 skills 的具体
来源。组合层把各行为面渲染为 :class:`HarnessFileSpec` 后交给这里写盘；
``harness.lock.json`` 以 SHA-256 钉住每份托管文件，snapshot 则保存可
逐文件 diff / 回滚的内容副本。

安全口径：

- 所有路径必须是根内 POSIX 相对路径，拒绝 ``..``、盘符与符号链接；
- 单文件 / 总量 / 文件数均有硬上限，超限明确失败，不静默截断；
- 单文件写入走同目录临时文件 + ``os.replace``；
- lock 只提供漂移可见性，不是签名或信任链。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import stat
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from backend.application.kernel.harness_config import (
    HARNESS_LOCK_FILE_NAME,
    harness_files_dirs,
)

logger = logging.getLogger(__name__)

LOCK_SCHEMA_VERSION = 1
LOCK_KIND = "sage-harness-lock"
SNAPSHOTS_DIR_NAME = ".snapshots"
LOCK_ENFORCE_ENV = "SAGE_HARNESS_LOCK_ENFORCE"
MAX_HARNESS_FILES = 2000
MAX_HARNESS_FILE_BYTES = 2 * 1024 * 1024
MAX_HARNESS_TOTAL_BYTES = 32 * 1024 * 1024
MAX_DIFF_TEXT_BYTES = 256 * 1024

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SNAPSHOT_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")

__all__ = [
    "LOCK_ENFORCE_ENV",
    "LOCK_KIND",
    "LOCK_SCHEMA_VERSION",
    "MAX_HARNESS_FILES",
    "MAX_HARNESS_FILE_BYTES",
    "MAX_HARNESS_TOTAL_BYTES",
    "SNAPSHOTS_DIR_NAME",
    "HarnessFileEntry",
    "HarnessFileSpec",
    "HarnessFilesError",
    "HarnessLock",
    "HarnessVerification",
    "VerificationIssue",
    "assert_adopted_harness_files_valid",
    "harness_lock_enforcement_enabled",
    "infer_harness_component",
    "load_harness_lock",
    "normalize_harness_path",
    "update_harness_lock",
    "verify_harness_files",
    "write_harness_file_specs",
]


class HarnessFilesError(ValueError):
    """harness 文件集、lock 或 snapshot 非法。"""


@dataclass(frozen=True)
class HarnessFileSpec:
    """一份待物化的托管文件。"""

    path: str
    content: Union[str, bytes]
    component: str = ""
    provenance: str = "local"
    owner: str = "local"
    authority: str = "projection"

    @property
    def data(self) -> bytes:
        if isinstance(self.content, bytes):
            return self.content
        return str(self.content).encode("utf-8")

    @property
    def normalized_path(self) -> str:
        return normalize_harness_path(self.path)

    def entry(self) -> HarnessFileEntry:
        path = self.normalized_path
        data = self.data
        return HarnessFileEntry(
            path=path,
            sha256=hashlib.sha256(data).hexdigest(),
            size=len(data),
            component=self.component or infer_harness_component(path),
            provenance=self.provenance or "local",
            owner=self.owner or "local",
            authority=self.authority or "projection",
        )


@dataclass(frozen=True)
class HarnessFileEntry:
    """lock / snapshot 中的单文件清单项。"""

    path: str
    sha256: str
    size: int
    component: str = ""
    provenance: str = "local"
    owner: str = "local"
    authority: str = "projection"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sha256": self.sha256,
            "size": self.size,
            "component": self.component or infer_harness_component(self.path),
            "provenance": self.provenance,
            "owner": self.owner,
            "authority": self.authority,
        }


@dataclass(frozen=True)
class HarnessLock:
    """已解析的 ``harness.lock.json``。"""

    generated_at: str
    content_sha256: str
    files: Tuple[HarnessFileEntry, ...]
    generator: str = "backend.cli.harness"
    startup_enforced: bool = True
    schema_version: int = LOCK_SCHEMA_VERSION

    @property
    def by_path(self) -> Dict[str, HarnessFileEntry]:
        return {entry.path: entry for entry in self.files}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": LOCK_KIND,
            "generated_at": self.generated_at,
            "generator": self.generator,
            "startup_enforced": self.startup_enforced,
            "file_count": len(self.files),
            "content_sha256": self.content_sha256,
            "files": {entry.path: entry.to_dict() for entry in self.files},
        }


@dataclass(frozen=True)
class VerificationIssue:
    code: str
    path: str
    message: str

    def to_dict(self) -> Dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


@dataclass(frozen=True)
class HarnessVerification:
    root: str
    exists: bool
    adopted: bool
    valid: bool
    enforced: bool
    issues: Tuple[VerificationIssue, ...]
    counts: Dict[str, int]
    current_files: Tuple[HarnessFileEntry, ...] = ()
    lock: Optional[HarnessLock] = None


def _format_time(value: Optional[Any]) -> str:
    if value is None:
        moment = datetime.now(timezone.utc)
    elif isinstance(value, str):
        return value
    elif isinstance(value, datetime):
        moment = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    else:
        raise HarnessFilesError("harness timestamp must be a datetime or ISO string")
    return moment.astimezone(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def normalize_harness_path(value: Any) -> str:
    """把托管路径规范化为安全的 POSIX 相对路径。"""
    raw = str(value or "").replace("\\", "/").strip()
    if not raw or raw.startswith("/") or _DRIVE_RE.match(raw):
        raise HarnessFilesError(f"unsafe harness path: {value!r}")
    parts = raw.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise HarnessFilesError(f"unsafe harness path: {value!r}")
    return "/".join(parts)


def infer_harness_component(path: str) -> str:
    normalized = normalize_harness_path(path)
    first = normalized.split("/", 1)[0]
    mapping = {
        "system.md": "system",
        "guardrails.yaml": "guardrails",
        "memory.yaml": "memory",
        "tool-guidance.yaml": "tool-guidance",
        "plugins.yaml": "plugins",
        "subagents": "subagents",
        "skills": "skills",
        "scripts": "scripts",
        "proposals": "proposals",
        "evidence": "evidence",
        ".gitignore": "meta",
    }
    return mapping.get(first, first.rsplit(".", 1)[0] if "." in first else first)


def _is_managed_path(path: str) -> bool:
    if path == HARNESS_LOCK_FILE_NAME:
        return False
    parts = path.split("/")
    if parts[0] == SNAPSHOTS_DIR_NAME or "__pycache__" in parts:
        return False
    if parts[0] in ("proposals", "evidence"):
        return path in ("proposals/README.md", "evidence/README.md")
    return True


def _validate_managed_path(path: str) -> str:
    normalized = normalize_harness_path(path)
    if not _is_managed_path(normalized):
        raise HarnessFilesError(f"path is not a managed harness file: {path!r}")
    return normalized


def _prepare_root(root: Any, *, create: bool = False) -> Path:
    path = Path(root).expanduser()
    if path.is_symlink():
        raise HarnessFilesError(f"harness root must not be a symlink: {path}")
    if create:
        path.mkdir(parents=True, exist_ok=True)
    if path.exists() and not path.is_dir():
        raise HarnessFilesError(f"harness root is not a directory: {path}")
    if path.is_symlink():
        raise HarnessFilesError(f"harness root must not be a symlink: {path}")
    return path


def _safe_target(root: Path, relative: str) -> Path:
    normalized = normalize_harness_path(relative)
    current = root
    parts = normalized.split("/")
    for part in parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise HarnessFilesError(f"harness path crosses a symlink: {relative}")
        if current.exists() and not current.is_dir():
            raise HarnessFilesError(f"harness path parent is not a directory: {relative}")
    target = root.joinpath(*parts)
    if target.is_symlink():
        raise HarnessFilesError(f"harness file must not be a symlink: {relative}")
    return target


def _atomic_write(root: Path, relative: str, data: bytes) -> bool:
    target = _safe_target(root, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target = _safe_target(root, relative)
    if target.exists():
        if not target.is_file():
            raise HarnessFilesError(f"harness target is not a file: {relative}")
        if target.read_bytes() == data:
            return False
    temp = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex[:10]}"
    try:
        with open(temp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temp.replace(target)
    finally:
        try:
            if temp.exists():
                temp.unlink()
        except OSError:
            logger.warning("failed to remove harness temp file: %s", temp)
    return True


def _delete_file(root: Path, relative: str) -> None:
    target = _safe_target(root, relative)
    if target.exists():
        if not target.is_file():
            raise HarnessFilesError(f"harness target is not a file: {relative}")
        target.unlink()
    parent = target.parent
    while parent != root:
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent


def _scan_files(
    root: Path,
) -> Tuple[Dict[str, Path], List[VerificationIssue]]:
    files: Dict[str, Path] = {}
    issues: List[VerificationIssue] = []
    if not root.exists():
        return files, issues
    if root.is_symlink():
        return files, [
            VerificationIssue("symlink_rejected", "", "harness root is a symlink")
        ]
    if not root.is_dir():
        return files, [
            VerificationIssue("invalid_root", "", "harness root is not a directory")
        ]

    total_size = 0
    for current_text, dir_names, file_names in os.walk(str(root)):
        current = Path(current_text)
        rel_dir = "" if current == root else current.relative_to(root).as_posix()
        kept_dirs: List[str] = []
        for dirname in sorted(dir_names):
            rel = f"{rel_dir}/{dirname}" if rel_dir else dirname
            child = current / dirname
            if rel == SNAPSHOTS_DIR_NAME or dirname == "__pycache__":
                continue
            if rel_dir in ("proposals", "evidence"):
                continue
            if child.is_symlink():
                issues.append(
                    VerificationIssue("symlink_rejected", rel, "directory is a symlink")
                )
                continue
            kept_dirs.append(dirname)
        dir_names[:] = kept_dirs

        for filename in sorted(file_names):
            rel = f"{rel_dir}/{filename}" if rel_dir else filename
            if not _is_managed_path(rel):
                continue
            path = current / filename
            if path.is_symlink():
                issues.append(
                    VerificationIssue("symlink_rejected", rel, "file is a symlink")
                )
                continue
            try:
                mode = os.lstat(str(path)).st_mode
                size = os.lstat(str(path)).st_size
            except OSError as exc:
                issues.append(VerificationIssue("unreadable_file", rel, str(exc)))
                continue
            if not stat.S_ISREG(mode):
                issues.append(
                    VerificationIssue("unsupported_file_type", rel, "not a regular file")
                )
                continue
            files[rel] = path
            total_size += size
            if size > MAX_HARNESS_FILE_BYTES:
                issues.append(
                    VerificationIssue("file_too_large", rel, "file exceeds 2 MiB limit")
                )
    if len(files) > MAX_HARNESS_FILES:
        issues.append(
            VerificationIssue("too_many_files", "", "managed file count exceeds limit")
        )
    if total_size > MAX_HARNESS_TOTAL_BYTES:
        issues.append(
            VerificationIssue("total_too_large", "", "managed files exceed 32 MiB limit")
        )
    return files, issues


def _raise_for_issues(issues: Sequence[VerificationIssue]) -> None:
    if issues:
        issue = issues[0]
        suffix = f" ({issue.path})" if issue.path else ""
        raise HarnessFilesError(f"{issue.code}{suffix}: {issue.message}")


def _hash_file(path: Path) -> Tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_HARNESS_FILE_BYTES:
                break
            digest.update(chunk)
    return digest.hexdigest(), size


def _entries_from_files(
    files: Mapping[str, Path],
    metadata: Optional[Mapping[str, HarnessFileEntry]] = None,
) -> List[HarnessFileEntry]:
    metadata = metadata or {}
    entries: List[HarnessFileEntry] = []
    for rel in sorted(files):
        path = files[rel]
        if path.stat().st_size > MAX_HARNESS_FILE_BYTES:
            continue
        sha256, size = _hash_file(path)
        old = metadata.get(rel)
        entries.append(
            HarnessFileEntry(
                path=rel,
                sha256=sha256,
                size=size,
                component=old.component if old else infer_harness_component(rel),
                provenance=old.provenance if old else "local",
                owner=old.owner if old else "local",
                authority=old.authority if old else "projection",
            )
        )
    return entries


def _content_sha(entries: Sequence[HarnessFileEntry]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: item.path):
        digest.update(entry.path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(entry.sha256.encode("ascii"))
        digest.update(b"\0")
        digest.update(str(entry.size).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _build_lock(
    entries: Sequence[HarnessFileEntry],
    *,
    generated_at: Optional[Any] = None,
    generator: str = "backend.cli.harness",
    startup_enforced: bool = True,
) -> HarnessLock:
    ordered = tuple(sorted(entries, key=lambda item: item.path))
    return HarnessLock(
        generated_at=_format_time(generated_at),
        generator=generator,
        startup_enforced=bool(startup_enforced),
        content_sha256=_content_sha(ordered),
        files=ordered,
    )


def _write_lock(root: Path, lock: HarnessLock) -> None:
    payload = json.dumps(lock.to_dict(), ensure_ascii=False, indent=2) + "\n"
    _atomic_write(root, HARNESS_LOCK_FILE_NAME, payload.encode("utf-8"))


def _parse_lock_entry(
    path_value: Any,
    raw: Any,
    issues: List[VerificationIssue],
) -> Optional[HarnessFileEntry]:
    try:
        path = _validate_managed_path(str(path_value))
    except HarnessFilesError as exc:
        issues.append(VerificationIssue("invalid_lock", str(path_value), str(exc)))
        return None
    if not isinstance(raw, Mapping):
        issues.append(VerificationIssue("invalid_lock", path, "entry must be an object"))
        return None
    sha256 = raw.get("sha256")
    size = raw.get("size")
    if not isinstance(sha256, str) or not _SHA256_RE.match(sha256):
        issues.append(VerificationIssue("invalid_lock", path, "sha256 is invalid"))
        return None
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        issues.append(VerificationIssue("invalid_lock", path, "size is invalid"))
        return None
    return HarnessFileEntry(
        path=path,
        sha256=sha256,
        size=size,
        component=str(raw.get("component") or infer_harness_component(path)),
        provenance=str(raw.get("provenance") or "local"),
        owner=str(raw.get("owner") or "local"),
        authority=str(raw.get("authority") or "projection"),
    )


def _load_lock(
    root: Path,
) -> Tuple[Optional[HarnessLock], List[VerificationIssue], bool, bool]:
    """Return (lock, issues, adopted, enforced)."""
    lock_path = root / HARNESS_LOCK_FILE_NAME
    if not lock_path.exists() and not lock_path.is_symlink():
        return None, [VerificationIssue("missing_lock", "", "harness.lock.json is missing")], False, False
    if lock_path.is_symlink():
        return None, [VerificationIssue("symlink_rejected", HARNESS_LOCK_FILE_NAME, "lock is a symlink")], True, True
    try:
        raw = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, [VerificationIssue("invalid_lock", HARNESS_LOCK_FILE_NAME, str(exc))], True, True
    if not isinstance(raw, Mapping):
        return None, [VerificationIssue("invalid_lock", HARNESS_LOCK_FILE_NAME, "lock must be an object")], True, True

    enforced_raw = raw.get("startup_enforced", True)
    enforced = enforced_raw if isinstance(enforced_raw, bool) else True
    issues: List[VerificationIssue] = []
    if raw.get("schema_version") != LOCK_SCHEMA_VERSION:
        issues.append(
            VerificationIssue("unsupported_lock_version", HARNESS_LOCK_FILE_NAME, "unsupported schema_version")
        )
    if raw.get("kind") not in (None, LOCK_KIND):
        issues.append(VerificationIssue("invalid_lock", HARNESS_LOCK_FILE_NAME, "unexpected lock kind"))
    if not isinstance(enforced_raw, bool):
        issues.append(
            VerificationIssue("invalid_lock", HARNESS_LOCK_FILE_NAME, "startup_enforced must be boolean")
        )
    files_raw = raw.get("files")
    entries: List[HarnessFileEntry] = []
    if not isinstance(files_raw, Mapping):
        issues.append(VerificationIssue("invalid_lock", HARNESS_LOCK_FILE_NAME, "files must be an object"))
    else:
        seen = set()
        for path_value, entry_raw in files_raw.items():
            entry = _parse_lock_entry(path_value, entry_raw, issues)
            if entry is None:
                continue
            if entry.path in seen:
                issues.append(VerificationIssue("invalid_lock", entry.path, "duplicate path"))
                continue
            seen.add(entry.path)
            entries.append(entry)
    file_count = raw.get("file_count")
    if file_count is not None and file_count != len(entries):
        issues.append(VerificationIssue("invalid_lock", HARNESS_LOCK_FILE_NAME, "file_count mismatch"))
    content_sha = raw.get("content_sha256")
    expected_content_sha = _content_sha(entries)
    if not isinstance(content_sha, str) or not _SHA256_RE.match(content_sha):
        issues.append(VerificationIssue("invalid_lock", HARNESS_LOCK_FILE_NAME, "content_sha256 is invalid"))
    elif content_sha != expected_content_sha:
        issues.append(
            VerificationIssue("lock_content_hash_mismatch", HARNESS_LOCK_FILE_NAME, "lock content digest mismatch")
        )
    if issues:
        return None, issues, True, enforced
    lock = HarnessLock(
        generated_at=str(raw.get("generated_at") or ""),
        generator=str(raw.get("generator") or "backend.cli.harness"),
        startup_enforced=enforced,
        content_sha256=expected_content_sha,
        files=tuple(sorted(entries, key=lambda item: item.path)),
        schema_version=LOCK_SCHEMA_VERSION,
    )
    return lock, [], True, enforced


def _lenient_lock_metadata(root: Path) -> Dict[str, HarnessFileEntry]:
    """从可能已损坏的 lock 中尽量恢复条目元数据（供 update-lock）。"""
    lock_path = root / HARNESS_LOCK_FILE_NAME
    if lock_path.is_symlink() or not lock_path.is_file():
        return {}
    try:
        raw = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return {}
    if not isinstance(raw, Mapping) or not isinstance(raw.get("files"), Mapping):
        return {}
    issues: List[VerificationIssue] = []
    entries: Dict[str, HarnessFileEntry] = {}
    for path_value, entry_raw in raw["files"].items():
        entry = _parse_lock_entry(path_value, entry_raw, issues)
        if entry is not None:
            entries[entry.path] = entry
    return entries


def load_harness_lock(root: Any) -> Optional[HarnessLock]:
    """加载 lock；不存在返回 None，非法抛 HarnessFilesError。"""
    path = Path(root).expanduser()
    lock, issues, adopted, _enforced = _load_lock(path)
    if not adopted:
        return None
    _raise_for_issues(issues)
    return lock


def verify_harness_files(root: Any) -> HarnessVerification:
    """校验一个 harness 根目录并返回结构化结果。"""
    path = Path(root).expanduser()
    exists = path.exists()
    counts = {"unchanged": 0, "modified": 0, "missing": 0, "added": 0}
    if not exists:
        return HarnessVerification(str(path), False, False, True, False, (), counts)
    files, issues = _scan_files(path)
    lock, lock_issues, adopted, enforced = _load_lock(path)
    issues.extend(lock_issues)
    metadata = lock.by_path if lock else {}
    current = tuple(_entries_from_files(files, metadata))
    current_by_path = {entry.path: entry for entry in current}
    if lock is not None:
        for expected in lock.files:
            actual = current_by_path.get(expected.path)
            if actual is None:
                counts["missing"] += 1
                issues.append(
                    VerificationIssue("missing_file", expected.path, "locked file is missing")
                )
            elif actual.size != expected.size:
                counts["modified"] += 1
                issues.append(
                    VerificationIssue("size_mismatch", expected.path, "file size differs from lock")
                )
            elif actual.sha256 != expected.sha256:
                counts["modified"] += 1
                issues.append(
                    VerificationIssue("hash_mismatch", expected.path, "file hash differs from lock")
                )
            else:
                counts["unchanged"] += 1
        for entry in current:
            if entry.path not in lock.by_path:
                counts["added"] += 1
                issues.append(
                    VerificationIssue("untracked_file", entry.path, "file is not present in lock")
                )
    else:
        counts["added"] = len(current)
    valid = bool(adopted and lock is not None and not issues)
    return HarnessVerification(
        root=str(path),
        exists=True,
        adopted=adopted,
        valid=valid,
        enforced=enforced,
        issues=tuple(issues),
        counts=counts,
        current_files=current,
        lock=lock,
    )


def update_harness_lock(
    root: Any,
    *,
    generated_at: Optional[Any] = None,
    generator: str = "backend.cli.harness files update-lock",
    startup_enforced: Optional[bool] = None,
) -> HarnessLock:
    """按当前托管文件重建 lock，尽量保留旧 lock 的元数据。"""
    path = _prepare_root(root)
    if not path.exists():
        raise HarnessFilesError(f"harness root does not exist: {path}")
    files, issues = _scan_files(path)
    _raise_for_issues(issues)
    old_lock, _old_issues, adopted, old_enforced = _load_lock(path)
    metadata = old_lock.by_path if old_lock else _lenient_lock_metadata(path)
    entries = _entries_from_files(files, metadata)
    lock = _build_lock(
        entries,
        generated_at=generated_at,
        generator=generator,
        startup_enforced=old_enforced if startup_enforced is None and adopted else bool(startup_enforced)
        if startup_enforced is not None
        else True,
    )
    _write_lock(path, lock)
    return lock


def write_harness_file_specs(
    root: Any,
    specs: Sequence[HarnessFileSpec],
    *,
    force: bool = False,
    generated_at: Optional[Any] = None,
    generator: str = "backend.cli.harness files export",
    startup_enforced: bool = True,
) -> Tuple[Path, Dict[str, HarnessFileSpec], HarnessLock]:
    """把 specs 写成文件集并刷新 lock（不创建 snapshot）。"""
    path = _prepare_root(root, create=True)
    spec_map: Dict[str, HarnessFileSpec] = {}
    total = 0
    for spec in specs:
        rel = _validate_managed_path(spec.path)
        if rel in spec_map:
            raise HarnessFilesError(f"duplicate harness file spec: {rel}")
        data = spec.data
        if len(data) > MAX_HARNESS_FILE_BYTES:
            raise HarnessFilesError(f"harness file exceeds size limit: {rel}")
        total += len(data)
        spec_map[rel] = spec
    if not spec_map or len(spec_map) > MAX_HARNESS_FILES or total > MAX_HARNESS_TOTAL_BYTES:
        raise HarnessFilesError("harness file set is empty or exceeds size limits")
    existing, issues = _scan_files(path)
    _raise_for_issues(issues)
    if existing and not force:
        raise HarnessFilesError(
            f"harness root already contains managed files: {path} (use --force)"
        )
    for rel in sorted(existing):
        if rel not in spec_map:
            _delete_file(path, rel)
    for rel in sorted(spec_map):
        _atomic_write(path, rel, spec_map[rel].data)
    lock = _build_lock(
        [spec_map[rel].entry() for rel in sorted(spec_map)],
        generated_at=generated_at,
        generator=generator,
        startup_enforced=startup_enforced,
    )
    _write_lock(path, lock)
    verification = verify_harness_files(path)
    if not verification.valid:
        _raise_for_issues(verification.issues)
    return path, spec_map, lock


def harness_lock_enforcement_enabled(
    environ: Optional[Mapping[str, str]] = None,
) -> bool:
    env = os.environ if environ is None else environ
    return str(env.get(LOCK_ENFORCE_ENV, "")).strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def assert_adopted_harness_files_valid(
    *,
    workspace: Optional[Any] = None,
    user_home: Optional[Any] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> List[HarnessVerification]:
    """校验所有已采用的 user/project harness；无 lock 时 no-op。"""
    if not harness_lock_enforcement_enabled(environ):
        logger.warning("harness lock startup enforcement disabled by %s", LOCK_ENFORCE_ENV)
        return []
    results: List[HarnessVerification] = []
    failures: List[str] = []
    for root in harness_files_dirs(
        workspace=workspace, user_home=user_home, environ=environ
    ):
        if not (root / HARNESS_LOCK_FILE_NAME).exists():
            continue
        verification = verify_harness_files(root)
        results.append(verification)
        if verification.enforced and not verification.valid:
            details = "; ".join(
                f"{issue.code}:{issue.path}" if issue.path else issue.code
                for issue in verification.issues[:3]
            )
            failures.append(f"{root} ({details})")
    if failures:
        raise HarnessFilesError(
            "harness lock verification failed; refusing to start: " + "; ".join(failures)
        )
    return results
