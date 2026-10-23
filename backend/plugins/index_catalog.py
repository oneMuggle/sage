# ruff: noqa: UP006, UP007, UP035
"""Static, offline-validatable plugin index (R86).

The index is catalog data only. Building, validating, or searching it never
downloads an archive, verifies a signature, installs a plugin, or executes
plugin code. A web host can serve ``index.json`` as a static file; Sage keeps
installation and runtime activation on the existing explicit R82/R83 paths.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from backend.plugins.manifest import PluginManifest
from backend.plugins.scaffold import validate_plugin_package
from backend.plugins.scaffold_templates import PluginEcosystemError

try:
    from pydantic import field_validator, model_validator

    PYDANTIC_V2 = True
except ImportError:  # pragma: no cover - exercised only on Pydantic v1 stacks
    from pydantic import (  # type: ignore
        root_validator as model_validator,
        validator as field_validator,
    )

    PYDANTIC_V2 = False


INDEX_SCHEMA_VERSION = "1.0"
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_CAPABILITY_TYPES = {"command", "hook", "mcp_server", "skill", "tool"}


class PluginSourceKind(str, Enum):
    """How an index consumer can locate plugin source material."""

    GIT = "git"
    ARCHIVE = "archive"
    LOCAL = "local"


class Win7Support(str, Enum):
    """Evidence state for the Windows 7 / Python 3.8 line."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


def _is_https_url(value: Optional[str]) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def _is_relative_path(value: Optional[str]) -> bool:
    if not value:
        return False
    return not (
        value.startswith(("/", "\\"))
        or re.match(r"^[A-Za-z]:", value)
        or Path(value).is_absolute()
    )


def _validate_signature_values(values: Dict[str, Any]) -> None:
    if not values.get("value") and not values.get("url"):
        raise ValueError("signature requires value or url")
    if values.get("url") and not _is_https_url(str(values["url"])):
        raise ValueError("signature url must be HTTPS")


def _validate_source_values(values: Dict[str, Any]) -> None:
    raw_kind = values.get("kind")
    kind = str(getattr(raw_kind, "value", raw_kind))
    url = values.get("url")
    subdir = values.get("subdir")
    path = values.get("path")
    sha256 = values.get("sha256")

    if kind in (PluginSourceKind.GIT.value, PluginSourceKind.ARCHIVE.value) and not _is_https_url(url):
        raise ValueError(f"{kind} source url must be HTTPS")
    if kind == PluginSourceKind.ARCHIVE.value and (not sha256 or not _SHA256_RE.match(str(sha256))):
        raise ValueError("archive source requires a lowercase SHA-256")
    if kind == PluginSourceKind.LOCAL.value and not _is_relative_path(path):
        raise ValueError("local source requires a relative path")
    if subdir is not None and (not _is_relative_path(subdir) or ".." in Path(subdir).parts):
        raise ValueError("source subdir must stay below the source root")


class PluginSignature(BaseModel):
    """Optional signature metadata; R86 validates shape, not trust."""

    algorithm: str = Field(..., min_length=1, max_length=50)
    value: Optional[str] = Field(default=None, description="Inline signature value")
    url: Optional[str] = Field(default=None, description="HTTPS signature URL")
    key_id: Optional[str] = Field(default=None, description="Publisher key identifier")

    if PYDANTIC_V2:

        @model_validator(mode="after")
        def validate_signature(self) -> PluginSignature:
            _validate_signature_values(
                {"value": self.value, "url": self.url, "algorithm": self.algorithm}
            )
            return self

    else:  # pragma: no cover

        @model_validator
        @classmethod
        def validate_signature(cls, values: Dict[str, Any]) -> Dict[str, Any]:
            _validate_signature_values(values)
            return values


class PluginSource(BaseModel):
    """Static locator for one plugin version."""

    kind: PluginSourceKind
    url: Optional[str] = None
    ref: Optional[str] = None
    subdir: Optional[str] = None
    path: Optional[str] = None
    sha256: Optional[str] = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    if PYDANTIC_V2:

        @model_validator(mode="after")
        def validate_source(self) -> PluginSource:
            _validate_source_values(
                {
                    "kind": self.kind,
                    "url": self.url,
                    "subdir": self.subdir,
                    "path": self.path,
                    "sha256": self.sha256,
                }
            )
            return self

    else:  # pragma: no cover

        @model_validator
        @classmethod
        def validate_source(cls, values: Dict[str, Any]) -> Dict[str, Any]:
            _validate_source_values(values)
            return values


def _validate_sage_requirement(value: str) -> str:
    if not re.match(r"^(>=|==|~=|>|<|<=)?\d+\.\d+\.\d+$", value.strip()):
        raise ValueError("sage compatibility must be a simple version requirement")
    return value.strip()


class PluginCompatibility(BaseModel):
    """Compatibility claims shown before a user chooses to install."""

    sage: str = Field(default=">=0.4.0", min_length=5)
    python: str = Field(default=">=3.8", min_length=3)
    platforms: List[str] = Field(default_factory=lambda: ["any"])
    win7: Win7Support = Win7Support.UNKNOWN

    if PYDANTIC_V2:

        @field_validator("sage")
        @classmethod
        def validate_sage(cls, value: str) -> str:
            return _validate_sage_requirement(value)

    else:  # pragma: no cover

        @field_validator("sage")
        @classmethod
        def validate_sage(cls, value: str) -> str:
            return _validate_sage_requirement(value)


class PluginIndexEntry(BaseModel):
    """One immutable plugin version in a static index."""

    name: str = Field(..., min_length=1, max_length=100)
    version: str = Field(..., pattern=r"^\d+\.\d+\.\d+$")
    manifest: PluginManifest
    source: PluginSource
    compatibility: PluginCompatibility = Field(default_factory=PluginCompatibility)
    signature: Optional[PluginSignature] = None
    published_at: Optional[str] = None

    if PYDANTIC_V2:

        @model_validator(mode="after")
        def validate_manifest_identity(self) -> PluginIndexEntry:
            if self.manifest.name != self.name or self.manifest.version != self.version:
                raise ValueError("index entry name/version must match its manifest")
            return self

    else:  # pragma: no cover

        @model_validator
        @classmethod
        def validate_manifest_identity(cls, values: Dict[str, Any]) -> Dict[str, Any]:
            manifest = values.get("manifest")
            manifest_name = getattr(manifest, "name", None) or (
                manifest.get("name") if isinstance(manifest, dict) else None
            )
            manifest_version = getattr(manifest, "version", None) or (
                manifest.get("version") if isinstance(manifest, dict) else None
            )
            if manifest_name != values.get("name") or manifest_version != values.get("version"):
                raise ValueError("index entry name/version must match its manifest")
            return values

    def to_dict(self) -> Dict[str, Any]:
        return json.loads(self.to_json())

    def to_json(self) -> str:
        if hasattr(self, "model_dump_json"):
            return self.model_dump_json()
        return self.json()  # pragma: no cover


class PluginIndex(BaseModel):
    """A complete static plugin index."""

    schema_version: str = Field(default=INDEX_SCHEMA_VERSION, pattern=r"^\d+\.\d+$")
    generated_at: Optional[str] = None
    plugins: List[PluginIndexEntry] = Field(default_factory=list)

    if PYDANTIC_V2:

        @model_validator(mode="after")
        def validate_unique_plugins(self) -> PluginIndex:
            seen = set()
            for entry in self.plugins:
                key = (entry.name, entry.version)
                if key in seen:
                    raise ValueError(f"duplicate plugin index entry: {entry.name}@{entry.version}")
                seen.add(key)
            return self

    else:  # pragma: no cover

        @model_validator
        @classmethod
        def validate_unique_plugins(cls, values: Dict[str, Any]) -> Dict[str, Any]:
            seen = set()
            for entry in values.get("plugins", []):
                name = getattr(entry, "name", None) or entry.get("name")
                version = getattr(entry, "version", None) or entry.get("version")
                key = (name, version)
                if key in seen:
                    raise ValueError(f"duplicate plugin index entry: {name}@{version}")
                seen.add(key)
            return values

    def to_dict(self) -> Dict[str, Any]:
        return json.loads(self.to_json())

    def to_json(self, indent: int = 2) -> str:
        if hasattr(self, "model_dump_json"):
            return self.model_dump_json(indent=indent)
        return self.json(indent=indent)  # pragma: no cover

    @classmethod
    def from_json(cls, payload: str) -> PluginIndex:
        data = json.loads(payload)
        if hasattr(cls, "model_validate"):
            return cls.model_validate(data)
        return cls.parse_obj(data)  # pragma: no cover

    @classmethod
    def from_file(cls, path: Path) -> PluginIndex:
        return cls.from_json(Path(path).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class PluginIndexIssue:
    """One index validation finding."""

    code: str
    severity: str
    message: str
    plugin: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "plugin": self.plugin,
        }


@dataclass(frozen=True)
class PluginIndexValidation:
    """Result of validating one static index."""

    path: Optional[Path]
    index: Optional[PluginIndex]
    issues: Tuple[PluginIndexIssue, ...]
    checked_local: bool = False

    @property
    def errors(self) -> Tuple[PluginIndexIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> Tuple[PluginIndexIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    @property
    def ok(self) -> bool:
        return self.index is not None and not self.errors

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "path": str(self.path) if self.path is not None else None,
            "checked_local": self.checked_local,
            "plugin_count": len(self.index.plugins) if self.index is not None else 0,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class PluginIndexBuildResult:
    """Built index plus the package validations used to produce it."""

    index: PluginIndex
    roots: Tuple[Path, ...]
    validations: Tuple[Any, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "roots": [str(root) for root in self.roots],
            "index": self.index.to_dict(),
            "validations": [validation.to_dict() for validation in self.validations],
        }


def _version_key(version: str) -> Tuple[int, int, int]:
    match = _VERSION_RE.match(version)
    if match is None:
        return (0, 0, 0)
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")  # noqa: UP017 - Python 3.8 has no datetime.UTC


def discover_plugin_roots(roots: Sequence[Path]) -> List[Path]:
    """Expand plugin roots or one-level plugin collections deterministically."""

    discovered: List[Path] = []
    seen = set()
    for raw_root in roots:
        root = Path(raw_root).expanduser()
        if not root.is_absolute():
            root = Path.cwd() / root
        candidates: List[Path] = []
        if root.is_file() and root.name == "plugin.json":
            candidates.append(root.parent)
        elif root.is_dir() and (root / "plugin.json").is_file():
            candidates.append(root)
        elif root.is_dir():
            candidates.extend(
                child
                for child in sorted(root.iterdir(), key=lambda item: item.name)
                if child.is_dir() and (child / "plugin.json").is_file()
            )
        if not candidates:
            raise PluginEcosystemError(
                "PLUGIN_ROOT_NOT_FOUND",
                f"no plugin.json found at or one level below: {root}",
                status_code=404,
            )
        for candidate in candidates:
            resolved = candidate.resolve()
            key = str(resolved)
            if key not in seen:
                seen.add(key)
                discovered.append(resolved)
    return discovered


def _source_for_root(
    root: Path,
    *,
    source_kind: str,
    source_url: Optional[str],
    source_ref: Optional[str],
    base_dir: Path,
) -> PluginSource:
    kind = source_kind.strip().lower()
    if kind == PluginSourceKind.LOCAL.value:
        relative = os.path.relpath(str(root), str(base_dir)).replace(os.sep, "/")
        return PluginSource(kind=PluginSourceKind.LOCAL, path=relative)
    if kind == PluginSourceKind.GIT.value:
        if not source_url:
            raise PluginEcosystemError(
                "PLUGIN_SOURCE_URL_REQUIRED",
                "git index sources require --source-url",
                status_code=422,
            )
        try:
            subdir = root.relative_to(base_dir).as_posix()
        except ValueError as exc:
            raise PluginEcosystemError(
                "PLUGIN_SOURCE_SUBDIR_UNKNOWN",
                "git plugin root must be below --base-dir so its subdir can be recorded",
                status_code=422,
                details={"root": str(root), "base_dir": str(base_dir)},
            ) from exc
        return PluginSource(
            kind=PluginSourceKind.GIT,
            url=source_url,
            ref=source_ref or "main",
            subdir=subdir,
        )
    raise PluginEcosystemError(
        "PLUGIN_SOURCE_KIND_UNSUPPORTED",
        f"index build does not create {kind!r} sources",
        status_code=422,
    )


def build_plugin_index(
    roots: Sequence[Path],
    *,
    source_kind: str = PluginSourceKind.LOCAL.value,
    source_url: Optional[str] = None,
    source_ref: Optional[str] = None,
    base_dir: Optional[Path] = None,
    generated_at: Optional[str] = None,
) -> PluginIndexBuildResult:
    """Validate plugin packages and build a deterministic static index."""

    plugin_roots = discover_plugin_roots(roots)
    base = (base_dir.expanduser() if base_dir is not None else Path.cwd())
    if not base.is_absolute():
        base = Path.cwd() / base
    base = base.resolve()

    validations = []
    entries: List[PluginIndexEntry] = []
    for root in plugin_roots:
        validation = validate_plugin_package(root)
        validations.append(validation)
        if validation.manifest is None or validation.errors:
            raise PluginEcosystemError(
                "PLUGIN_INDEX_BUILD_FAILED",
                f"plugin package failed validation: {root}",
                status_code=422,
                details={"validations": [item.to_dict() for item in validations]},
            )
        manifest = validation.manifest
        entries.append(
            PluginIndexEntry(
                name=manifest.name,
                version=manifest.version,
                manifest=manifest,
                source=_source_for_root(
                    root,
                    source_kind=source_kind,
                    source_url=source_url,
                    source_ref=source_ref,
                    base_dir=base,
                ),
                compatibility=PluginCompatibility(
                    sage=f">={manifest.min_sage_version}",
                    python=manifest.python_version,
                    platforms=["any"],
                    win7=Win7Support.UNKNOWN,
                ),
            )
        )

    entries.sort(key=lambda entry: (entry.name, _version_key(entry.version)))
    try:
        index = PluginIndex(
            schema_version=INDEX_SCHEMA_VERSION,
            generated_at=generated_at or _utc_now(),
            plugins=entries,
        )
    except (TypeError, ValueError) as exc:
        raise PluginEcosystemError(
            "PLUGIN_INDEX_BUILD_FAILED",
            str(exc),
            status_code=422,
        ) from exc
    return PluginIndexBuildResult(
        index=index,
        roots=tuple(plugin_roots),
        validations=tuple(validations),
    )


def write_plugin_index(index: PluginIndex, path: Path) -> Path:
    """Write an index atomically as UTF-8 JSON."""

    output = Path(path).expanduser()
    if not output.is_absolute():
        output = Path.cwd() / output
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    try:
        temporary.write_bytes((index.to_json(indent=2) + "\n").encode("utf-8"))
        temporary.replace(output)
    except OSError as exc:
        raise PluginEcosystemError(
            "PLUGIN_INDEX_WRITE_FAILED",
            f"could not write plugin index: {exc}",
            status_code=500,
        ) from exc
    finally:
        if temporary.exists():
            temporary.unlink()
    return output


def load_plugin_index(path: Path) -> PluginIndex:
    """Load and structurally validate one static index file."""

    try:
        return PluginIndex.from_file(Path(path))
    except (OSError, TypeError, ValueError) as exc:
        raise PluginEcosystemError(
            "PLUGIN_INDEX_INVALID",
            str(exc),
            status_code=422,
            details={"path": str(path)},
        ) from exc


def _compatibility_issues(entry: PluginIndexEntry) -> List[PluginIndexIssue]:
    issues: List[PluginIndexIssue] = []
    if not entry.compatibility.platforms:
        issues.append(PluginIndexIssue("COMPATIBILITY_PLATFORMS_EMPTY", "error", "compatibility.platforms must not be empty", entry.name))
    requirement = entry.compatibility.sage.strip()
    if requirement.startswith(">="):
        advertised = requirement[2:]
        if _version_key(advertised) < _version_key(entry.manifest.min_sage_version):
            issues.append(PluginIndexIssue("COMPATIBILITY_BELOW_MANIFEST", "error", "index advertises an older Sage than the manifest minimum", entry.name))
    return issues


def _local_root_for_entry(
    entry: PluginIndexEntry,
    base_dir: Path,
) -> Tuple[Optional[Path], Optional[PluginIndexIssue]]:
    kind = str(getattr(entry.source.kind, "value", entry.source.kind))
    if kind == PluginSourceKind.LOCAL.value:
        return (base_dir / str(entry.source.path)).resolve(), None
    if kind == PluginSourceKind.GIT.value:
        if entry.source.subdir:
            return (base_dir / entry.source.subdir).resolve(), None
        return None, PluginIndexIssue("LOCAL_CHECK_SKIPPED", "warning", "git source has no subdir for a local checkout check", entry.name)
    return None, PluginIndexIssue("LOCAL_CHECK_SKIPPED", "warning", "archive sources are not downloaded during local index validation", entry.name)


def validate_plugin_index(
    source: Union[PluginIndex, Path],
    *,
    check_local: bool = False,
    base_dir: Optional[Path] = None,
) -> PluginIndexValidation:
    """Validate index structure and, optionally, local checkout consistency."""

    path: Optional[Path] = None
    index: Optional[PluginIndex]
    issues: List[PluginIndexIssue] = []
    if isinstance(source, PluginIndex):
        try:
            index = PluginIndex.from_json(source.to_json())
        except (TypeError, ValueError) as exc:
            return PluginIndexValidation(
                path=None,
                index=None,
                issues=(PluginIndexIssue("PLUGIN_INDEX_INVALID", "error", str(exc)),),
                checked_local=check_local,
            )
    else:
        path = Path(source).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        try:
            index = load_plugin_index(path)
        except PluginEcosystemError as exc:
            return PluginIndexValidation(
                path=path,
                index=None,
                issues=(PluginIndexIssue(exc.code, "error", exc.message),),
                checked_local=check_local,
            )

    for entry in index.plugins:
        issues.extend(_compatibility_issues(entry))

    if check_local:
        provided_base = None
        if base_dir is not None:
            provided_base = base_dir.expanduser()
            if not provided_base.is_absolute():
                provided_base = Path.cwd() / provided_base
            provided_base = provided_base.resolve()
        local_base = path.parent if path else Path.cwd()
        for entry in index.plugins:
            kind = str(getattr(entry.source.kind, "value", entry.source.kind))
            if provided_base is not None:
                base = provided_base
            elif kind == PluginSourceKind.LOCAL.value:
                base = local_base
            else:
                # Git subdirs are recorded relative to a checkout root. The
                # conventional invocation is from that root; --base-dir makes
                # any other checkout location explicit.
                base = Path.cwd()
            root, skip_issue = _local_root_for_entry(entry, base.resolve())
            if skip_issue is not None:
                issues.append(skip_issue)
                continue
            if root is None or not root.is_dir():
                issues.append(
                    PluginIndexIssue(
                        "INDEX_LOCAL_PLUGIN_MISSING",
                        "error",
                        f"local plugin root does not exist: {root}",
                        entry.name,
                    )
                )
                continue
            validation = validate_plugin_package(root)
            for item in validation.issues:
                issues.append(
                    PluginIndexIssue(item.code, item.severity, item.message, entry.name)
                )
            if validation.manifest is None:
                continue
            if validation.manifest.name != entry.name or validation.manifest.version != entry.version:
                issues.append(
                    PluginIndexIssue(
                        "INDEX_LOCAL_MANIFEST_MISMATCH",
                        "error",
                        "local manifest name/version differs from the index entry",
                        entry.name,
                    )
                )
            elif json.dumps(
                validation.manifest.to_dict(), sort_keys=True, default=str
            ) != json.dumps(entry.manifest.to_dict(), sort_keys=True, default=str):
                issues.append(
                    PluginIndexIssue(
                        "INDEX_LOCAL_MANIFEST_DRIFT",
                        "error",
                        "local manifest differs from the manifest embedded in the index",
                        entry.name,
                    )
                )

    return PluginIndexValidation(
        path=path,
        index=index,
        issues=tuple(issues),
        checked_local=check_local,
    )


def _entry_view(entry: PluginIndexEntry) -> Dict[str, Any]:
    payload = entry.to_dict()
    manifest = payload["manifest"]
    metadata = manifest.get("metadata") or {}
    permissions: List[str] = []
    seen = set()
    for capability in manifest.get("capabilities") or []:
        for permission in capability.get("permissions") or []:
            if permission not in seen:
                seen.add(permission)
                permissions.append(permission)
    return {
        "name": payload["name"],
        "version": payload["version"],
        "display_name": metadata.get("display_name") or payload["name"],
        "description": metadata.get("description") or "",
        "author": metadata.get("author") or "",
        "categories": metadata.get("categories") or [],
        "tags": metadata.get("tags") or [],
        "capabilities": manifest.get("capabilities") or [],
        "permissions": permissions,
        "source": payload["source"],
        "compatibility": payload["compatibility"],
        "signature": payload.get("signature"),
        "published_at": payload.get("published_at"),
    }


def search_plugin_index(
    index: PluginIndex,
    query: str = "",
    *,
    capability_type: Optional[str] = None,
    permission: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Search a loaded static index without network access."""

    normalized_type = capability_type.strip().lower() if capability_type else None
    if normalized_type and normalized_type not in _CAPABILITY_TYPES:
        raise PluginEcosystemError(
            "UNKNOWN_CAPABILITY_TYPE",
            f"unknown capability type: {capability_type!r}",
            status_code=422,
            details={"capability_types": sorted(_CAPABILITY_TYPES)},
        )
    tokens = [token.lower() for token in query.split() if token.strip()]
    results: List[Dict[str, Any]] = []
    for entry in sorted(index.plugins, key=lambda item: (item.name, _version_key(item.version))):
        view = _entry_view(entry)
        if normalized_type and not any(
            capability.get("type") == normalized_type
            for capability in view["capabilities"]
        ):
            continue
        if permission and permission not in view["permissions"]:
            continue
        haystack_parts = [
            view["name"],
            view["display_name"],
            view["description"],
            view["author"],
            " ".join(view["categories"]),
            " ".join(view["tags"]),
            " ".join(
                "{} {}".format(capability.get("type", ""), capability.get("name", ""))
                for capability in view["capabilities"]
            ),
        ]
        haystack = "\n".join(haystack_parts).lower()
        if tokens and not all(token in haystack for token in tokens):
            continue
        results.append(view)
    return results


__all__ = [
    "INDEX_SCHEMA_VERSION",
    "PluginCompatibility",
    "PluginIndex",
    "PluginIndexBuildResult",
    "PluginIndexEntry",
    "PluginIndexIssue",
    "PluginIndexValidation",
    "PluginSignature",
    "PluginSource",
    "PluginSourceKind",
    "Win7Support",
    "build_plugin_index",
    "discover_plugin_roots",
    "load_plugin_index",
    "search_plugin_index",
    "validate_plugin_index",
    "write_plugin_index",
]
