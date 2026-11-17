"""Safe extraction of signed component payloads."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from typing import Callable, Optional, Set

from .errors import ComponentError
from .models import ComponentManifest

MAX_TOTAL_BYTES = 8 * 1024**3
MAX_FILES = 100_000
ProgressCallback = Optional[Callable[[str, str, int, int], None]]


def safe_member_name(name: str) -> str:
    normalized = name.replace("\\", "/")
    parts = normalized.split("/")
    if normalized.startswith("/") or any(part in ("", ".", "..") for part in parts):
        raise ComponentError(f"组件包包含非法路径：{name}", code="unsafe_path")
    if ":" in parts[0]:
        raise ComponentError(f"组件包包含盘符路径：{name}", code="unsafe_path")
    return normalized


def read_component_json(zip_path: Path) -> bytes:
    try:
        with zipfile.ZipFile(zip_path) as archive:
            info = archive.getinfo("component.json")
            if info.file_size > 1024 * 1024:
                raise ComponentError("component.json 过大", code="invalid_manifest")
            return archive.read(info)
    except KeyError as exc:
        raise ComponentError("组件包缺少 component.json", code="invalid_manifest") from exc
    except zipfile.BadZipFile as exc:
        raise ComponentError("组件包不是有效的 zip 文件", code="invalid_zip") from exc


def read_signature(zip_path: Path) -> bytes:
    try:
        with zipfile.ZipFile(zip_path) as archive:
            info = archive.getinfo("signature.bin")
            if info.file_size > 64 * 1024:
                raise ComponentError("signature.bin 过大", code="invalid_signature")
            return archive.read(info)
    except KeyError as exc:
        raise ComponentError("组件包缺少 signature.bin", code="unsigned_package") from exc
    except zipfile.BadZipFile as exc:
        raise ComponentError("组件包不是有效的 zip 文件", code="invalid_zip") from exc


def stage_payload(
    zip_path: Path,
    manifest: ComponentManifest,
    staging_dir: Path,
    progress: ProgressCallback = None,
) -> None:
    expected = {item.path: item for item in manifest.files}
    if len(expected) > MAX_FILES or manifest.total_bytes > MAX_TOTAL_BYTES:
        raise ComponentError("组件包超出文件数量或解压体积限制", code="package_too_large")
    staging_dir.mkdir(parents=True, exist_ok=True)
    seen: Set[str] = set()
    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise ComponentError("组件包不是有效的 zip 文件", code="invalid_zip") from exc
    with archive:
        infos = archive.infolist()
        total = len(infos)
        for index, info in enumerate(infos, 1):
            name = safe_member_name(info.filename)
            if info.is_dir() or name in ("component.json", "signature.bin"):
                continue
            prefix = manifest.payload_dir + "/"
            if not name.startswith(prefix):
                raise ComponentError(
                    f"组件包包含 payload 之外的文件：{name}", code="unexpected_file"
                )
            relative = name[len(prefix) :]
            item = expected.get(relative)
            if item is None:
                raise ComponentError(
                    f"组件包包含未登记文件：{relative}", code="unexpected_file"
                )
            if relative in seen:
                raise ComponentError(
                    f"组件包存在重复条目：{relative}", code="duplicate_entry"
                )
            seen.add(relative)
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise ComponentError(
                    f"组件包不允许符号链接：{relative}", code="symlink_rejected"
                )
            target = staging_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            written = 0
            with archive.open(info) as source, target.open("wb") as destination:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > item.size:
                        raise ComponentError(
                            f"文件大小超出声明：{relative}", code="size_mismatch"
                        )
                    digest.update(chunk)
                    destination.write(chunk)
            if written != item.size or digest.hexdigest() != item.sha256:
                raise ComponentError(f"文件校验失败：{relative}", code="hash_mismatch")
            if progress:
                progress("extract", relative, index, total)
    missing = set(expected) - seen
    if missing:
        raise ComponentError(f"组件包缺少文件：{sorted(missing)[0]}", code="missing_file")
