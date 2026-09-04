"""``runtime_validation``：runtime_exec 的输入校验层。

承担：

- 运行时路径必须是 regular file + 可执行；
- cwd 必须位于 workspace_root 内（避免路径遍历）；
- 源码大小、timeout 不超上限；
- 不允许在请求里设置敏感环境变量（如 ``SAGE_LOCAL_AUTH_TOKEN``）。

执行风险由 ``BaseTool.risk`` 与 ``PermissionEnforcer`` 控制，本模块
只负责结构性校验，不触碰权限语义。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

MAX_CODE_BYTES = 256 * 1024  # 单次执行 256 KiB
MIN_TIMEOUT_SECONDS = 1
MAX_TIMEOUT_SECONDS = 600

FORBIDDEN_ENV_KEYS = frozenset(
    {
        "SAGE_LOCAL_AUTH_TOKEN",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_ACCESS_KEY_ID",
        "GITHUB_TOKEN",
        "SAGE_LLM_API_KEY",
    }
)


class RuntimeValidationError(ValueError):
    """校验失败，由 ``runtime_exec`` 捕获并返回 ToolResult(success=False)。"""


def validate_runtime_path(
    path: str,
    *,
    workspace_root: Optional[Path],
) -> str:
    if not isinstance(path, str) or not path:
        raise RuntimeValidationError("runtime_path 不能为空")
    p = Path(path)
    if not p.is_file():
        raise RuntimeValidationError(f"runtime_path 不是 regular file: {path}")
    if not os.access(p, os.X_OK):
        raise RuntimeValidationError(f"runtime_path 不可执行: {path}")
    real = p.resolve()
    return str(real)


def validate_cwd(
    cwd: Optional[str],
    *,
    workspace_root: Path,
) -> Optional[str]:
    if cwd is None:
        return None
    target = Path(cwd).expanduser()
    real_target = target.resolve()
    real_root = workspace_root.resolve()
    try:
        real_target.relative_to(real_root)
    except ValueError as exc:
        raise RuntimeValidationError(
            f"cwd 必须位于 workspace_root 内: {cwd} 不在 {real_root}"
        ) from exc
    if not real_target.is_dir():
        raise RuntimeValidationError(f"cwd 不是目录: {cwd}")
    return str(real_target)


def validate_code_size(code: str) -> int:
    if not isinstance(code, str):
        raise RuntimeValidationError("code 必须是字符串")
    size = len(code.encode("utf-8"))
    if size > MAX_CODE_BYTES:
        raise RuntimeValidationError(
            f"code 大小 {size} 超过上限 {MAX_CODE_BYTES}"
        )
    return size


def validate_timeout(timeout: Optional[int]) -> int:
    if timeout is None:
        return 60
    if not isinstance(timeout, int) or timeout < MIN_TIMEOUT_SECONDS:
        raise RuntimeValidationError(
            f"timeout 必须为 >= {MIN_TIMEOUT_SECONDS} 的整数"
        )
    if timeout > MAX_TIMEOUT_SECONDS:
        raise RuntimeValidationError(
            f"timeout {timeout} 超过上限 {MAX_TIMEOUT_SECONDS}"
        )
    return timeout


def validate_env_overrides(env: Optional[dict]) -> dict:
    if not env:
        return {}
    sanitized: dict = {}
    for key, value in env.items():
        if not isinstance(key, str) or not key:
            raise RuntimeValidationError("env_overrides 的键必须是非空字符串")
        if key in FORBIDDEN_ENV_KEYS:
            raise RuntimeValidationError(f"禁止覆盖环境变量: {key}")
        if not isinstance(value, str):
            raise RuntimeValidationError(f"env_overrides[{key}] 必须是字符串")
        sanitized[key] = value
    return sanitized
