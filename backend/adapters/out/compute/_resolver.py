"""可执行文件路径解析器（``ExecutableResolver``）。

为 ``SubprocessComputeAdapter`` 提供"按优先级查找 ghm 入口"的能力，使
sage 在不同部署形态下零代码切换：

==================  ========================================================
来源                 适用场景
==================  ========================================================
``GHM_EXECUTABLE_PATH``  环境变量临时覆盖（调试 / CI）
``executable_path``      yaml 显式 exe 路径（打包后的用户机器）
``sidecar_name``         Tauri sidecar 解析（**本期预留**，未来桌面分发）
``python_module``        conda ``python -m ghm``（**当前开发**）
``path_lookup_name``     系统 PATH 查找（``shutil.which``）
==================  ========================================================

任一来源命中即返回 ``ResolvedExecutable``；全部失败抛
``ExecutableNotFoundError``。

设计要点
--------

- 不抛非预期异常：所有 IO 检查（``Path.is_file`` / ``os.access`` /
  ``shutil.which``）都是 best-effort，任意来源不存在仅记录到 ``tried``。
- 解析结果在实例内缓存，多次 ``resolve()`` 不重复查询文件系统。
- 不引入任何外部依赖（仅 stdlib），符合 adapters 层约定。
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ResolvedExecutable:
    """一个被解析出来的可执行文件 + 必要的执行环境。

    Attributes:
        argv_prefix:  作为 ``asyncio.create_subprocess_exec`` 第一个参数集合
                      传入。例：``["/path/to/ghm-cli"]`` 或
                      ``["/.../bin/python", "-m", "ghm"]``。
        working_dir:  子进程 cwd（None 表示继承父进程）。
        env:          子进程额外环境变量（None 表示仅继承父进程 env）。
        source:       解析来源标记（``"executable_path"`` / ``"python_module"``
                      等），用于审计 / 日志。
    """

    argv_prefix: list[str]
    working_dir: str | None = None
    env: dict[str, str] | None = None
    source: str = ""


class ExecutableNotFoundError(RuntimeError):
    """所有解析途径都失败时抛出。

    Attributes:
        tried:  按顺序尝试过的来源描述（便于诊断 yaml 配置错误）。
    """

    def __init__(self, tried: list[str]) -> None:
        super().__init__(f"ghm executable not found. Tried: {tried}")
        self.tried = list(tried)


# 环境变量名（最高优先级）
_ENV_OVERRIDE = "GHM_EXECUTABLE_PATH"


@dataclass
class ExecutableResolver:
    """按优先级解析 ghm 可执行文件入口。

    Args:
        config:  ``backend/config/ghm.yaml`` 中 ``ghm.subprocess`` 段的字典。
                 缺失字段按 ``None`` 跳过；详见模块 docstring。
    """

    config: dict[str, Any] = field(default_factory=dict)
    _cached: ResolvedExecutable | None = field(default=None, init=False, repr=False)

    def resolve(self) -> ResolvedExecutable:
        """按优先级查找并返回首个可用入口。多次调用使用缓存。

        Raises:
            ExecutableNotFoundError: 所有来源均不可用。
        """
        if self._cached is not None:
            return self._cached

        tried: list[str] = []

        # 1) 显式 exe 路径（env 覆盖优先于 yaml）
        exe = os.environ.get(_ENV_OVERRIDE) or self.config.get("executable_path")
        if exe:
            tried.append(f"executable_path={exe}")
            if _is_executable(exe):
                self._cached = ResolvedExecutable(
                    argv_prefix=[str(exe)],
                    source="executable_path",
                )
                return self._cached

        # 2) Tauri sidecar（本期未实现）
        sidecar_name = self.config.get("sidecar_name")
        if sidecar_name:
            tried.append(f"sidecar={sidecar_name}")
            # TODO(future): 与 Tauri 协作约定 sidecar 路径后启用，
            # 例如 src-tauri/binaries/{sidecar_name}-{target-triple}{ext}

        # 3) python_module 开发回退
        pm = self.config.get("python_module")
        if isinstance(pm, dict):
            py = pm.get("python")
            mod = pm.get("module") or "ghm"
            tried.append(f"python_module={py} -m {mod}")
            if py and _is_executable(py):
                self._cached = ResolvedExecutable(
                    argv_prefix=[str(py), "-m", str(mod)],
                    working_dir=pm.get("working_dir"),
                    source="python_module",
                )
                return self._cached

        # 4) 系统 PATH 查找
        lookup = self.config.get("path_lookup_name") or "ghm-cli"
        tried.append(f"shutil.which={lookup}")
        found = shutil.which(lookup)
        if found:
            self._cached = ResolvedExecutable(
                argv_prefix=[found],
                source="path_lookup",
            )
            return self._cached

        raise ExecutableNotFoundError(tried)

    def invalidate(self) -> None:
        """清空缓存（仅供测试 / 配置热重载使用）。"""
        self._cached = None


def _is_executable(path: str | os.PathLike[str]) -> bool:
    """``True`` iff path 存在、是文件且当前用户具备执行权限。"""
    try:
        p = Path(path)
    except (TypeError, ValueError):
        return False
    return p.is_file() and os.access(p, os.X_OK)
