"""Windows 原生 reparse-safe 文件读写原语（R32，ctypes CreateFileW）。

等价于 POSIX ``O_NOFOLLOW`` 语义：
- 逐组件 ``GetFileAttributesW`` 检查 FILE_ATTRIBUTE_REPARSE_POINT
  （symlink / junction / 其他 reparse 点全部拒绝）；
- 最终打开自带 ``FILE_FLAG_OPEN_REPARSE_POINT`` —— 打开的是链接本身而非
  目标，打开后再经 ``GetFileInformationByHandle`` 复核 reparse 属性、目录
  类型与链接数，闭合 final-component TOCTOU 窗口。

设计参照 ``backend/tools/shell_resolver.py`` 的 kernel32 配置与注入模式：
``_kernel32`` 为模块属性，测试可 monkeypatch 注入假实现。

POSIX 平台一律抛 OSError（调用方各自决定降级策略），保证 fail-closed。
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Optional

# ---- Win32 常量（对照 shell_resolver.py / WinBase.h） ----
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_FILE_SHARE_DELETE = 0x00000004
_FILE_SHARE_NONE = 0
_OPEN_EXISTING = 3
_CREATE_NEW = 1
_CREATE_ALWAYS = 2
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_FILE_ATTRIBUTE_DIRECTORY = 0x10
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_BEGIN = 0
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_MOVEFILE_REPLACE_EXISTING = 0x1
_ERROR_FILE_NOT_FOUND = 2
_ERROR_PATH_NOT_FOUND = 3
_ERROR_ACCESS_DENIED = 5
_ERROR_FILE_EXISTS = 80
_ERROR_ALREADY_EXISTS = 183

_kernel32 = (
    ctypes.WinDLL("kernel32", use_last_error=True) if os.name == "nt" else None
)  # POSIX 上 WinDLL 不存在；公共函数在触碰 _kernel32 前均已早退


def _configure(kernel32) -> None:
    attributes = kernel32.GetFileAttributesW
    attributes.argtypes = [wintypes.LPCWSTR]
    attributes.restype = wintypes.DWORD

    create = kernel32.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE

    get_info = kernel32.GetFileInformationByHandle
    get_info.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    get_info.restype = wintypes.BOOL

    set_pointer = kernel32.SetFilePointer
    set_pointer.argtypes = [wintypes.HANDLE, wintypes.LONG, ctypes.c_void_p, wintypes.DWORD]
    set_pointer.restype = wintypes.DWORD

    set_eof = kernel32.SetEndOfFile
    set_eof.argtypes = [wintypes.HANDLE]
    set_eof.restype = wintypes.BOOL

    final_path = kernel32.GetFinalPathNameByHandleW
    final_path.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    final_path.restype = wintypes.DWORD

    write = kernel32.WriteFile
    write.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    write.restype = wintypes.BOOL

    read = kernel32.ReadFile
    read.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    read.restype = wintypes.BOOL

    close = kernel32.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    return attributes, create, final_path, close


class _FileInfo(ctypes.Structure):
    """BY_HANDLE_FILE_INFORMATION 的最小对齐副本。"""

    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTime", wintypes.FILETIME),
        ("ftLastAccessTime", wintypes.FILETIME),
        ("ftLastWriteTime", wintypes.FILETIME),
        ("dwVolumeSerialNumber", wintypes.DWORD),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("nNumberOfLinks", wintypes.DWORD),
        ("nFileIndexHigh", wintypes.DWORD),
        ("nFileIndexLow", wintypes.DWORD),
    ]


def _is_windows() -> bool:
    return os.name == "nt"


def _is_invalid_handle(handle) -> bool:
    """CreateFileW 失败返回 INVALID_HANDLE_VALUE；ctypes 可能给出
    18446744073709551615（无符号）或 -1（有符号），两者都要识别。"""
    return handle is None or handle in (_INVALID_HANDLE_VALUE, -1)


def verify_no_reparse(path: str) -> bool:
    """对已存在的组件检查 FILE_ATTRIBUTE_REPARSE_POINT。

    不存在的组件（write CREATE_NEW 的目标叶、缺失的父目录）无法有 reparse
    属性，直接放行 —— 缺失错误由后续打开语义（FileNotFoundError）表达。
    """
    if not _is_windows():
        return False
    attributes, _create, _final_path, _close = _configure(_kernel32)
    drive, tail = ntpath_splitdrive(path)
    parts = [part for part in tail.replace("/", "\\").split("\\") if part]
    current = drive + "\\"
    value = attributes(current)
    if value != 0xFFFFFFFF and value & _FILE_ATTRIBUTE_REPARSE_POINT:
        return False
    for part in parts:
        current = current.rstrip("\\") + "\\" + part
        value = attributes(current)
        if value == 0xFFFFFFFF:
            continue  # 组件不存在 → 不可能携带 reparse 点
        if value & _FILE_ATTRIBUTE_REPARSE_POINT:
            return False
    return True


def ntpath_splitdrive(path: str):
    import ntpath

    return ntpath.splitdrive(ntpath.normpath(path))


def _open_handle(
    path: str, *, write: bool, overwrite: bool
) -> Optional[ctypes.c_void_p]:
    desired = _GENERIC_WRITE if write else _GENERIC_READ
    share = _FILE_SHARE_NONE if write else (_FILE_SHARE_READ | _FILE_SHARE_WRITE)
    # 读：OPEN_EXISTING；写：CREATE_NEW（overwrite=False 原子建）/
    # CREATE_ALWAYS（overwrite=True 缺失即建、存在即截断；
    # OPEN_REPARSE_POINT 使打开 symlink 时得到链接本身，随后属性复核拒绝）
    disposition = _OPEN_EXISTING if not write else (
        _CREATE_NEW if not overwrite else _CREATE_ALWAYS
    )
    flags = _FILE_FLAG_OPEN_REPARSE_POINT
    handle = _kernel32.CreateFileW(
        path, desired, share, None, disposition, flags, None
    )
    handle_value = getattr(handle, "value", handle)
    if _is_invalid_handle(handle_value):
        error = ctypes.get_last_error()
        if error in (_ERROR_FILE_NOT_FOUND, _ERROR_PATH_NOT_FOUND):
            raise FileNotFoundError(error, os.strerror(error), path)
        if error in (_ERROR_FILE_EXISTS, _ERROR_ALREADY_EXISTS):
            raise FileExistsError(error, os.strerror(error), path)
        if error == _ERROR_ACCESS_DENIED:
            raise PermissionError(error, os.strerror(error), path)
        raise OSError(error, f"CreateFileW failed: {path}")
    return handle


def _validate_info(info: _FileInfo, path: str) -> None:
    if info.dwFileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        raise OSError(f"refusing reparse point: {path}")
    if info.dwFileAttributes & _FILE_ATTRIBUTE_DIRECTORY:
        raise NotADirectoryError(f"refusing directory handle: {path}")
    if info.nNumberOfLinks != 1:
        # “多链接”为 wiki/files 安全契约文案（test_wiki_path_security 依赖）
        raise OSError(f"refusing non-private file (多链接 links={info.nNumberOfLinks}): {path}")


def read_file_bound_reparse_safe(path: str) -> tuple[bytes, tuple[int, int, int]]:
    """读取整文件并返回 Windows 文件身份绑定（R32 切片 B）。

    返回 ``(data, identity)``，identity =
    ``(dwVolumeSerialNumber, nFileIndexHigh, nFileIndexLow)``，即 Windows
    版的 ``(st_dev, st_ino)``。读取前后各开一次句柄比对身份——路径指向的
    文件在读取期间被替换/篡改时抛 OSError。
    """
    return _read_with_double_open(path)


def _file_identity(handle, path: str) -> tuple[int, int, int]:
    info = _FileInfo()
    if not _kernel32.GetFileInformationByHandle(handle, ctypes.byref(info)):
        raise OSError(f"GetFileInformationByHandle failed: {path}")
    return (
        info.dwVolumeSerialNumber,
        info.nFileIndexHigh,
        info.nFileIndexLow,
    )


def _read_with_double_open(path: str) -> tuple[bytes, tuple[int, int, int]]:
    first = _open_single(path)
    identity_before = _file_identity(first, path)
    data = _read_all(first, path)
    identity_after = _file_identity(first, path)
    if identity_before != identity_after:
        raise OSError(f"脚本 inode 在读取期间发生变化: {path}")
    identity_first = identity_before
    _kernel32.CloseHandle(first)
    # 重新打开验证路径→同一文件（读取期间未被替换）
    second = _open_single(path)
    try:
        identity_second = _file_identity(second, path)
    finally:
        _kernel32.CloseHandle(second)
    if identity_first != identity_second:
        raise OSError(f"脚本路径在读取期间发生变化: {path}")
    return data, identity_first


def _open_single(path: str):
    handle = _kernel32.CreateFileW(
        path, _GENERIC_READ, _FILE_SHARE_READ, None, _OPEN_EXISTING,
        _FILE_FLAG_OPEN_REPARSE_POINT, None,
    )
    handle_value = getattr(handle, "value", handle)
    if _is_invalid_handle(handle_value):
        error = ctypes.get_last_error()
        if error in (_ERROR_FILE_NOT_FOUND, _ERROR_PATH_NOT_FOUND):
            raise FileNotFoundError(error, os.strerror(error), path)
        raise OSError(f"CreateFileW failed: {path}")
    info = _FileInfo()
    if not _kernel32.GetFileInformationByHandle(handle, ctypes.byref(info)):
        _kernel32.CloseHandle(handle)
        raise OSError(f"GetFileInformationByHandle failed: {path}")
    try:
        # 校验失败必须关闭句柄：SHARE_NONE 下泄漏会把同 inode 的其他
        # 硬链接一起锁死（W5 硬链接拒绝用例暴露）。
        _validate_info(info, path)
    except BaseException:
        _kernel32.CloseHandle(handle)
        raise
    return handle


def _read_all(handle, path: str) -> bytes:
    chunks = []
    while True:
        buf = ctypes.create_string_buffer(1024 * 1024)
        read_bytes = wintypes.DWORD(0)
        if not _kernel32.ReadFile(handle, buf, 1024 * 1024, ctypes.byref(read_bytes), None):
            raise OSError(f"ReadFile failed: {path}")
        if read_bytes.value == 0:
            break
        chunks.append(buf.raw[: read_bytes.value])
    return b"".join(chunks)


def read_file_reparse_safe(path: str) -> bytes:
    """读整文件（Windows reparse-safe）；非 Windows 或验证失败抛 OSError。"""
    if not _is_windows():
        raise OSError("reparse-safe read requires Windows")
    if not verify_no_reparse(path):
        raise OSError(f"refusing reparse component in path: {path}")
    _configure(_kernel32)
    # 目录预检：无 BACKUP_SEMANTICS 时打开目录会得到 ACCESS_DENIED，
    # 提前转成语义正确的 NotADirectoryError
    attributes, _create, _final_path, _close = _configure(_kernel32)
    value = attributes(path)
    if value != 0xFFFFFFFF and value & _FILE_ATTRIBUTE_DIRECTORY:
        raise NotADirectoryError(f"refusing directory handle: {path}")
    handle = _open_handle(path, write=False, overwrite=False)
    info = _FileInfo()
    if not _kernel32.GetFileInformationByHandle(handle, ctypes.byref(info)):
        _kernel32.CloseHandle(handle)
        raise OSError(f"GetFileInformationByHandle failed: {path}")
    try:
        _validate_info(info, path)
        size = (info.nFileSizeHigh << 32) | info.nFileSizeLow
        chunks = []
        offset = 0
        while True:
            buf = ctypes.create_string_buffer(1024 * 1024)
            read_bytes = wintypes.DWORD(0)
            ok = _kernel32.ReadFile(handle, buf, 1024 * 1024, ctypes.byref(read_bytes), None)
            if not ok:
                raise OSError(f"ReadFile failed: {path}")
            if read_bytes.value == 0:
                break
            chunks.append(buf.raw[: read_bytes.value])
            offset += read_bytes.value
            if size and offset >= size:
                break
        return b"".join(chunks)
    finally:
        _kernel32.CloseHandle(handle)


def _open_validated(path: str, disposition: int):
    """以指定 disposition 打开并复核（reparse/目录/多链接一律拒绝）。"""
    handle = _kernel32.CreateFileW(
        path,
        _GENERIC_WRITE,
        _FILE_SHARE_NONE,
        None,
        disposition,
        _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    handle_value = getattr(handle, "value", handle)
    if _is_invalid_handle(handle_value):
        error = ctypes.get_last_error()
        if error in (_ERROR_FILE_NOT_FOUND, _ERROR_PATH_NOT_FOUND):
            raise FileNotFoundError(error, os.strerror(error), path)
        if error in (_ERROR_FILE_EXISTS, _ERROR_ALREADY_EXISTS):
            raise FileExistsError(error, os.strerror(error), path)
        if error == _ERROR_ACCESS_DENIED:
            raise PermissionError(error, os.strerror(error), path)
        raise OSError(error, f"CreateFileW failed: {path}")
    info = _FileInfo()
    if not _kernel32.GetFileInformationByHandle(handle, ctypes.byref(info)):
        _kernel32.CloseHandle(handle)
        raise OSError(f"GetFileInformationByHandle failed: {path}")
    try:
        # 校验失败必须关闭句柄：SHARE_NONE 下泄漏会把同 inode 的其他
        # 硬链接一起锁死（W5 硬链接拒绝用例暴露）。
        _validate_info(info, path)
    except BaseException:
        _kernel32.CloseHandle(handle)
        raise
    return handle


def write_file_reparse_safe(
    path: str, data: bytes, *, overwrite: bool
) -> None:
    """写整文件（Windows reparse-safe）。

    overwrite=False → CREATE_NEW 原子建（已存在 → FileExistsError）；
    overwrite=True → 缺失即建；已存在则 OPEN_EXISTING 打开链接本体，
    **复核通过后才截断**（SetFilePointer+SetEndOfFile）——W5 修复：原
    CREATE_ALWAYS 会在句柄复核之前截断硬链接目标，放行"多链接拒绝"
    契约本应堵住的越界写入。
    """
    if not _is_windows():
        raise OSError("reparse-safe write requires Windows")
    if not verify_no_reparse(path):
        raise OSError(f"refusing reparse component in path: {path}")
    _configure(_kernel32)
    handle = None
    try:
        if not overwrite:
            handle = _open_validated(path, _CREATE_NEW)
        else:
            try:
                handle = _open_validated(path, _CREATE_NEW)
            except FileExistsError:
                handle = _open_validated(path, _OPEN_EXISTING)
                if _kernel32.SetFilePointer(handle, 0, None, _FILE_BEGIN) == 0xFFFFFFFF:
                    raise OSError(f"SetFilePointer failed: {path}")
                if not _kernel32.SetEndOfFile(handle):
                    raise OSError(f"SetEndOfFile failed: {path}")
        total = len(data)
        written = wintypes.DWORD(0)
        offset = 0
        while offset < total:
            chunk = data[offset : offset + 1024 * 1024]
            if not _kernel32.WriteFile(handle, chunk, len(chunk), ctypes.byref(written), None):
                raise OSError(f"WriteFile failed: {path}")
            if written.value == 0:
                raise OSError(f"WriteFile wrote 0 bytes: {path}")
            offset += written.value
    finally:
        if handle is not None:
            _kernel32.CloseHandle(handle)


def replace_file(src: str, dst: str) -> None:
    """同卷原子替换（MoveFileExW + REPLACE_EXISTING）。"""
    if not _is_windows():
        raise OSError("MoveFileExW replace requires Windows")
    move = _kernel32.MoveFileExW
    move.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    move.restype = wintypes.BOOL
    if not move(src, dst, _MOVEFILE_REPLACE_EXISTING):
        raise OSError(ctypes.get_last_error(), f"MoveFileExW failed: {src} -> {dst}")


def _open_osfhandle_or_close(handle, access: int) -> int:
    """把 Win32 句柄转成 CRT fd；失败时关闭句柄并抛 OSError。

    成功后 CRT 接管句柄所有权（os.close(fd) 即 CloseHandle）。
    """
    import msvcrt

    fd = msvcrt.open_osfhandle(handle, access | getattr(os, "O_NOINHERIT", 0))
    if fd == -1:
        _kernel32.CloseHandle(handle)
        raise OSError("open_osfhandle failed")
    return fd


def open_read_fd_reparse_safe(path: str) -> int:
    """打开 regular 文件并返回 CRT fd（reparse-safe，W5）。

    语义对齐 POSIX O_NOFOLLOW 打开：reparse/目录/多链接一律拒绝。
    返回的 CRT fd 归调用方所有（os.read / os.close）。
    """
    if not _is_windows():
        raise OSError("requires Windows")
    if not verify_no_reparse(path):
        raise OSError(f"refusing reparse component in path: {path}")
    _configure(_kernel32)
    attributes, _create, _final_path, _close = _configure(_kernel32)
    value = attributes(path)
    if value != 0xFFFFFFFF and value & _FILE_ATTRIBUTE_DIRECTORY:
        raise NotADirectoryError(f"refusing directory handle: {path}")
    handle = _open_handle(path, write=False, overwrite=False)
    info = _FileInfo()
    if not _kernel32.GetFileInformationByHandle(handle, ctypes.byref(info)):
        _kernel32.CloseHandle(handle)
        raise OSError(f"GetFileInformationByHandle failed: {path}")
    try:
        _validate_info(info, path)
        return _open_osfhandle_or_close(handle, os.O_RDONLY)
    except BaseException:
        _kernel32.CloseHandle(handle)
        raise


def create_new_write_fd_reparse_safe(path: str) -> int:
    """CREATE_NEW 原子建并返回 CRT fd（held-temp 契约，W5）。

    已存在 → FileExistsError；reparse/目录/多链接 → OSError。
    """
    if not _is_windows():
        raise OSError("requires Windows")
    if not verify_no_reparse(path):
        raise OSError(f"refusing reparse component in path: {path}")
    _configure(_kernel32)
    handle = _open_handle(path, write=True, overwrite=False)
    info = _FileInfo()
    if not _kernel32.GetFileInformationByHandle(handle, ctypes.byref(info)):
        _kernel32.CloseHandle(handle)
        raise OSError(f"GetFileInformationByHandle failed: {path}")
    try:
        _validate_info(info, path)
        return _open_osfhandle_or_close(handle, os.O_RDWR)
    except BaseException:
        _kernel32.CloseHandle(handle)
        raise
