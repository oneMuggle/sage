"""Install, remove and scan signed offline component packages."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
import time
from contextlib import contextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Mapping, Optional, Sequence, Set, Tuple

from .archive import ProgressCallback, read_component_json, read_signature, stage_payload
from .crypto import require_public_key, verify_signature
from .errors import ComponentError
from .models import (
    ComponentFile,
    ComponentManifest,
    InstalledComponent,
    PackageScanResult,
    installed_manifest_path,
    parse_installed_metadata,
    resolve_installed_paths,
)

LOCK_STALE_SECONDS = 600
_SCHEMA_VERSION = 1


def _now_iso() -> str:
    # timezone.utc keeps py3.8 support (datetime.UTC is 3.11+).
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")  # noqa: UP017


def _normalise_arch(value: str) -> str:
    lowered = value.strip().lower()
    if lowered in ("amd64", "x86_64", "x64"):
        return "x64"
    if lowered in ("aarch64", "arm64"):
        return "arm64"
    return lowered


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_user_data_dir(env: Mapping[str, str]) -> Path:
    from backend.services.rescue.paths import resolve_user_data_dir

    return resolve_user_data_dir(env)


def _resolve_resources_dir(env: Mapping[str, str]) -> Path:
    explicit = str(env.get("SAGE_RESOURCES_DIR", "")).strip()
    if explicit:
        return Path(explicit)
    if env.get("SAGE_IS_PACKAGED") == "1":
        return Path(sys.executable).resolve().parent.parent
    # repo/backend/services/components/service.py -> repo/resources
    return Path(__file__).resolve().parents[3] / "resources"


class ComponentService:
    """Single source of truth for component verification and installation."""

    def __init__(
        self,
        *,
        user_data_dir: Path,
        resources_dir: Optional[Path] = None,
        environ: Optional[Mapping[str, str]] = None,
        progress: ProgressCallback = None,
    ) -> None:
        self.user_data_dir = Path(user_data_dir)
        self.resources_dir = Path(resources_dir) if resources_dir is not None else None
        self.environ = dict(environ) if environ is not None else dict(os.environ)
        self._progress = progress

    @classmethod
    def from_environment(
        cls,
        *,
        environ: Optional[Mapping[str, str]] = None,
        progress: ProgressCallback = None,
    ) -> ComponentService:
        env = dict(environ) if environ is not None else dict(os.environ)
        return cls(
            user_data_dir=_resolve_user_data_dir(env),
            resources_dir=_resolve_resources_dir(env),
            environ=env,
            progress=progress,
        )

    # ── metadata ──────────────────────────────────────────────────────────

    def _metadata_path(self) -> Path:
        return installed_manifest_path(self.user_data_dir)

    def _read_metadata(self) -> Dict[str, InstalledComponent]:
        path = self._metadata_path()
        if not path.is_file():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return parse_installed_metadata(raw)

    def _write_metadata(self, components: Dict[str, InstalledComponent]) -> None:
        path = self._metadata_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schemaVersion": _SCHEMA_VERSION,
            "components": {key: value.to_dict() for key, value in components.items()},
        }
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp.replace(path)

    def list_installed(self) -> List[InstalledComponent]:
        metadata = self._read_metadata()
        return [metadata[key] for key in sorted(metadata)]

    # ── scan ──────────────────────────────────────────────────────────────

    def _default_scan_dirs(self) -> List[Path]:
        dirs: List[Path] = []
        if self.resources_dir is not None:
            dirs.append(self.resources_dir / "components")
        dirs.append(self.user_data_dir / "components" / "inbox")
        extra = self.environ.get("SAGE_COMPONENT_SCAN_DIRS", "")
        for part in extra.split(os.pathsep):
            if part.strip():
                dirs.append(Path(part.strip()))
        program_data = self.environ.get("ProgramData")
        if program_data:
            dirs.append(Path(program_data) / "Sage" / "components")
        return dirs

    def scan(self, dirs: Optional[Sequence[Path]] = None) -> List[PackageScanResult]:
        candidates = [Path(item) for item in dirs] if dirs else self._default_scan_dirs()
        results: List[PackageScanResult] = []
        seen: Set[Path] = set()
        for directory in candidates:
            if not directory.is_dir():
                continue
            try:
                entries = sorted(directory.glob("*.sagepkg"))
            except OSError:
                continue
            for package_path in entries:
                resolved = package_path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                results.append(self._scan_one(package_path))
        return results

    def _scan_one(self, package_path: Path) -> PackageScanResult:
        try:
            size = package_path.stat().st_size
            body = read_component_json(package_path)
            manifest = ComponentManifest.from_dict(json.loads(body.decode("utf-8")))
            return PackageScanResult(
                path=str(package_path),
                id=manifest.id,
                name=manifest.name,
                version=manifest.version,
                size=size,
            )
        except (ComponentError, ValueError, OSError, UnicodeDecodeError) as exc:
            return PackageScanResult(
                path=str(package_path),
                id="",
                name="",
                version="",
                size=0,
                error=str(exc),
            )

    # ── verification ──────────────────────────────────────────────────────

    def _load_manifest(self, package_path: Path) -> Tuple[ComponentManifest, bytes]:
        if not package_path.is_file():
            raise ComponentError(f"组件包不存在：{package_path}", code="package_missing")
        body = read_component_json(package_path)
        signature = read_signature(package_path)
        public_key = require_public_key(
            environ=self.environ,
            user_data_dir=self.user_data_dir,
            resources_dir=self.resources_dir,
        )
        if not verify_signature(public_key, body, signature):
            raise ComponentError("组件包签名无效", code="signature_invalid")
        try:
            manifest = ComponentManifest.from_dict(json.loads(body.decode("utf-8")))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ComponentError(f"组件包清单无效：{exc}", code="invalid_manifest") from exc
        self._check_compatibility(manifest)
        return manifest, body

    def _check_compatibility(self, manifest: ComponentManifest) -> None:
        expected_python = f"{sys.version_info.major}.{sys.version_info.minor}"
        if manifest.python and manifest.python != expected_python:
            raise ComponentError(
                f"组件包 Python 版本不匹配：需要 {manifest.python}，当前 {expected_python}",
                code="python_mismatch",
            )
        if manifest.arch and _normalise_arch(manifest.arch) != _normalise_arch(platform.machine()):
            raise ComponentError(
                f"组件包架构不匹配：需要 {manifest.arch}，当前 {platform.machine()}",
                code="arch_mismatch",
            )
        expected_branch = str(self.environ.get("SAGE_COMPONENT_BRANCH", "")).strip()
        if expected_branch and manifest.branch and manifest.branch != expected_branch:
            raise ComponentError(
                f"组件包分支不匹配：需要 {manifest.branch}，当前 {expected_branch}",
                code="branch_mismatch",
            )

    def verify_package(
        self,
        package_path: Path,
        *,
        full: bool = True,
        progress: ProgressCallback = None,
    ) -> ComponentManifest:
        manifest, _body = self._load_manifest(Path(package_path))
        if not full:
            return manifest
        staging_root = self.user_data_dir / "components" / ".staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f"verify-{manifest.id}-", dir=str(staging_root)))
        try:
            stage_payload(
                Path(package_path),
                manifest,
                staging,
                progress=progress or self._progress,
            )
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return manifest

    # ── install ───────────────────────────────────────────────────────────

    @contextmanager
    def _install_lock(self) -> Iterator[None]:
        lock_dir = self.user_data_dir / "components"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / ".install.lock"
        fd: Optional[int] = None
        for _attempt in range(2):
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    age = time.time() - lock_path.stat().st_mtime
                except OSError:
                    age = LOCK_STALE_SECONDS + 1
                if age > LOCK_STALE_SECONDS:
                    with suppress(OSError):
                        lock_path.unlink()
                    continue
                raise ComponentError(
                    "另一个组件安装正在进行，请稍后重试", code="install_locked"
                )
            try:
                os.write(fd, ("%d %s" % (os.getpid(), _now_iso())).encode("ascii"))
            except OSError:
                with suppress(OSError):
                    os.close(fd)
                with suppress(OSError):
                    lock_path.unlink()
                raise
            break
        if fd is None:
            raise ComponentError("无法获取组件安装锁", code="install_locked")
        try:
            yield
        finally:
            with suppress(OSError):
                os.close(fd)
            with suppress(OSError):
                lock_path.unlink()

    def _files_match(
        self,
        target: str,
        component_id: str,
        version: str,
        files: Tuple[ComponentFile, ...],
    ) -> bool:
        try:
            resolved = resolve_installed_paths(
                self.user_data_dir,
                target,
                component_id,
                version,
                files,
            )
        except ValueError:
            return False
        for item, destination in resolved:
            if not destination.is_file() or destination.stat().st_size != item.size:
                return False
            try:
                if _sha256_file(destination) != item.sha256:
                    return False
            except OSError:
                return False
        return True

    def _copy_with_backup(
        self,
        source: Path,
        destination: Path,
        backup_dir: Path,
        relative: str,
        created: List[Path],
        backups: List[Tuple[Path, Path]],
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            backup = backup_dir / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, backup)
            backups.append((destination, backup))
        else:
            created.append(destination)
        temporary = destination.with_name(destination.name + ".sagepkg-tmp")
        try:
            shutil.copyfile(source, temporary)
            temporary.replace(destination)
        except OSError as exc:
            with suppress(OSError):
                temporary.unlink()
            raise ComponentError(
                f"写入组件文件失败（可能被占用）：{destination}", code="write_failed"
            ) from exc

    def install(self, package_path: Path) -> InstalledComponent:
        package_path = Path(package_path)
        manifest, _body = self._load_manifest(package_path)
        staging_root = self.user_data_dir / "components" / ".staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f"install-{manifest.id}-", dir=str(staging_root)))
        try:
            stage_payload(package_path, manifest, staging, progress=self._progress)
            with self._install_lock():
                metadata = self._read_metadata()
                previous = metadata.get(manifest.id)
                if (
                    previous is not None
                    and previous.version == manifest.version
                    and previous.target == manifest.target
                    and self._files_match(
                        manifest.target,
                        manifest.id,
                        manifest.version,
                        manifest.files,
                    )
                ):
                    return previous
                return self._commit_install(
                    staging, manifest, previous, package_path, metadata
                )
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _commit_install(
        self,
        staging: Path,
        manifest: ComponentManifest,
        previous: Optional[InstalledComponent],
        package_path: Path,
        metadata: Dict[str, InstalledComponent],
    ) -> InstalledComponent:
        resolved = resolve_installed_paths(
            self.user_data_dir,
            manifest.target,
            manifest.id,
            manifest.version,
            manifest.files,
        )
        backup_dir = staging / ".backup"
        backup_dir.mkdir(parents=True, exist_ok=True)
        created: List[Path] = []
        backups: List[Tuple[Path, Path]] = []
        try:
            for item, destination in resolved:
                self._copy_with_backup(
                    staging / item.path,
                    destination,
                    backup_dir,
                    item.path,
                    created,
                    backups,
                )
            installed = InstalledComponent(
                id=manifest.id,
                name=manifest.name,
                version=manifest.version,
                target=manifest.target,
                installed_at=_now_iso(),
                files=manifest.files,
                source_package=str(package_path),
                signature_verified=True,
            )
            next_metadata = dict(metadata)
            next_metadata[installed.id] = installed
            self._write_metadata(next_metadata)
        except Exception:
            for destination, backup in reversed(backups):
                with suppress(OSError):
                    shutil.copy2(backup, destination)
            for destination in reversed(created):
                with suppress(OSError):
                    destination.unlink()
            raise
        if previous is not None:
            keep = {destination for _item, destination in resolved}
            self._remove_old_files(previous, keep, manifest.version)
        return installed

    def _remove_old_files(
        self,
        previous: InstalledComponent,
        keep: Set[Path],
        current_version: str,
    ) -> None:
        try:
            old_paths = resolve_installed_paths(
                self.user_data_dir,
                previous.target,
                previous.id,
                previous.version,
                previous.files,
            )
        except ValueError:
            return
        for _item, path in old_paths:
            if path in keep:
                continue
            try:
                if path.is_file():
                    path.unlink()
            except OSError:
                continue
        if previous.target == "component_dir" and previous.version != current_version:
            version_dir = self.user_data_dir / "components" / previous.id / previous.version
            shutil.rmtree(version_dir, ignore_errors=True)

    # ── remove ────────────────────────────────────────────────────────────

    def remove(self, component_id: str) -> bool:
        with self._install_lock():
            metadata = self._read_metadata()
            installed = metadata.get(component_id)
            if installed is None:
                return False
            try:
                resolved = resolve_installed_paths(
                    self.user_data_dir,
                    installed.target,
                    installed.id,
                    installed.version,
                    installed.files,
                )
            except ValueError as exc:
                raise ComponentError(
                    f"组件元数据路径非法：{exc}", code="invalid_metadata"
                ) from exc
            for _item, path in resolved:
                try:
                    if path.is_file():
                        path.unlink()
                except OSError as exc:
                    raise ComponentError(
                        f"删除组件文件失败（可能被占用）：{path}", code="remove_failed"
                    ) from exc
            if installed.target == "component_dir":
                shutil.rmtree(
                    self.user_data_dir / "components" / installed.id / installed.version,
                    ignore_errors=True,
                )
            else:
                models_root = self.user_data_dir / "models"
                for _item, path in resolved:
                    self._prune_empty_dirs(path.parent, models_root)
            next_metadata = dict(metadata)
            next_metadata.pop(component_id, None)
            self._write_metadata(next_metadata)
            return True

    @staticmethod
    def _prune_empty_dirs(start: Path, stop: Path) -> None:
        current = start
        try:
            stop_resolved = stop.resolve()
        except OSError:
            return
        while True:
            try:
                if current.resolve() == stop_resolved:
                    return
                if any(current.iterdir()):
                    return
                current.rmdir()
            except OSError:
                return
            current = current.parent
