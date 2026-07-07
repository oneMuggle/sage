"""SKILL.md 脚本执行沙箱（v2）。

- ``SandboxRequest``: 脚本执行请求（参数化）
- ``SandboxResult``: 脚本执行结果
- ``SandboxPort``: 沙箱端口协议（六边形出站边界）
- ``DEFAULT_ENV_DENYLIST``: 默认敏感环境变量黑名单

设计要点
--------

- ``SandboxPort`` 是 Protocol，定义了沙箱的统一接口
- ``DEFAULT_ENV_DENYLIST`` 包含常见 API key 和 secret 键名，防止脚本访问敏感凭据
- ``SandboxRequest`` 是不可变 dataclass，便于序列化和测试
- 实际实现（subprocess）在 ``backend/adapters/out/skill_script/subprocess_sandbox.py``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, Optional, Protocol, Tuple

# 默认敏感环境变量黑名单（防止子进程访问宿主机的密钥）
DEFAULT_ENV_DENYLIST: FrozenSet[str] = frozenset(
    {
        # 云服务凭据
        "AWS_SECRET_ACCESS_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SESSION_TOKEN",
        "AZURE_CLIENT_SECRET",
        "AZURE_TENANT_KEY",
        "GCP_SERVICE_ACCOUNT_KEY",
        # AI/LLM API keys
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "COHERE_API_KEY",
        "MISTRAL_API_KEY",
        # Git 平台
        "GITHUB_TOKEN",
        "GITLAB_TOKEN",
        "BITBUCKET_TOKEN",
        # 数据库
        "DATABASE_URL",
        "POSTGRES_PASSWORD",
        "MYSQL_PASSWORD",
        "MONGO_PASSWORD",
        "REDIS_PASSWORD",
        # 其他常见 secret
        "SECRET_KEY",
        "JWT_SECRET",
        "PRIVATE_KEY",
        "API_TOKEN",
        "AUTH_TOKEN",
    }
)


@dataclass(frozen=True)
class SandboxRequest:
    """脚本执行请求（不可变）。

    Args:
        script_path: 要执行的 Python 脚本路径（必须经 validate_resource_path 校验）
        args: 传递给脚本的命令行参数（不经过 shell，直接拼接为 argv）
        cwd: 子进程的工作目录（None = 脚本所在目录）
        env: 注入到子进程的环境变量（denylist 中的键会被过滤）
        timeout_s: 超时时间（秒），超过会被 kill
        stdin_data: 写入子进程 stdin 的字节数据（None = 不写入）
    """

    script_path: Path
    args: Tuple[str, ...] = ()
    cwd: Optional[Path] = None
    env: Dict[str, str] = field(default_factory=dict)
    timeout_s: float = 30.0
    stdin_data: Optional[bytes] = None


@dataclass(frozen=True)
class SandboxResult:
    """脚本执行结果。

    Args:
        success: 是否成功（exit_code == 0 且未超时且无异常）
        exit_code: 子进程退出码
        stdout: 标准输出（UTF-8 解码后的字符串）
        stderr: 标准错误（UTF-8 解码后的字符串）
        duration_ms: 执行时长（毫秒）
        timed_out: 是否超时
        error: 错误信息（None = 无错误）
    """

    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    error: Optional[str] = None


class SandboxPort(Protocol):
    """脚本执行沙箱端口（六边形出站边界）。

    所有沙箱实现必须实现 ``run`` 方法，返回 ``SandboxResult``。
    不抛异常 — 所有失败都通过 ``SandboxResult.success=False`` 和 ``error`` 字段表达。
    """

    async def run(self, req: SandboxRequest) -> SandboxResult:
        """执行沙箱请求。

        Args:
            req: 沙箱请求（不可变）

        Returns:
            ``SandboxResult``: 执行结果（永不抛异常）
        """
        ...
