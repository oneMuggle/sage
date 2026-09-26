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
from pathlib import Path, PurePath
from typing import Optional

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

#: (父目录名, 文件名) —— 仅在特定目录下敏感
_SENSITIVE_IN_DIR = frozenset({
    (".aws", "credentials"),
    (".docker", "config.json"),
    (".kube", "config"),
    ("gcloud", "credentials.db"),
    ("gcloud", "access_tokens.db"),
})

#: ``.ssh`` 下放行的非机密文件
_SSH_PUBLIC_NAMES = frozenset({"known_hosts", "known_hosts.old", "config", "authorized_keys"})


def sensitive_path_reason(path: str) -> Optional[str]:  # noqa: PLR0911 — 规则表逐条早返回
    """命中凭据规则返回原因描述，否则 ``None``。只看路径，不读文件。"""
    if not isinstance(path, str) or not path:
        return None
    pure = PurePath(str(Path(path).expanduser()).replace("\\", "/"))
    name = pure.name.lower()
    parent = pure.parent.name.lower()
    parts = [p.lower() for p in pure.parts]

    if name.endswith(".pub"):
        return None
    if name in _SENSITIVE_NAMES:
        return f"凭据文件名 {pure.name!r}"
    if name.startswith(".env."):
        if name[len(".env."):] in _ENV_TEMPLATE_SUFFIXES:
            return None
        return f"环境变量文件 {pure.name!r}"
    suffix = pure.suffix.lower()
    if suffix in _SENSITIVE_SUFFIXES:
        return f"密钥/证书扩展名 {suffix!r}"
    if (parent, name) in _SENSITIVE_IN_DIR:
        return f"凭据文件 {parent}/{pure.name}"
    if ".ssh" in parts[:-1] and name not in _SSH_PUBLIC_NAMES:
        return f"SSH 目录下的私密文件 {pure.name!r}"
    return None


def _sensitive_guard_disabled() -> bool:
    return os.environ.get(ALLOW_SENSITIVE_ENV, "").strip().lower() in {"1", "true", "yes"}


def check_sensitive_path(path: str, operation: str) -> Optional[ToolResult]:
    """凭据路径守卫；返回 ``None`` 放行，否则返回拒绝结果。"""
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


__all__ = [
    "ALLOW_SENSITIVE_ENV",
    "NEW_FILE_VERSION",
    "VERSION_PREFIX",
    "check_expected_version",
    "check_sensitive_path",
    "compute_bytes_version",
    "compute_file_version",
    "sensitive_path_reason",
]
