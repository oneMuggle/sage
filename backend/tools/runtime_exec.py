"""``runtime_exec`` 工具 — 使用指定运行时执行代码。

风险：``EXEC``。运行时代理或用户授权后才允许调用。

安全约束：

- runtime_path 必须经过 ``runtime_validation``；
- cwd 必须位于 workspace_root 内；
- 进程使用参数数组启动，不使用 shell；
- 进程在 ``safe_run`` 中接受超时、输出上限与进程组回收；
- 不注入 SAGE_LOCAL_AUTH_TOKEN 等敏感环境变量。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from backend.domain.risk import RiskClass
from backend.domain.runtime import (
    ExecutionRequest,
    ExecutionResult,
    RuntimeInfo,
)
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.runtime_adapter import AdapterContext, registry
from backend.tools.runtime_safe_run import safe_run
from backend.tools.runtime_validation import (
    RuntimeValidationError,
    validate_code_size,
    validate_cwd,
    validate_env_overrides,
    validate_runtime_path,
    validate_timeout,
)

logger = logging.getLogger(__name__)


class RuntimeExecTool(BaseTool):
    risk = RiskClass.EXEC

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="runtime_exec",
            description=(
                "在指定的运行时（Python 解释器或 Node.js）中执行短代码片段，"
                "返回 stdout / stderr / exit_code。第一版仅支持前台执行。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "language": {
                        "type": "string",
                        "description": "运行时语言（python / javascript 等）",
                    },
                    "runtime_path": {
                        "type": "string",
                        "description": "运行时解释器路径，需先经 runtime_probe 探测",
                    },
                    "code": {
                        "type": "string",
                        "description": "待执行源代码；通过 stdin 传入，避免临时文件",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "工作目录；必须位于 workspace_root 内",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "超时秒数，默认 60，最大 600",
                        "default": 60,
                    },
                    "env_overrides": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": "附加环境变量；不允许覆盖 SAGE_LOCAL_AUTH_TOKEN 等",
                    },
                },
                "required": ["language", "runtime_path", "code"],
            },
        )

    def execute(  # type: ignore[override]
        self,
        *,
        language: str,
        runtime_path: str,
        code: str,
        cwd: Optional[str] = None,
        timeout: Optional[int] = None,
        env_overrides: Optional[Dict[str, str]] = None,
        workspace_root: Optional[str] = None,
        **_kwargs: Any,
    ) -> ToolResult:
        try:
            timeout_s = validate_timeout(timeout)
            env = validate_env_overrides(env_overrides)
            validate_code_size(code)
            workspace = Path(workspace_root) if workspace_root else Path.cwd()
            workspace = workspace.resolve()
            safe_runtime = validate_runtime_path(runtime_path, workspace_root=workspace)
            safe_cwd = validate_cwd(cwd, workspace_root=workspace)
        except RuntimeValidationError as exc:
            return ToolResult(success=False, error=str(exc))

        adapter = registry.get(language)
        if adapter is None:
            return ToolResult(success=False, error=f"未注册的运行时语言: {language}")

        ctx = AdapterContext(workspace_root=workspace, safe_run=safe_run)
        exec_request = ExecutionRequest(
            language=language,
            runtime_path=safe_runtime,
            code=code,
            cwd=safe_cwd,
            timeout=timeout_s,
            run_in_background=False,
            env_overrides=env,
        )
        runtime = RuntimeInfo(
            language=language,
            name=adapter.__class__.__name__,
            path=safe_runtime,
            version="",
        )
        try:
            command = adapter.build_command(exec_request, runtime, ctx)
        except Exception as exc:  # noqa: BLE001
            logger.warning("runtime_exec build_command 失败: %s", exc)
            return ToolResult(success=False, error=f"构造命令失败: {exc}")

        if not command.argv:
            return ToolResult(success=False, error="runtime_exec 命令为空")

        result = safe_run(
            command.argv,
            timeout=float(timeout_s),
            cwd=Path(safe_cwd) if safe_cwd else workspace,
            env=command.env or env or None,
            input_text=command.stdin_payload,
            output_cap=64 * 1024,
        )

        exec_result = ExecutionResult(
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_seconds=result.duration_seconds,
            timed_out=result.timed_out,
            output_truncated=result.output_truncated,
            error=result.error,
            command=list(command.argv),
        )
        return ToolResult(
            success=result.exit_code in (0, None),
            content=exec_result.to_dict(),
        )


__all__ = ["RuntimeExecTool"]
