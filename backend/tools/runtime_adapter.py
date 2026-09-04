"""Runtime Adapter 协议与注册表。

适配器是 ``runtime_probe`` / ``runtime_exec`` / ``project_diagnose``
与具体语言实现之间的解耦层：

- 每个 ``RuntimeAdapter`` 只负责一种语言的发现、版本探测、命令构造
  和项目诊断。
- 适配器不直接调用 ``subprocess.run``，统一使用
  ``safe_run`` 提供的超时、输出上限和进程组回收。
- 安全策略（路径校验、cwd 限制、审批）由 ``runtime_validation`` 和
  ``runtime_exec`` 工具负责；适配器**不得**自行越过。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Protocol

from backend.domain.runtime import (
    Diagnostic,
    ExecutionRequest,
    ProbeRequest,
    ProbeResult,
    ProjectDiagnosis,
    ProjectManifest,
    RuntimeInfo,
    RuntimeSource,
)


@dataclass(frozen=True)
class CommandRequest:
    """适配器构造出的执行命令，由 runtime_exec 实际启动。"""

    argv: List[str]
    stdin_payload: Optional[str] = None
    env: Optional[dict] = None
    cleanup_paths: tuple[Path, ...] = ()


@dataclass(frozen=True)
class SafeRunResult:
    """``safe_run`` 的最小结果包装。"""

    exit_code: Optional[int]
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    output_truncated: bool = False
    error: Optional[str] = None


class SafeRunFunc(Protocol):
    """工具运行时提供的安全子进程调用签名。"""

    def __call__(
        self,
        argv: List[str],
        *,
        timeout: float,
        cwd: Optional[Path] = None,
        env: Optional[dict] = None,
        input_text: Optional[str] = None,
    ) -> SafeRunResult: ...


@dataclass
class AdapterContext:
    """适配器在调用时获得的上下文（cwd 根目录、safe_run 注入等）。"""

    workspace_root: Path
    safe_run: SafeRunFunc


class RuntimeAdapter(Protocol):
    """单一语言的运行时适配器协议。"""

    language: str

    def discover(
        self,
        request: ProbeRequest,
        ctx: AdapterContext,
    ) -> List[RuntimeInfo]:
        """发现本机可用的运行时实例；不抛错时返回已收集到的结果。"""

    def inspect(
        self,
        runtime: RuntimeInfo,
        ctx: AdapterContext,
    ) -> RuntimeInfo:
        """补充运行时版本、能力等信息。"""

    def build_command(
        self,
        request: ExecutionRequest,
        runtime: RuntimeInfo,
        ctx: AdapterContext,
    ) -> CommandRequest:
        """构造执行命令，必须使用 argv 数组，禁止 shell 拼接。"""

    def diagnose(
        self,
        project_root: Path,
        runtimes: List[RuntimeInfo],
        ctx: AdapterContext,
    ) -> ProjectDiagnosis:
        """根据项目清单和已发现的运行时生成诊断。"""

    def discover_manifests(
        self,
        project_root: Path,
    ) -> List[ProjectManifest]:
        """扫描项目目录，识别该语言相关的清单文件。"""


class AdapterRegistry:
    """运行时适配器注册中心。"""

    def __init__(self) -> None:
        self._adapters: dict[str, RuntimeAdapter] = {}

    def register(self, adapter: RuntimeAdapter) -> None:
        language = adapter.language.lower()
        if language in self._adapters:
            raise ValueError(f"runtime adapter already registered: {language}")
        self._adapters[language] = adapter

    def get(self, language: str) -> Optional[RuntimeAdapter]:
        return self._adapters.get(language.lower())

    def languages(self) -> List[str]:
        return sorted(self._adapters)

    def all(self) -> Iterable[RuntimeAdapter]:
        return list(self._adapters.values())


# 模块级单例，由 ``register_all_adapters`` 在启动时注入。
registry = AdapterRegistry()


def classify_python_source(env_python: str, prefix: str) -> RuntimeSource:
    """从解释器路径推断运行时来源，仅用于诊断显示。"""

    p = env_python.lower()
    if "/anaconda" in p or "/miniconda" in p or "/conda" in p:
        return RuntimeSource.CONDA
    if "/.venv/" in p or p.endswith("/venv/bin/python") or "/venv/" in p:
        return RuntimeSource.VENV
    if p.startswith(prefix.lower()):
        return RuntimeSource.PROJECT
    return RuntimeSource.SYSTEM
