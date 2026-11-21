"""Safe OOXML archive handling (M5).

OOXML files are ZIP archives of XML parts.  This module provides the
security-relevant primitive layer used by validate/runs helpers:

- member counting / size / compression-ratio budgets (zip-bomb guard)
- path traversal, absolute path and symlink rejection
- deterministic pack (fixed timestamps, sorted members)

Failure contract: every problem raises ``OfficeParseError`` so the route
layer returns the structured 422 envelope.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import zipfile
from pathlib import Path
from typing import List

from ..errors import OfficeParseError

__all__ = ["pack_ooxml", "unpack_ooxml", "validate_archive_members"]

MAX_MEMBERS = 10_000
MAX_TOTAL_UNCOMPRESSED = 250 * 1024 * 1024
MAX_MEMBER_UNCOMPRESSED = 50 * 1024 * 1024
#: file_size / compress_size ratio above this is treated as a zip bomb.
MAX_COMPRESSION_RATIO = 1000
#: Only ratios above this size are checked (small XML compresses naturally).
_RATIO_CHECK_MIN_BYTES = 10 * 1024 * 1024


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return (info.external_attr >> 16) & 0o170000 == 0o120000


def _validate_member_name(name: str) -> None:
    if not name or name.endswith("/"):
        return
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or (len(normalized) > 1 and normalized[1] == ":"):
        raise OfficeParseError(f"OOXML 包含绝对路径成员: {name}")
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise OfficeParseError(f"OOXML 包含路径穿越成员: {name}")


def validate_archive_members(archive: zipfile.ZipFile) -> None:
    """Enforce member count / size / ratio / name safety rules."""
    infos = archive.infolist()
    if len(infos) > MAX_MEMBERS:
        raise OfficeParseError(f"OOXML 成员数超过上限 {MAX_MEMBERS}")
    total = 0
    for info in infos:
        if _is_symlink(info):
            raise OfficeParseError(f"OOXML 包含符号链接成员: {info.filename}")
        _validate_member_name(info.filename)
        if info.file_size > MAX_MEMBER_UNCOMPRESSED:
            raise OfficeParseError(f"OOXML 成员过大: {info.filename}")
        total += info.file_size
        if total > MAX_TOTAL_UNCOMPRESSED:
            raise OfficeParseError("OOXML 解压后总大小超过 250MiB 上限")
        if (
            info.file_size > _RATIO_CHECK_MIN_BYTES
            and info.compress_size > 0
            and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO
        ):
            raise OfficeParseError(f"OOXML 成员压缩比异常（疑似 zip bomb）: {info.filename}")


def unpack_ooxml(source: Path, destination: Path) -> int:
    """Safely extract an OOXML archive; returns the member count."""
    source = Path(source)
    destination = Path(destination)
    try:
        archive = zipfile.ZipFile(str(source))
    except (OSError, zipfile.BadZipFile) as exc:
        raise OfficeParseError(f"无法打开 OOXML 包: {exc}", file_path=source) from exc
    with archive:
        broken = archive.testzip()
        if broken is not None:
            raise OfficeParseError(f"OOXML 包损坏（首个坏成员 {broken}）", file_path=source)
        validate_archive_members(archive)
        destination.mkdir(parents=True, exist_ok=True)
        for info in archive.infolist():
            if info.filename.endswith("/"):
                continue
            target = (destination / info.filename).resolve()
            try:
                target.relative_to(destination.resolve())
            except ValueError as exc:
                raise OfficeParseError(f"OOXML 成员越界: {info.filename}") from exc
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, open(target, "wb") as dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)
    return len(archive.infolist())


def pack_ooxml(source_dir: Path, output: Path, *, overwrite: bool = False) -> int:
    """Deterministically pack a directory into an OOXML zip; returns member count."""
    source_dir = Path(source_dir)
    output = Path(output)
    if not source_dir.is_dir():
        raise OfficeParseError(f"目录不存在: {source_dir}")
    if output.exists() and not overwrite:
        raise OfficeParseError(f"输出文件已存在: {output}")
    files: List[Path] = sorted(
        path for path in source_dir.rglob("*") if path.is_file() and not path.is_symlink()
    )
    if len(files) > MAX_MEMBERS:
        raise OfficeParseError(f"OOXML 成员数超过上限 {MAX_MEMBERS}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=output.name + ".", suffix=".tmp", dir=str(output.parent)
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            str(temporary), "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for path in files:
                info = zipfile.ZipInfo(
                    path.relative_to(source_dir).as_posix(),
                    date_time=(1980, 1, 1, 0, 0, 0),
                )
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                with open(path, "rb") as handle:
                    archive.writestr(info, handle.read())
        temporary.replace(output)
    except OSError as exc:
        raise OfficeParseError(f"打包 OOXML 失败: {exc}", file_path=output) from exc
    finally:
        if temporary.exists():
            with contextlib.suppress(OSError):
                temporary.unlink()
    return len(files)
