"""文件写入乐观锁 + 凭据路径守卫（LocalBridge 借鉴 P0，见
``docs/plans/2026-09-26-localbridge-p0-safety.md``）。

两项能力，均为纯函数、不依赖 FastAPI，可单测：

1. **内容版本（乐观并发控制）**：``read_file`` 返回 ``version``
   （``sha256:<hex>``，按磁盘原始字节计算）；``write_file`` / ``edit_file`` /
   ``apply_patch`` 可选携带 ``expected_version``：

   - 省略 → 不校验（向后兼容）；
   - ``"new"`` → 目标必须不存在（仅创建，防覆盖他人刚写的新文件）；
   - ``"sha256:..."`` → 目标必须存在且当前版本一致，否则
     ``version_conflict``，要求重新读取后再改。

   用途：主代理 / 子代理 / 用户并行编辑同一文件时，防止基于过期内容的
   写入静默覆盖他人改动。进程内校验不防御恶意本机进程的 TOCTOU 竞态。

2. **凭据路径守卫**：对 LLM 文件工具（读 / 写 / 编辑）拒绝常见凭据文件
   （``.env``、SSH 私钥、``*.pem``、``.git-credentials`` 等）。这不是完整
   DLP —— 普通命名的私密文件仍可能被读取；bash 等执行类工具也不受本
   守卫约束（由权限模式与审批兜底）。设置环境变量
   ``SAGE_ALLOW_SENSITIVE_PATHS=1`` 可整体关闭（调试 / 明确知情场景）。
"""

from __future__ import annotations

import hashlib
import os
import threading
import uuid
from contextlib import contextmanager, suppress
from pathlib import Path, PurePath
from typing import Callable, Iterable, Iterator, List, Optional, Set

from .base import ToolResult

VERSION_PREFIX = "sha256:"
NEW_FILE_VERSION = "new"
_HASH_CHUNK = 1024 * 1024

ALLOW_SENSITIVE_ENV = "SAGE_ALLOW_SENSITIVE_PATHS"


# ── 内容版本 ─────────────────────────────────────────────────────────


def compute_file_version(path: str) -> str:
    """按磁盘原始字节计算 ``sha256:<hex>`` 版本号（流式，不整读入内存）。"""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return VERSION_PREFIX + digest.hexdigest()


def compute_bytes_version(data: bytes) -> str:
    """内存字节的版本号（写入后回传新版本，免二次读盘）。"""
    return VERSION_PREFIX + hashlib.sha256(data).hexdigest()


def _is_valid_version_token(expected: str) -> bool:
    if expected == NEW_FILE_VERSION:
        return True
    if not expected.startswith(VERSION_PREFIX):
        return False
    hex_part = expected[len(VERSION_PREFIX):]
    return len(hex_part) == 64 and all(c in "0123456789abcdef" for c in hex_part.lower())


def check_expected_version(  # noqa: PLR0911 — 守卫式早返回：一种冲突一分支
    path: str, expected: Optional[str]
) -> Optional[ToolResult]:
    """校验 ``expected_version``；返回 ``None`` 放行，否则返回拒绝结果。"""
    if expected is None:
        return None
    if not isinstance(expected, str) or not _is_valid_version_token(expected.strip()):
        return ToolResult(
            success=False,
            error=(
                "invalid_expected_version: expected_version 必须是 read_file 返回的 "
                "'sha256:<64 位十六进制>'，或 'new' 表示仅创建新文件"
            ),
        )
    expected = expected.strip().lower()
    exists = Path(path).exists()
    if expected == NEW_FILE_VERSION:
        if exists:
            return ToolResult(
                success=False,
                error=(
                    "version_conflict: expected_version='new' 但文件已存在；"
                    "请先 read_file 获取当前 version 再决定是否覆盖"
                ),
            )
        return None
    if not exists:
        return ToolResult(
            success=False,
            error="version_conflict: 文件已不存在（可能被他人删除或移动），请重新确认目标",
        )
    try:
        actual = compute_file_version(path)
    except OSError as exc:
        return ToolResult(success=False, error=f"version_check_failed: 无法读取文件计算版本: {exc}")
    if actual != expected:
        return ToolResult(
            success=False,
            error=(
                f"version_conflict: 文件自上次读取后已被修改（expected {expected[:19]}…，"
                f"actual {actual[:19]}…）；请重新 read_file 后基于最新内容再修改，"
                "不要盲目重试"
            ),
        )
    return None


# ── 凭据路径守卫 ─────────────────────────────────────────────────────

#: 精确文件名（小写比较）
_SENSITIVE_NAMES = frozenset({
    ".env",
    ".git-credentials",
    ".netrc",
    "_netrc",
    ".pgpass",
    ".pypirc",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_ecdsa_sk",
    "id_ed25519_sk",
})

#: 扩展名（小写比较）
_SENSITIVE_SUFFIXES = frozenset({
    ".pem",
    ".key",
    ".pfx",
    ".p12",
    ".jks",
    ".keystore",
    ".kdbx",
    ".ppk",
})

#: ``.env.*`` 中允许的模板类文件（不含真实凭据的约定命名）
_ENV_TEMPLATE_SUFFIXES = frozenset({"example", "sample", "template", "dist", "defaults"})

#: 整个目录视为凭据目录（路径任意一段命中即拒绝；LocalBridge files.cjs 同款）
_SENSITIVE_DIRS = frozenset({".aws", ".azure"})

#: 任意位置的同名文件都视为凭据（LocalBridge: ``credentials``）
_SENSITIVE_ANYWHERE = frozenset({"credentials"})

#: (父目录名, 文件名) —— 仅在特定目录下敏感
_SENSITIVE_IN_DIR = frozenset({
    (".docker", "config.json"),
    (".kube", "config"),
    ("gcloud", "credentials.db"),
    ("gcloud", "access_tokens.db"),
})

#: ``.ssh`` 下放行的非机密文件
_SSH_PUBLIC_NAMES = frozenset({"known_hosts", "known_hosts.old", "config", "authorized_keys"})

#: Windows 保留设备名（可带扩展名：``nul.txt`` 同样指向设备）
_WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(10)}
    | {f"lpt{i}" for i in range(10)}
)


def _normalize_segment(segment: str) -> str:
    """模拟 Win32 路径规范化：去掉段尾的点与空格（``.env.`` / ``id_rsa `` → 原名）。

    ``.`` / ``..`` 保持原样。判定一律基于规范化后的小写名，防止用段尾
    点/空格绕过黑名单（Windows 打开 ``id_rsa.`` 实际打开的是 ``id_rsa``）。
    """
    if segment in (".", ".."):
        return segment
    return segment.rstrip(". ").lower()


def _split_segments(path: str) -> List[str]:
    text = str(Path(path).expanduser()).replace("\\", "/")
    return [seg for seg in text.split("/") if seg]


def sensitive_path_reason(path: str) -> Optional[str]:  # noqa: PLR0911 — 规则表逐条早返回
    """命中凭据规则返回原因描述，否则 ``None``。只看路径，不读文件。"""
    if not isinstance(path, str) or not path:
        return None
    segments = [_normalize_segment(seg) for seg in _split_segments(path)]
    if not segments:
        return None
    name = segments[-1]
    parent = segments[-2] if len(segments) > 1 else ""
    dirs = segments[:-1]

    for directory in dirs:
        if directory in _SENSITIVE_DIRS:
            return f"凭据目录 {directory}/"
    if name.endswith(".pub"):
        return None
    if name in _SENSITIVE_NAMES or name in _SENSITIVE_ANYWHERE:
        return f"凭据文件名 {name!r}"
    if name.startswith(".env."):
        if name[len(".env."):] in _ENV_TEMPLATE_SUFFIXES:
            return None
        return f"环境变量文件 {name!r}"
    suffix = PurePath(name).suffix
    if suffix in _SENSITIVE_SUFFIXES:
        return f"密钥/证书扩展名 {suffix!r}"
    if (parent, name) in _SENSITIVE_IN_DIR:
        return f"凭据文件 {parent}/{name}"
    if ".ssh" in dirs and name not in _SSH_PUBLIC_NAMES:
        return f"SSH 目录下的私密文件 {name!r}"
    return None


def git_internal_reason(path: str) -> Optional[str]:
    """路径位于 ``.git`` 目录内返回原因（写 ``.git/hooks`` 等价于任意代码执行）。"""
    if not isinstance(path, str) or not path:
        return None
    for segment in _split_segments(path)[:-1]:
        if _normalize_segment(segment) == ".git":
            return "git 内部目录 .git/（hooks / config 可导致代码执行）"
    return None


def invalid_windows_path_reason(path: str) -> Optional[str]:
    """写入目标的 Windows 路径合法性（LocalBridge ``parts()`` 同款）。

    - 盘符之外出现 ``:`` → NTFS 备用数据流（``a.txt:hidden``）；
    - 段尾为点或空格 → Windows 会静默截掉，可用于绕过名称规则；
    - 保留设备名（``nul`` / ``con`` / ``com1`` …，可带扩展名）。
    跨平台一致执行：仓库需在 Windows 上可检出，这类名字本就不应出现。
    """
    if not isinstance(path, str) or not path:
        return None
    text = str(Path(path).expanduser()).replace("\\", "/")
    body = text[2:] if len(text) >= 2 and text[1] == ":" and text[0].isalpha() else text
    if ":" in body:
        return "路径含 ':'（NTFS 备用数据流）"
    for segment in _split_segments(body):
        if segment in (".", ".."):
            continue
        if segment != segment.rstrip(". "):
            return f"路径段 {segment!r} 以点或空格结尾"
        if segment.split(".", 1)[0].lower() in _WINDOWS_RESERVED:
            return f"Windows 保留设备名 {segment!r}"
    return None


def _sensitive_guard_disabled() -> bool:
    return os.environ.get(ALLOW_SENSITIVE_ENV, "").strip().lower() in {"1", "true", "yes"}


def check_sensitive_path(path: str, operation: str, *, write: bool = False) -> Optional[ToolResult]:
    """凭据路径守卫；返回 ``None`` 放行，否则返回拒绝结果。

    ``write=True`` 额外执行 Windows 路径合法性与 ``.git`` 内部目录检查
    （这两项不受 ``SAGE_ALLOW_SENSITIVE_PATHS`` 开关影响）。
    """
    if write:
        reason = invalid_windows_path_reason(path) or git_internal_reason(path)
        if reason is not None:
            return ToolResult(success=False, error=f"path_denied: 拒绝{operation}（{reason}）")
    if _sensitive_guard_disabled():
        return None
    reason = sensitive_path_reason(path)
    if reason is None:
        return None
    return ToolResult(
        success=False,
        error=(
            f"sensitive_path_blocked: 拒绝{operation}（{reason}）。凭据类文件不经由 "
            "LLM 文件工具读写；如确需操作请由用户手动处理"
        ),
    )


# ── 写入互斥 + 原子替换（LocalBridge files.cjs write() 同款）──────────

_busy_paths: Set[str] = set()
_busy_guard = threading.Lock()


def _lock_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(str(Path(path).expanduser())))


@contextmanager
def file_write_lock(paths: Iterable[str]) -> Iterator[Optional[ToolResult]]:
    """进程内写互斥：任一路径正被写入则 yield 拒绝结果（``file_busy``），不排队等待。

    用法::

        with file_write_lock([p]) as busy:
            if busy is not None:
                return busy
            ...
    """
    keys = sorted({_lock_key(p) for p in paths})
    with _busy_guard:
        taken = [k for k in keys if k in _busy_paths]
        if not taken:
            _busy_paths.update(keys)
    if taken:
        yield ToolResult(
            success=False,
            error="file_busy: 该文件正被另一个写操作占用，请稍后重新读取再修改",
        )
        return
    try:
        yield None
    finally:
        with _busy_guard:
            _busy_paths.difference_update(keys)


def atomic_write(
    path: str,
    write_temp: Callable[[str], None],
    expected_version: Optional[str] = None,
) -> Optional[ToolResult]:
    """同目录临时文件 → （可选）替换前复核版本 → ``os.replace`` 原子替换。

    ``write_temp(tmp_path)`` 负责把内容写进临时文件（调用方决定编码/换行）。
    复核失败返回 ``version_conflict``；目标被其他程序独占导致 replace 失败
    （Windows ``PermissionError``）时回退为原地写入，保证可用性。
    临时文件在任何路径上都会被清理。只防协作客户端，不防恶意本机进程。
    """
    target = str(Path(path).expanduser())
    directory = os.path.dirname(os.path.abspath(target))
    temp = os.path.join(directory, f".sage-{uuid.uuid4().hex}.tmp")
    try:
        write_temp(temp)
        if expected_version is not None:
            conflict = check_expected_version(target, expected_version)
            if conflict is not None:
                return ToolResult(
                    success=False,
                    error="version_conflict: 写入过程中文件被他人修改，已放弃本次写入；"
                    + (conflict.error or ""),
                )
        try:
            Path(temp).replace(target)
        except PermissionError:
            with open(temp, "rb") as src, open(target, "wb") as dst:
                dst.write(src.read())
        return None
    finally:
        with suppress(OSError):
            Path(temp).unlink(missing_ok=True)


__all__ = [
    "ALLOW_SENSITIVE_ENV",
    "NEW_FILE_VERSION",
    "VERSION_PREFIX",
    "check_expected_version",
    "atomic_write",
    "check_sensitive_path",
    "file_write_lock",
    "git_internal_reason",
    "invalid_windows_path_reason",
    "compute_bytes_version",
    "compute_file_version",
    "sensitive_path_reason",
]
