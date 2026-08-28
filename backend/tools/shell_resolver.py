"""跨平台 shell 探测。

模型写出的命令按 POSIX shell 语法（``&&`` ``|`` ``$()``）组织，所以优先
找真 bash：POSIX 上是 ``/bin/bash``，Windows 上是 Git Bash。Windows 找不到
bash 时退 PowerShell，此时把 ``SHELL_FALLBACK_NOTE`` 放进工具结果——让模型
知道语法可能不适用，而不是对着看不懂的报错反复重试。

``release/win7`` 分支尤其依赖 PowerShell 降级路径：Win7 机器未必装 Git。

探测结果进程内缓存一次（``resolve_shell``）。测试用 ``resolve_shell_uncached``
绕过缓存。
"""

from __future__ import annotations

import functools
import ntpath
import os
import shutil
from dataclasses import dataclass
from typing import Optional, Tuple

#: PowerShell 降级时放进 ToolResult.content 的提示，供模型调整命令写法
SHELL_FALLBACK_NOTE = (
    "未找到 bash（已尝试 PATH 与 Git for Windows 安装目录），"
    "改用 PowerShell 执行。bash 专有语法（&&、||、$()、管道到 sh）可能不生效，"
    "请改用 PowerShell 等价写法。"
)

_POSIX_CANDIDATES: Tuple[Tuple[str, str], ...] = (
    ("/bin/bash", "bash"),
    ("/bin/sh", "sh"),
)

#: Git for Windows 默认安装位置下的 bash 相对路径
_GIT_BASH_RELATIVE = ntpath.join("Git", "bin", "bash.exe")


@dataclass(frozen=True)
class ShellSpec:
    """一次 shell 调用需要的全部信息。

    Attributes:
        executable:  shell 可执行文件路径
        args_prefix: 命令前的固定参数（bash 为 ``("-c",)``）
        kind:        ``"bash"`` / ``"sh"`` / ``"powershell"``
    """

    executable: str
    args_prefix: Tuple[str, ...]
    kind: str

    @property
    def is_fallback(self) -> bool:
        """是否为 PowerShell 降级（调用方据此附加 SHELL_FALLBACK_NOTE）。"""
        return self.kind == "powershell"


def _resolve_posix() -> ShellSpec:
    for path, kind in _POSIX_CANDIDATES:
        if os.path.exists(path):
            return ShellSpec(executable=path, args_prefix=("-c",), kind=kind)
    # 连 /bin/sh 都没有的 POSIX 系统极罕见；仍返回 /bin/sh 让 Popen 报
    # 具体的 FileNotFoundError，比在这里抛一个更模糊的异常有用。
    return ShellSpec(executable="/bin/sh", args_prefix=("-c",), kind="sh")


def _find_windows_bash() -> Optional[str]:
    from_path = shutil.which("bash")
    if from_path:
        return from_path
    for env_key in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        base = os.environ.get(env_key)
        if not base or not ntpath.isabs(base) or base.startswith(("\\\\", "//")):
            continue
        candidate = ntpath.join(base, _GIT_BASH_RELATIVE)
        if os.path.isfile(candidate):  # noqa: PTH113
            return candidate
    return None


def _resolve_windows() -> ShellSpec:
    bash_path = _find_windows_bash()
    if bash_path:
        return ShellSpec(executable=bash_path, args_prefix=("-c",), kind="bash")
    powershell = shutil.which("powershell") or "powershell.exe"
    return ShellSpec(
        executable=powershell,
        args_prefix=("-NoProfile", "-Command"),
        kind="powershell",
    )


def resolve_shell_uncached() -> ShellSpec:
    """探测可用 shell（不走缓存）。"""
    if os.name == "nt":
        return _resolve_windows()
    return _resolve_posix()


@functools.lru_cache(maxsize=1)
def resolve_shell() -> ShellSpec:
    """探测可用 shell（进程内缓存一次）。"""
    return resolve_shell_uncached()


__all__ = [
    "ShellSpec",
    "SHELL_FALLBACK_NOTE",
    "resolve_shell",
    "resolve_shell_uncached",
]
