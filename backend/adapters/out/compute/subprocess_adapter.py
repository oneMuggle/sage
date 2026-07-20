"""``SubprocessComputeAdapter`` — 通过 subprocess CLI 调用 ghm 计算。

设计目标：

- 使用 ``ExecutableResolver`` 解析 ghm 入口（exe / python -m / PATH 等),调用方
  无需关心 sage 部署形态(开发期 conda vs. 用户期独立 exe)。
- 严格白名单:仅允许 ``ghm.yaml`` 中声明的 operations,禁止任意命令拼接。
- 所有错误统一收敛为 ``ComputeResult(success=False, error=...)``,**永不抛异常**。
- 超时强制 kill 子进程并 ``await proc.wait()`` 防泄漏。
- 退出码语义化映射(参考 ghm ``src/ghm/__main__.py:8-12``):

    +-------+-------------------------------+
    | 0     | 成功                          |
    | 1     | PROCESS_FAILED(计算异常)      |
    | 2     | INVALID_PARAMS(argparse)      |
    | 3     | PROCESS_FAILED(缺可选依赖)    |
    +-------+-------------------------------+

签名遵循 ``backend.ports.compute.ComputePort``(结构性类型)。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Dict, List

from sage_core import (
    ComputeError,
    ComputeErrorType,
    ComputeRequest,
    ComputeResult,
    ComputeSpec,
)
from sage_core.repositories import ComputePort  # noqa: F401  (structural typing target)

from backend.adapters.out.compute._resolver import (
    ExecutableNotFoundError,
    ExecutableResolver,
    ResolvedExecutable,
)

logger = logging.getLogger(__name__)

# 默认单次超时
_DEFAULT_TIMEOUT_S = 30


@dataclass
class _OperationDef:
    """yaml 中单个 operation 的内部表示。"""

    name: str
    cli_subcommand: List[str]
    description: str
    params_schema: Dict[str, Any] = field(default_factory=dict)


class SubprocessComputeAdapter:
    """``ComputePort`` 的 subprocess CLI 实现。

    Args:
        config:  ``backend/config/ghm.yaml`` 中 ``ghm`` 段(含 ``subprocess`` /
                 ``operations`` 等子键)。

    用法::

        import yaml
        from pathlib import Path
        cfg = yaml.safe_load(Path("backend/config/ghm.yaml").read_text())["ghm"]
        adapter = SubprocessComputeAdapter(cfg)
        ops = adapter.list_operations()
        result = await adapter.execute(ComputeRequest(operation="compute_shock",
                                                      params={"mach": 6.5, ...}))
    """

    def __init__(self, config: Dict[str, Any]):
        self._config = config
        self._timeout_s = int(config.get("timeout_seconds", _DEFAULT_TIMEOUT_S))
        self._operations: Dict[str, _OperationDef] = {}
        for raw in config.get("operations", []):
            op = _OperationDef(
                name=str(raw["name"]),
                cli_subcommand=list(raw.get("cli_subcommand", [])),
                description=str(raw.get("description", "")),
                params_schema=dict(raw.get("params_schema", {})),
            )
            self._operations[op.name] = op

        self._resolver = ExecutableResolver(config=config.get("subprocess", {}))

    # ---- ComputePort 实现 ----

    def list_operations(self) -> List[ComputeSpec]:
        """返回 yaml 中声明的全部 operations 的 spec 视图。"""
        return [
            ComputeSpec(
                name=op.name,
                description=op.description,
                params_schema=dict(op.params_schema),
            )
            for op in self._operations.values()
        ]

    async def execute(self, req: ComputeRequest) -> ComputeResult:
        """按 yaml 声明执行单次 ghm CLI 调用。"""
        op = self._operations.get(req.operation)
        if op is None:
            return ComputeResult(
                success=False,
                error=ComputeError(
                    type=ComputeErrorType.OPERATION_NOT_FOUND,
                    message=f"unknown operation: {req.operation}",
                ),
            )

        # 解析可执行文件
        try:
            resolved = self._resolver.resolve()
        except ExecutableNotFoundError as exc:
            return ComputeResult(
                success=False,
                error=ComputeError(
                    type=ComputeErrorType.INTERNAL_ERROR,
                    message=str(exc),
                    details={"tried": list(exc.tried)},
                ),
            )

        # 拼 argv:resolver 前缀 + subcommand + params + --json
        argv = self._build_argv(resolved, op, req.params)

        timeout_s = req.timeout_ms / 1000 if req.timeout_ms is not None else self._timeout_s

        start = monotonic()
        try:
            return await self._run_subprocess(argv, resolved, timeout_s, start)
        except Exception as exc:  # noqa: BLE001  — 按 ComputePort 约定不抛
            logger.exception("compute.subprocess unexpected error op=%s", req.operation)
            return ComputeResult(
                success=False,
                duration_ms=int((monotonic() - start) * 1000),
                error=ComputeError(
                    type=ComputeErrorType.INTERNAL_ERROR,
                    message=f"{type(exc).__name__}: {exc}",
                ),
            )

    # ---- 内部辅助 ----

    @staticmethod
    def _build_argv(
        resolved: ResolvedExecutable,
        op: _OperationDef,
        params: Dict[str, Any],
    ) -> List[str]:
        """拼出最终 argv 列表。"""
        argv: List[str] = list(resolved.argv_prefix)
        argv.extend(op.cli_subcommand)
        argv.extend(_params_to_args(params, op.params_schema))
        argv.append("--json")
        return argv

    async def _run_subprocess(
        self,
        argv: List[str],
        resolved: ResolvedExecutable,
        timeout_s: float,
        start: float,
    ) -> ComputeResult:
        """执行 subprocess 并解析结果。"""
        # 子进程环境:父 env + resolver 额外 env
        env = dict(os.environ)
        if resolved.env:
            env.update(resolved.env)

        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=resolved.working_dir,
            env=env,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_s,
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return ComputeResult(
                success=False,
                duration_ms=int((monotonic() - start) * 1000),
                error=ComputeError(
                    type=ComputeErrorType.TIMEOUT,
                    message=f"timeout after {timeout_s}s",
                ),
            )

        duration_ms = int((monotonic() - start) * 1000)
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        return_code = proc.returncode if proc.returncode is not None else -1

        if return_code == 0:
            return _parse_success(stdout, stderr, duration_ms)
        return _parse_failure(return_code, stdout, stderr, duration_ms)


# ---------- 辅助函数(模块级,便于单测覆盖) ----------


def _params_to_args(params: Dict[str, Any], schema: Dict[str, Any]) -> List[str]:
    """把 params dict 翻译为 CLI flag 列表。

    规则:
    - 字段名按 ``snake_case → kebab-case`` 转 flag(如 ``area_ratio`` → ``--area-ratio``)
    - boolean 字段为 ``True`` 时仅追加 flag(无值),``False`` 时跳过
    - 列表字段按 ``nargs="*"`` 风格展开多个值(如 ``--config k1=v1 k2=v2``)
    - 其他类型一律 ``str(val)`` 序列化
    - schema 仅用于查询 ``type``,不做强校验(实际校验由 ghm CLI 完成)
    """
    out: List[str] = []
    props = schema.get("properties", {}) if isinstance(schema, dict) else {}

    for key, val in params.items():
        field_schema = props.get(key, {}) if isinstance(props, dict) else {}
        flag = f"--{key.replace('_', '-')}"
        field_type = field_schema.get("type") if isinstance(field_schema, dict) else None

        if field_type == "boolean":
            if val:
                out.append(flag)
            continue
        if isinstance(val, (list, tuple)):
            if not val:
                continue
            out.append(flag)
            out.extend(str(item) for item in val)
            continue
        out.extend([flag, str(val)])

    return out


def _parse_success(stdout: str, stderr: str, duration_ms: int) -> ComputeResult:
    """退出码 0 → 尝试解析 stdout 为 JSON。"""
    try:
        output = json.loads(stdout) if stdout.strip() else {}
    except json.JSONDecodeError as exc:
        return ComputeResult(
            success=False,
            raw_stdout=stdout,
            raw_stderr=stderr,
            exit_code=0,
            duration_ms=duration_ms,
            error=ComputeError(
                type=ComputeErrorType.OUTPUT_PARSE_ERROR,
                message=f"stdout not valid JSON: {exc}",
            ),
        )

    if not isinstance(output, dict):
        return ComputeResult(
            success=False,
            raw_stdout=stdout,
            raw_stderr=stderr,
            exit_code=0,
            duration_ms=duration_ms,
            error=ComputeError(
                type=ComputeErrorType.OUTPUT_PARSE_ERROR,
                message=f"stdout must be a JSON object, got {type(output).__name__}",
            ),
        )

    return ComputeResult(
        success=True,
        output=output,
        raw_stdout=stdout,
        exit_code=0,
        duration_ms=duration_ms,
    )


def _parse_failure(
    return_code: int,
    stdout: str,
    stderr: str,
    duration_ms: int,
) -> ComputeResult:
    """非零退出码 → 按 ghm 约定映射到 ComputeErrorType。

    参考 ghm ``src/ghm/__main__.py:8-12``:
    - 1 → 计算异常       → PROCESS_FAILED
    - 2 → argparse 错误  → INVALID_PARAMS
    - 3 → 缺可选依赖     → PROCESS_FAILED
    - 其他               → PROCESS_FAILED
    """
    if return_code == 2:
        err_type = ComputeErrorType.INVALID_PARAMS
    else:
        err_type = ComputeErrorType.PROCESS_FAILED

    message = stderr.strip() or stdout.strip() or f"exit code {return_code}"
    return ComputeResult(
        success=False,
        raw_stdout=stdout,
        raw_stderr=stderr,
        exit_code=return_code,
        duration_ms=duration_ms,
        error=ComputeError(
            type=err_type,
            message=message,
            details={"exit_code": return_code},
        ),
    )
