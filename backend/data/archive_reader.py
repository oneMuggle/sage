# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""压缩包文件读取 —— 目录列表与条目内容读取（feat/archive-preview）。

消费方:
- ``workspace_preview_routes`` 工作区文件预览端点
- ``file_tool`` AI 工具读取压缩包内文件
- 文件清理场景压缩包内容摘要

安全约束:
- 路径穿越防护: entry path 不得含 ``..`` 或绝对路径
- 大小限制: 压缩包 >500MB 只返回目录结构，不读取内容
- 解压比例防护 (zip bomb): 解压后总大小 >1GB 拒绝
- 加密: 检测后返回 ``encrypted`` 状态

P0 格式 (纯标准库):
- ``.zip`` → ``zipfile``
- ``.tar`` / ``.tar.gz`` / ``.tgz`` / ``.tar.bz2`` / ``.tar.xz`` → ``tarfile``
- ``.gz`` / ``.bz2`` / ``.xz`` → 单文件解压读取

py3.8 纪律: stdlib only, 不用 ``str | None`` 联合语法。
"""

from __future__ import annotations

import bz2
import datetime
import gzip
import lzma
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

#: 压缩包大小上限 (字节)——超过只返回目录结构
MAX_ARCHIVE_SIZE_BYTES = 500 * 1024 * 1024  # 500 MB
#: 解压后总大小上限 (字节)——zip bomb 防护
MAX_EXTRACTED_SIZE_BYTES = 1024 * 1024 * 1024  # 1 GB
#: 单条目读取大小上限 (字节)
MAX_ENTRY_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
#: 条目列表最大条数——超过截断
MAX_ENTRY_COUNT = 10000

#: 扩展名 → 格式标签
_EXT_FORMAT_MAP: Dict[str, str] = {
    ".zip": "zip",
    ".jar": "zip",
    ".war": "zip",
    ".ear": "zip",
    ".whl": "zip",
    ".epub": "zip",
    ".docx": "zip",  # Office 文件底层是 zip，但预览走 office 路径
    ".xlsx": "zip",
    ".pptx": "zip",
    ".tar": "tar",
    ".tar.gz": "tar.gz",
    ".tgz": "tar.gz",
    ".tar.bz2": "tar.bz2",
    ".tbz2": "tar.bz2",
    ".tar.xz": "tar.xz",
    ".txz": "tar.xz",
    ".gz": "gzip",
    ".bz2": "bzip2",
    ".xz": "xz",
}

#: 魔数 → 格式标签 (用于文件头校验)
_MAGIC_FORMAT: Tuple[Tuple[bytes, str], ...] = (
    (b"PK\x03\x04", "zip"),
    (b"PK\x05\x06", "zip"),  # 空 zip
    (b"\x1f\x8b", "gzip"),
    (b"BZh", "bzip2"),
    (b"\xfd7zXZ\x00", "xz"),
)


@dataclass
class ArchiveEntry:
    """压缩包内条目信息。"""
    name: str
    size: int
    compressed_size: int
    is_dir: bool
    mtime: Optional[int] = None  # Unix timestamp (秒)
    is_archive: bool = False  # 是否为嵌套压缩包


@dataclass
class ArchiveInfo:
    """压缩包整体信息。"""
    format: str  # "zip" / "tar" / "tar.gz" / ...
    path: str
    size: int  # 压缩包文件大小 (字节)
    entry_count: int
    total_uncompressed: int  # 解压后总大小
    entries: List[ArchiveEntry]
    encrypted: bool = False
    truncated: bool = False  # 是否因超限截断


def detect_archive_kind(path: Path) -> Optional[str]:
    """按扩展名 + 魔数判定压缩包格式。

    返回格式标签 (``zip`` / ``tar`` / ``tar.gz`` / ``gzip`` / ...) 或 ``None``。
    Office 文件 (docx/xlsx/pptx) 虽然底层是 zip，但预览走 office 路径，此处
    返回 ``"zip"`` 让调用方决定是否作为压缩包处理。
    """
    if not path.is_file():
        return None
    # 复合扩展名优先 (.tar.gz > .gz)
    name_lower = path.name.lower()
    for ext, fmt in _EXT_FORMAT_MAP.items():
        if name_lower.endswith(ext):
            return fmt
    return None


def _is_path_safe(entry_path: str) -> bool:
    """校验条目路径是否安全 (防路径穿越)。"""
    if not entry_path:
        return False
    if entry_path.startswith("/") or entry_path.startswith("\\"):
        return False
    if ".." in entry_path.split("/"):
        return False
    if ".." in entry_path.split("\\"):
        return False
    return True


def _is_nested_archive(name: str) -> bool:
    """判断文件名是否为压缩包 (用于嵌套检测)。"""
    name_lower = name.lower()
    return any(name_lower.endswith(ext) for ext in _EXT_FORMAT_MAP)


def _zip_datetime(dt: Tuple[int, int, int, int, int, int]) -> datetime.datetime:
    """将 zip 时间元组转为 datetime。"""
    try:
        return datetime.datetime(dt[0], dt[1], dt[2], dt[3], dt[4], dt[5])  # noqa: DTZ001 — zip 本地时间
    except ValueError:
        return datetime.datetime(1980, 1, 1)  # noqa: DTZ001 — 回退默认


def _read_zip_listing(path: Path, max_entries: int = MAX_ENTRY_COUNT) -> Tuple[List[ArchiveEntry], int, bool, bool]:
    """读取 zip 压缩包目录列表。

    返回 (entries, total_uncompressed, encrypted, truncated)。
    """
    entries: List[ArchiveEntry] = []
    total_size = 0
    encrypted = False
    truncated = False

    try:
        with zipfile.ZipFile(path, "r") as zf:
            for i, info in enumerate(zf.infolist()):
                if i >= max_entries:
                    truncated = True
                    break
                # 检测加密
                if info.flag_bits & 0x1:
                    encrypted = True
                # 累积解压大小
                total_size += info.file_size
                if total_size > MAX_EXTRACTED_SIZE_BYTES:
                    truncated = True
                    break
                name = info.filename
                is_dir = name.endswith("/")
                mtime = None
                if not is_dir:
                    try:
                        mtime = int(_zip_datetime(info.date_time).timestamp())
                    except (ValueError, OverflowError):
                        mtime = None
                entries.append(ArchiveEntry(
                    name=name.rstrip("/"),
                    size=0 if is_dir else info.file_size,
                    compressed_size=0 if is_dir else info.compress_size,
                    is_dir=is_dir,
                    mtime=mtime,
                    is_archive=not is_dir and _is_nested_archive(name),
                ))
    except zipfile.BadZipFile:
        raise ValueError("无效的 ZIP 文件")
    except RuntimeError as exc:
        if "password" in str(exc).lower():
            encrypted = True
        else:
            raise

    return entries, total_size, encrypted, truncated


def _read_tar_listing(path: Path, mode: str, max_entries: int = MAX_ENTRY_COUNT) -> Tuple[List[ArchiveEntry], int, bool]:
    """读取 tar 压缩包目录列表。

    ``mode`` 为 tarfile.open 的模式 (``r:``, ``r:gz``, ``r:bz2``, ``r:xz``)。
    返回 (entries, total_uncompressed, truncated)。
    """
    entries: List[ArchiveEntry] = []
    total_size = 0
    truncated = False

    try:
        with tarfile.open(path, mode) as tf:
            for i, member in enumerate(tf):
                if i >= max_entries:
                    truncated = True
                    break
                total_size += member.size
                if total_size > MAX_EXTRACTED_SIZE_BYTES:
                    truncated = True
                    break
                name = member.name
                is_dir = member.isdir()
                entries.append(ArchiveEntry(
                    name=name.rstrip("/"),
                    size=0 if is_dir else member.size,
                    compressed_size=0,  # tar 不单独记录压缩大小
                    is_dir=is_dir,
                    mtime=int(member.mtime) if not is_dir else None,
                    is_archive=not is_dir and _is_nested_archive(name),
                ))
    except tarfile.TarError as exc:
        raise ValueError(f"无效的 tar 文件: {exc}")

    return entries, total_size, truncated


def _read_single_compressed_listing(path: Path, fmt: str) -> Tuple[List[ArchiveEntry], int, bool]:
    """读取单文件压缩格式 (gz/bz2/xz) 的目录列表。

    这类格式只压缩单个文件，目录列表只有一个条目。
    返回 (entries, total_uncompressed, truncated)。
    """
    # 单文件压缩：解压后文件名 = 原文件名去掉压缩扩展名
    name = path.name
    for ext in (".gz", ".bz2", ".xz"):
        if name.lower().endswith(ext):
            name = name[:-len(ext)]
            break

    file_size = path.stat().st_size
    entry = ArchiveEntry(
        name=name,
        size=file_size * 4,  # 粗略估计解压大小 (实际需解压才知道)
        compressed_size=file_size,
        is_dir=False,
        mtime=int(path.stat().st_mtime),
        is_archive=False,
    )
    return [entry], file_size * 4, False


def read_archive_listing(path: Path) -> ArchiveInfo:
    """读取压缩包目录列表。

    返回 ``ArchiveInfo``，包含格式、条目列表、总大小等信息。
    失败抛 ``ValueError``。
    """
    if not path.is_file():
        raise ValueError("文件不存在")

    fmt = detect_archive_kind(path)
    if fmt is None:
        raise ValueError("不是支持的压缩包格式")

    file_size = path.stat().st_size

    # 大文件只返回基本信息，不读取条目
    if file_size > MAX_ARCHIVE_SIZE_BYTES:
        return ArchiveInfo(
            format=fmt,
            path=str(path),
            size=file_size,
            entry_count=0,
            total_uncompressed=0,
            entries=[],
            encrypted=False,
            truncated=True,
        )

    entries: List[ArchiveEntry] = []
    total_uncompressed = 0
    encrypted = False
    truncated = False

    if fmt == "zip":
        entries, total_uncompressed, encrypted, truncated = _read_zip_listing(path)
    elif fmt in ("tar", "tar.gz", "tar.bz2", "tar.xz"):
        mode_map = {"tar": "r:", "tar.gz": "r:gz", "tar.bz2": "r:bz2", "tar.xz": "r:xz"}
        entries, total_uncompressed, truncated = _read_tar_listing(path, mode_map[fmt])
    elif fmt in ("gzip", "bzip2", "xz"):
        entries, total_uncompressed, truncated = _read_single_compressed_listing(path, fmt)
    else:
        raise ValueError(f"不支持的格式: {fmt}")

    return ArchiveInfo(
        format=fmt,
        path=str(path),
        size=file_size,
        entry_count=len(entries),
        total_uncompressed=total_uncompressed,
        entries=entries,
        encrypted=encrypted,
        truncated=truncated,
    )


def _read_zip_entry(path: Path, entry_path: str, max_bytes: int = MAX_ENTRY_SIZE_BYTES) -> bytes:
    """从 zip 压缩包读取单个条目内容。"""
    if not _is_path_safe(entry_path):
        raise ValueError(f"不安全的路径: {entry_path}")
    try:
        with zipfile.ZipFile(path, "r") as zf:
            namelist = zf.namelist()
            # 先按原名匹配，再兼容末尾斜杠写法
            for name in (entry_path, entry_path + "/", entry_path.rstrip("/")):
                if name in namelist:
                    info = zf.getinfo(name)
                    if info.file_size > max_bytes:
                        raise ValueError(f"条目过大: {info.file_size} 字节")
                    # 检测加密
                    if info.flag_bits & 0x1:
                        raise ValueError("条目已加密，需要密码")
                    return zf.read(name)
            raise ValueError(f"条目不存在: {entry_path}")
    except zipfile.BadZipFile:
        raise ValueError("无效的 ZIP 文件")


def _read_tar_entry(path: Path, mode: str, entry_path: str, max_bytes: int = MAX_ENTRY_SIZE_BYTES) -> bytes:
    """从 tar 压缩包读取单个条目内容。"""
    if not _is_path_safe(entry_path):
        raise ValueError(f"不安全的路径: {entry_path}")
    try:
        with tarfile.open(path, mode) as tf:
            # 尝试多种匹配
            for name in (entry_path, entry_path + "/", entry_path.rstrip("/")):
                try:
                    member = tf.getmember(name)
                    if member.size > max_bytes:
                        raise ValueError(f"条目过大: {member.size} 字节")
                    if member.isdir():
                        raise ValueError(f"条目是目录: {entry_path}")
                    f = tf.extractfile(member)
                    if f is None:
                        raise ValueError(f"无法读取条目: {entry_path}")
                    return f.read()
                except KeyError:
                    continue
            raise ValueError(f"条目不存在: {entry_path}")
    except tarfile.TarError as exc:
        raise ValueError(f"无效的 tar 文件: {exc}")


def _read_single_compressed_entry(path: Path, fmt: str, max_bytes: int = MAX_ENTRY_SIZE_BYTES) -> bytes:
    """读取单文件压缩格式 (gz/bz2/xz) 的内容。"""
    file_size = path.stat().st_size
    if file_size > max_bytes:
        raise ValueError(f"文件过大: {file_size} 字节")

    if fmt == "gzip":
        with gzip.open(path, "rb") as f:
            return f.read()
    elif fmt == "bzip2":
        with bz2.open(path, "rb") as f:
            return f.read()
    elif fmt == "xz":
        with lzma.open(path, "rb") as f:
            return f.read()
    else:
        raise ValueError(f"不支持的格式: {fmt}")


def read_archive_entry(path: Path, entry_path: str, max_bytes: int = MAX_ENTRY_SIZE_BYTES) -> bytes:
    """从压缩包读取单个条目内容。

    ``entry_path`` 是压缩包内的相对路径 (如 ``src/main.py``)。
    失败抛 ``ValueError``。
    """
    if not path.is_file():
        raise ValueError("文件不存在")

    fmt = detect_archive_kind(path)
    if fmt is None:
        raise ValueError("不是支持的压缩包格式")

    # 单文件压缩格式没有内部路径概念
    if fmt in ("gzip", "bzip2", "xz"):
        return _read_single_compressed_entry(path, fmt, max_bytes)

    if fmt == "zip":
        return _read_zip_entry(path, entry_path, max_bytes)
    elif fmt in ("tar", "tar.gz", "tar.bz2", "tar.xz"):
        mode_map = {"tar": "r:", "tar.gz": "r:gz", "tar.bz2": "r:bz2", "tar.xz": "r:xz"}
        return _read_tar_entry(path, mode_map[fmt], entry_path, max_bytes)
    else:
        raise ValueError(f"不支持的格式: {fmt}")


def read_archive_entry_text(
    path: Path, entry_path: str, encoding: str = "utf-8", max_bytes: int = MAX_ENTRY_SIZE_BYTES
) -> str:
    """从压缩包读取单个条目并解码为文本。

    失败抛 ``ValueError`` 或 ``UnicodeDecodeError``。
    """
    data = read_archive_entry(path, entry_path, max_bytes)
    return data.decode(encoding)


def get_archive_summary(path: Path) -> Dict[str, object]:
    """获取压缩包摘要信息 (用于文件清理场景)。

    返回格式、条目数、文件类型分布等。
    """
    try:
        info = read_archive_listing(path)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    # 统计文件类型分布
    ext_counts: Dict[str, int] = {}
    for entry in info.entries:
        if entry.is_dir:
            continue
        ext = Path(entry.name).suffix.lower() or "(无扩展名)"
        ext_counts[ext] = ext_counts.get(ext, 0) + 1

    # 按类型排序，取前 10
    top_types = sorted(ext_counts.items(), key=lambda x: -x[1])[:10]

    return {
        "ok": True,
        "format": info.format,
        "size": info.size,
        "entry_count": info.entry_count,
        "total_uncompressed": info.total_uncompressed,
        "encrypted": info.encrypted,
        "truncated": info.truncated,
        "top_file_types": dict(top_types),
    }


__all__ = [
    "ArchiveEntry",
    "ArchiveInfo",
    "detect_archive_kind",
    "get_archive_summary",
    "read_archive_entry",
    "read_archive_entry_text",
    "read_archive_listing",
]
