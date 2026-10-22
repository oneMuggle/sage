"""远程工作区路径校验（对齐 LocalBridge ``files.cjs`` 的 ``parts()`` / ``resolve()``）。

远程 Agent 只能使用**相对于工作区根**的路径，规则比 Sage 内部文件工具更严：

1. 只接受相对路径；拒绝绝对路径、``/`` 或 ``\\`` 开头、控制字符、``:``
   （NTFS 备用数据流 / 盘符）、长度 > 1000；
2. 拒绝空段、``..``、以点或空格结尾的段、Windows 保留设备名；
3. 受保护路径：LocalBridge 规则 ∪ ``file_guard`` 凭据规则；``.git`` 读写均拒绝；
4. 逐段 ``lstat``：任一段为符号链接 / junction 即拒绝；最终 realpath 复核在根内。
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import List, Optional

from backend.tools.file_guard import sensitive_path_reason

MAX_PATH_LENGTH = 1000

_CONTROL_OR_COLON = re.compile(r"[\x00-\x1f:]")
_RESERVED = re.compile(r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\.|$)", re.IGNORECASE)

#: 任一段命中即拒绝读写（LocalBridge 列表 + .git）
PROTECTED_SEGMENTS = frozenset({".git", ".ssh", ".aws", ".azure", ".gnupg"})

#: 只拒绝写入的目录段（依赖源码可读，不可改）
WRITE_PROTECTED_SEGMENTS = frozenset({"node_modules"})

#: 列表 / 搜索时跳过的噪声目录（不是安全规则）
SKIP_WALK_SEGMENTS = frozenset({"node_modules", "__pycache__", ".venv", "venv", "dist", "build"})


class RemotePathError(ValueError):
    """路径被拒绝；``str(exc)`` 以 ``PATH_DENIED:`` 开头，可直接返回给远程 Agent。"""


def _deny(reason: str) -> RemotePathError:
    return RemotePathError(f"PATH_DENIED: {reason}")


def split_relative(relative: str) -> List[str]:
    """校验并切分相对路径；返回去掉 ``.`` 段后的路径段列表（``"."`` → ``[]``）。"""
    if not isinstance(relative, str) or not relative:
        raise _deny("relative workspace path required")
    if len(relative) > MAX_PATH_LENGTH:
        raise _deny("path too long")
    if _CONTROL_OR_COLON.search(relative):
        raise _deny("control characters and ':' are not allowed")
    if relative.startswith(("/", "\\")) or Path(relative).is_absolute():
        raise _deny("relative workspace path required")
    segments = relative.replace("\\", "/").split("/")
    for segment in segments:
        if segment == ".":
            continue
        if not segment or segment == "..":
            raise _deny("empty or '..' path component")
        if segment != segment.rstrip(". "):
            raise _deny(f"path component {segment!r} ends with dot or space")
        if _RESERVED.match(segment):
            raise _deny(f"reserved device name {segment!r}")
    parts = [s for s in segments if s != "."]
    if len(parts) > 1 and parts[-1] == "":
        parts = parts[:-1]
    return parts


def protected_reason(parts: List[str], *, write: bool) -> Optional[str]:
    """受保护路径判定（基于已校验的路径段）。"""
    lowered = [p.lower() for p in parts]
    for segment in lowered:
        if segment in PROTECTED_SEGMENTS:
            return f"protected directory {segment!r}"
        if write and segment in WRITE_PROTECTED_SEGMENTS:
            return f"write-protected directory {segment!r}"
    if parts:
        reason = sensitive_path_reason("/".join(parts))
        if reason:
            return f"credential path ({reason})"
    return None


def is_hidden_entry(name: str) -> bool:
    """列目录时应隐藏的条目名（非法名 / 受保护名）。"""
    try:
        parts = split_relative(name)
    except RemotePathError:
        return True
    return protected_reason(parts, write=False) is not None


def resolve(root: str, relative: str, *, write: bool = False, may_create: bool = False) -> str:
    """把远程相对路径解析为工作区内的绝对路径；任何违规抛 :class:`RemotePathError`。

    ``may_create=True`` 允许最后一段尚不存在（新建文件）；中间目录必须已存在
    （与 LocalBridge 一致：远程写入不隐式创建目录树）。
    """
    parts = split_relative(relative)
    reason = protected_reason(parts, write=write)
    if reason:
        raise _deny(reason)
    canonical = os.path.realpath(root)
    current = canonical
    for index, segment in enumerate(parts):
        current = os.path.join(current, segment)
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            if may_create and index == len(parts) - 1:
                return current
            raise _deny("path does not exist") from None
        if stat.S_ISLNK(info.st_mode) or _is_junction(current, info):
            raise _deny("symlinks/junctions are not allowed")
    actual = os.path.realpath(current)
    if os.path.normcase(actual) != os.path.normcase(canonical) and not os.path.normcase(
        actual
    ).startswith(os.path.normcase(canonical) + os.sep):
        raise _deny("outside workspace")
    return actual


def _is_junction(path: str, info: os.stat_result) -> bool:
    """Windows junction / 其他 reparse point 检测（py38 无 ``os.path.isjunction``）。"""
    attrs = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if attrs & reparse_flag:
        return True
    return bool(getattr(os.path, "isjunction", lambda _p: False)(path))


def to_relative(root: str, absolute: str) -> str:
    """绝对路径 → 以 ``/`` 分隔的工作区相对路径（用于回显给远程 Agent）。"""
    rel = os.path.relpath(absolute, os.path.realpath(root))
    return "." if rel == "." else Path(rel).as_posix()


__all__ = [
    "PROTECTED_SEGMENTS",
    "SKIP_WALK_SEGMENTS",
    "RemotePathError",
    "is_hidden_entry",
    "protected_reason",
    "resolve",
    "split_relative",
    "to_relative",
]
