"""On-disk schema for ``.sagepkg`` manifests and installed-component metadata.

The schema is deliberately plain dataclasses (no pydantic) so the same code
runs on main's pydantic 2.x and release/win7's pydantic 1.x without shims.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$")
_SHA_RE = re.compile(r"^[a-f0-9]{64}$")

ALLOWED_TARGETS = ("user_data", "component_dir")
# ``user_data`` packages may only write below these prefixes. This keeps a
# signed package from overwriting sage.db / settings / diagnostics.
ALLOWED_USER_DATA_PREFIXES = ("models/",)


def safe_relative_path(value: Any, label: str) -> str:
    """Normalise and validate a path that will be joined below a trusted root."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} 必须是非空字符串")
    normalized = value.replace("\\", "/")
    parts = normalized.split("/")
    if normalized.startswith("/") or any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"{label} 不允许绝对路径、空段或 ..：{value}")
    if ":" in parts[0]:
        raise ValueError(f"{label} 不允许盘符：{value}")
    if "\x00" in normalized:
        raise ValueError(f"{label} 包含非法控制字符")
    return normalized


@dataclass(frozen=True)
class ComponentFile:
    path: str
    size: int
    sha256: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ComponentFile:
        path = safe_relative_path(data.get("path"), "文件路径")
        size = data.get("size")
        sha = str(data.get("sha256", "")).lower()
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ValueError("文件 size 必须是非负整数")
        if not _SHA_RE.match(sha):
            raise ValueError("文件 sha256 格式错误")
        return cls(path=path, size=size, sha256=sha)

    def to_dict(self) -> Dict[str, Any]:
        return {"path": self.path, "size": self.size, "sha256": self.sha256}


@dataclass(frozen=True)
class ComponentManifest:
    schema_version: int
    id: str
    name: str
    version: str
    branch: str
    python: str
    arch: str
    target: str
    payload_dir: str
    files: Tuple[ComponentFile, ...]
    description: str = ""
    created_at: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ComponentManifest:
        if not isinstance(data, dict) or data.get("schemaVersion") != 1:
            raise ValueError("不支持的组件包 schemaVersion")
        comp_id = str(data.get("id", ""))
        if not _ID_RE.match(comp_id):
            raise ValueError("组件 id 格式错误")
        version = str(data.get("version", ""))
        if not _VERSION_RE.match(version):
            raise ValueError("组件 version 格式错误")
        target = str(data.get("target", ""))
        if target not in ALLOWED_TARGETS:
            raise ValueError(f"不支持的组件 target：{target}")
        payload_dir = safe_relative_path(data.get("payloadDir", "payload"), "payloadDir")
        raw_files = data.get("files")
        if not isinstance(raw_files, list) or not raw_files:
            raise ValueError("组件包 files 不能为空")
        files = tuple(ComponentFile.from_dict(item) for item in raw_files)
        paths = [item.path for item in files]
        if len(paths) != len(set(paths)):
            raise ValueError("组件包 files 存在重复路径")
        if target == "user_data":
            for item in files:
                if not any(item.path.startswith(prefix) for prefix in ALLOWED_USER_DATA_PREFIXES):
                    raise ValueError(
                        f"user_data 组件只能写入 {'/'.join(ALLOWED_USER_DATA_PREFIXES)}："
                        f"{item.path}"
                    )
        return cls(
            schema_version=1,
            id=comp_id,
            name=str(data.get("name", comp_id)),
            version=version,
            branch=str(data.get("branch", "")),
            python=str(data.get("python", "")),
            arch=str(data.get("arch", "")),
            target=target,
            payload_dir=payload_dir,
            files=files,
            description=str(data.get("description", "")),
            created_at=str(data.get("createdAt", "")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "branch": self.branch,
            "python": self.python,
            "arch": self.arch,
            "target": self.target,
            "payloadDir": self.payload_dir,
            "files": [item.to_dict() for item in self.files],
            "description": self.description,
            "createdAt": self.created_at,
        }

    @property
    def total_bytes(self) -> int:
        return sum(item.size for item in self.files)


@dataclass(frozen=True)
class InstalledComponent:
    id: str
    name: str
    version: str
    target: str
    installed_at: str
    files: Tuple[ComponentFile, ...]
    source_package: str
    signature_verified: bool

    @property
    def total_bytes(self) -> int:
        return sum(item.size for item in self.files)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> InstalledComponent:
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            version=str(data.get("version", "")),
            target=str(data.get("target", "")),
            installed_at=str(data.get("installedAt", "")),
            files=tuple(ComponentFile.from_dict(item) for item in data.get("files", [])),
            source_package=str(data.get("sourcePackage", "")),
            signature_verified=bool(data.get("signatureVerified", False)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "target": self.target,
            "installedAt": self.installed_at,
            "files": [item.to_dict() for item in self.files],
            "sourcePackage": self.source_package,
            "signatureVerified": self.signature_verified,
        }


@dataclass(frozen=True)
class PackageScanResult:
    path: str
    id: str
    name: str
    version: str
    size: int
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "size": self.size,
            "error": self.error,
        }


def installed_manifest_path(user_data_dir: Path) -> Path:
    return user_data_dir / "components" / "installed.json"


def component_install_root(user_data_dir: Path, component_id: str, version: str) -> Path:
    return user_data_dir / "components" / component_id / version


def resolve_installed_paths(
    user_data_dir: Path,
    target: str,
    component_id: str,
    version: str,
    files: Tuple[ComponentFile, ...],
) -> List[Tuple[ComponentFile, Path]]:
    """Map manifest files to their final absolute paths."""
    resolved: List[Tuple[ComponentFile, Path]] = []
    for item in files:
        if target == "user_data":
            if not any(item.path.startswith(prefix) for prefix in ALLOWED_USER_DATA_PREFIXES):
                raise ValueError(f"user_data 组件路径不在允许前缀内：{item.path}")
            destination = user_data_dir / item.path
        elif target == "component_dir":
            destination = component_install_root(user_data_dir, component_id, version) / item.path
        else:
            raise ValueError(f"不支持的组件 target：{target}")
        resolved.append((item, destination))
    return resolved


def parse_installed_metadata(raw: Optional[Dict[str, Any]]) -> Dict[str, InstalledComponent]:
    if not isinstance(raw, dict):
        return {}
    components = raw.get("components")
    if not isinstance(components, dict):
        return {}
    result: Dict[str, InstalledComponent] = {}
    for key, value in components.items():
        if isinstance(value, dict) and isinstance(key, str):
            try:
                result[key] = InstalledComponent.from_dict(value)
            except ValueError:
                continue
    return result
