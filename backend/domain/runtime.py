"""运行时与本地开发环境助手领域模型。

本模块属于 backend.domain 层（零外部依赖），定义 runtime_probe、
runtime_exec、project_diagnose 三个工具共享的领域结构。语言细节
（如如何探测 conda 环境、如何解析 package.json）由 ``tools/adapters``
实现，本模块只描述数据形态。

约定：

- ``language`` 取小写 ASCII 名（``python``、``javascript`` 等），用于
  跨语言路由。
- ``source`` 描述运行时来自哪一类环境（系统 PATH / conda / venv / 项目
  本地 / 其他），避免向模型泄露绝对敏感信息。
- ``version`` 是字符串，因为不同运行时的版本语义差异较大，统一交给
  ``RuntimeAdapter`` 在 ``diagnose`` 中按需做语义比较。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class RuntimeSource(str, Enum):
    """运行时来源分类，仅用于诊断与 UI 渲染。"""

    SYSTEM = "system"
    CONDA = "conda"
    VENV = "venv"
    PROJECT = "project"
    TOOLCHAIN = "toolchain"
    UNKNOWN = "unknown"


class DiagnosticLevel(str, Enum):
    """项目诊断结果等级。"""

    SATISFIED = "satisfied"
    PARTIAL = "partial"
    UNSATISFIED = "unsatisfied"


class DiagnosticSeverity(str, Enum):
    """单条诊断的严重程度。"""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class RuntimeCapability:
    """运行时支持的副作用能力描述。"""

    can_execute: bool = False
    can_package_check: bool = False
    supports_stdin_source: bool = True
    supports_tempfile_source: bool = True
    notes: str = ""


@dataclass(frozen=True)
class RuntimeInfo:
    """单个运行时实例的探测结果。"""

    language: str
    name: str
    path: str
    version: str
    source: RuntimeSource = RuntimeSource.UNKNOWN
    is_default: bool = False
    is_compatible: Optional[bool] = None
    compatibility_notes: tuple[str, ...] = field(default_factory=tuple)
    capabilities: RuntimeCapability = field(default_factory=RuntimeCapability)
    diagnostics: tuple[str, ...] = field(default_factory=tuple)
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProbeRequest:
    """runtime_probe 工具的领域表示。"""

    languages: tuple[str, ...] = ()
    include_tools: bool = True
    target_version: Optional[str] = None
    include_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProbeResult:
    """runtime_probe 工具的领域结果。"""

    runtimes: List[RuntimeInfo]
    recommended: Optional[str] = None
    errors: tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "runtimes": [_runtime_to_dict(item) for item in self.runtimes],
            "recommended": self.recommended,
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class ExecutionRequest:
    """runtime_exec 工具的领域表示。"""

    language: str
    runtime_path: str
    code: str
    cwd: Optional[str] = None
    timeout: int = 60
    run_in_background: bool = False
    env_overrides: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionResult:
    """runtime_exec 工具的领域结果。"""

    exit_code: Optional[int]
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    output_truncated: bool = False
    error: Optional[str] = None
    command: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_seconds": round(self.duration_seconds, 4),
            "timed_out": self.timed_out,
            "output_truncated": self.output_truncated,
            "error": self.error,
            "command": list(self.command) if self.command else None,
        }


@dataclass(frozen=True)
class ProjectManifest:
    """识别到的项目清单。"""

    language: str
    path: str
    kind: str
    requires: tuple[str, ...] = ()
    extras: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Diagnostic:
    """项目诊断的单条记录。"""

    code: str
    severity: DiagnosticSeverity
    message: str
    remediation: Optional[str] = None
    related_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "remediation": self.remediation,
            "related_path": self.related_path,
        }


@dataclass(frozen=True)
class ProjectDiagnosis:
    """project_diagnose 工具的领域结果。"""

    level: DiagnosticLevel
    diagnostics: List[Diagnostic]
    manifests: List[ProjectManifest]
    recommended_runtime: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level.value,
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "manifests": [
                {
                    "language": m.language,
                    "path": m.path,
                    "kind": m.kind,
                    "requires": list(m.requires),
                    "extras": m.extras,
                }
                for m in self.manifests
            ],
            "recommended_runtime": self.recommended_runtime,
        }


def _runtime_to_dict(item: RuntimeInfo) -> Dict[str, Any]:
    return {
        "language": item.language,
        "name": item.name,
        "path": item.path,
        "version": item.version,
        "source": item.source.value,
        "is_default": item.is_default,
        "is_compatible": item.is_compatible,
        "compatibility_notes": list(item.compatibility_notes),
        "capabilities": {
            "can_execute": item.capabilities.can_execute,
            "can_package_check": item.capabilities.can_package_check,
            "supports_stdin_source": item.capabilities.supports_stdin_source,
            "supports_tempfile_source": item.capabilities.supports_tempfile_source,
            "notes": item.capabilities.notes,
        },
        "diagnostics": list(item.diagnostics),
    }
