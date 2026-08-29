"""bash 工具 —— 执行 shell 命令（对齐 Claude Code Bash tool）。

与被它取代的 ``TerminalTool`` 的关键差别：**不在工具内做危险命令拦截**。
旧实现拒绝一切含 shell 操作符（``| && ; > $()``）的命令，把安全性换成了
几乎不可用——``ls | head`` 这种命令都跑不了。

危险判定现在只有一处来源：``backend.tools.bash_validation.validate_bash``
的三档风险 + ``PermissionEnforcer`` 的模式矩阵与审批闸口。那条链比旧的
子串黑名单更严——DESTRUCTIVE 命令即使在 ``full_access`` 模式、即使有
显式 allow 规则也强制走用户确认。

其余设计要点：

- 输出走临时文件并只读前 30 KiB（父进程内存有界，见 ``subprocess_util``）
- ``start_new_session=True`` + 超时杀进程组（连孙进程）
- shell 由 ``shell_resolver`` 探测；Windows 无 bash 时降级 PowerShell 并
  在结果里标注，让模型知道 bash 语法可能不适用
- **cwd 无状态**：每次调用可传，不跨调用记忆。工具实例可能被主 agent 与
  ``AgentTool`` 派生的子代理共享，持久化 cwd 会让一方 ``cd`` 静默改变另一方
  的视角，且该状态不出现在审批摘要里。模型要切目录直接写 ``cd x && ...``。
- 命令非零退出仍 ``success=True``：模型需要看到 stderr 自行纠错，把编译
  失败当成工具故障会让它无法诊断。
- **后台会话上限 32**：超出后 ``bash(run_in_background=true)`` 返回明确错误
  并提示 ``kill_shell``；绝不静默丢弃 spawn 请求。
- **后台进程登记失败必须回收**：预检查 + 注册之间存在并发竞态，注册失败
  时由 ``_run_background`` 显式 ``kill_process_tree + unlink_owned``，
  避免孤儿进程与泄漏临时文件。
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from backend.domain.risk import RiskClass

from .base import BaseTool, ToolResult, ToolSchema
from .bash_session import (
    MAX_BACKGROUND_SESSIONS,
    STATUS_RUNNING,
    SessionLimitExceeded,
    get_registry,
)
from .shell_resolver import SHELL_FALLBACK_NOTE, ShellSpec, resolve_shell
from .subprocess_util import (
    VerifiedProcess,
    file_identity,
    kill_process_tree,
    make_temp_output_file,
    read_capped_output,
    spawn_verified,
    unlink_owned,
    unlink_quietly,
)

logger = logging.getLogger(__name__)

BASH_DEFAULT_TIMEOUT_SECONDS = 120.0
BASH_MIN_TIMEOUT_SECONDS = 1.0
BASH_MAX_TIMEOUT_SECONDS = 600.0

#: stdout / stderr 各自的输出截断上限（30 KiB）
BASH_MAX_OUTPUT_BYTES = 30 * 1024

_TEMP_PREFIX = "sage_bash_"


def clamp_bash_timeout(value: float) -> float:
    """把超时夹到 ``[BASH_MIN, BASH_MAX]`` 区间。"""
    return min(max(float(value), BASH_MIN_TIMEOUT_SECONDS), BASH_MAX_TIMEOUT_SECONDS)


class BashTool(BaseTool):
    """在 shell 中执行命令（同步或后台）。"""

    risk = RiskClass.EXEC

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="bash",
            description=(
                "在 shell 中执行命令并返回 stdout/stderr/exit_code。"
                "支持完整 shell 语法：管道 |、串联 && ||、重定向 > >>、命令替换 $()。"
                "需要切换目录时写 `cd <dir> && <command>`（cwd 参数不跨调用保留）。"
                f"默认超时 {BASH_DEFAULT_TIMEOUT_SECONDS:.0f} 秒"
                f"（上限 {BASH_MAX_TIMEOUT_SECONDS:.0f}）。"
                "长时间运行的命令（开发服务器、watch 模式）设 run_in_background=true，"
                "用 bash_output 读取输出、kill_shell 结束。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的 shell 命令"},
                    "cwd": {
                        "type": "string",
                        "description": "工作目录（可选，默认工作区根目录；不跨调用保留）",
                    },
                    "timeout": {
                        "type": "number",
                        "description": (
                            f"超时秒数（默认 {BASH_DEFAULT_TIMEOUT_SECONDS:.0f}，"
                            f"上限 {BASH_MAX_TIMEOUT_SECONDS:.0f}；后台执行时忽略）"
                        ),
                    },
                    "run_in_background": {
                        "type": "boolean",
                        "description": "true 则立即返回 shell_id，不等待命令结束",
                    },
                },
                "required": ["command"],
            },
        )

    def execute(
        self,
        command: str = "",
        cwd: Optional[str] = None,
        timeout: float = BASH_DEFAULT_TIMEOUT_SECONDS,
        run_in_background: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        """执行命令。

        Returns:
            同步：``content`` 含 ``exit_code`` / ``stdout`` / ``stderr`` /
            ``duration_seconds`` / ``truncated`` / ``shell`` / ``cwd``。
            命令非零退出仍 ``success=True``；超时或启动失败 ``success=False``。
            后台：``content`` 含 ``shell_id`` / ``command`` / ``status="running"``。
        """
        if kwargs:
            names = ", ".join(sorted(kwargs))
            return ToolResult(
                success=False,
                error=(
                    f"未知参数: {names}"
                    "（合法参数: command, cwd, timeout, run_in_background）"
                ),
            )
        if not isinstance(command, str) or not command.strip():
            return ToolResult(success=False, error="command 不能为空")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):  # noqa: UP038 — py3.8 不支持 X | Y isinstance
            return ToolResult(success=False, error="timeout 必须是数字")

        resolved_cwd, rejection = self._resolve_cwd(cwd)
        if rejection is not None:
            return rejection

        shell = resolve_shell()
        if run_in_background:
            return self._run_background(command, resolved_cwd, shell)
        return self._run_foreground(command, resolved_cwd, shell, clamp_bash_timeout(timeout))

    def _resolve_cwd(self, cwd: Optional[str]) -> Tuple[Optional[str], Optional[ToolResult]]:
        """确定工作目录；越界返回拒绝结果。

        显式传入的 cwd 走 workspace 守卫；未传时用 ``policy.workspace_root``
        （已在边界内，无需再校验），未绑定 workspace 则返回 ``None``
        让 ``Popen`` 继承进程 cwd。
        """
        if cwd is None:
            return self._policy.workspace_root, None
        guard = self._enforce_workspace(cwd)
        if guard is not None:
            return None, guard
        return cwd, None

    def _decorate(self, content: Dict[str, Any], shell: ShellSpec, cwd: Optional[str]) -> Dict[str, Any]:
        """给结果补上执行环境元数据。"""
        content["shell"] = shell.kind
        content["cwd"] = cwd or str(Path.cwd())
        if shell.is_fallback:
            content["shell_fallback"] = SHELL_FALLBACK_NOTE
        return content

    def _spawn(
        self, command: str, cwd: Optional[str], shell: ShellSpec
    ) -> Tuple[VerifiedProcess, str, str]:
        """启动子进程，输出重定向到临时文件。

        返回 ``(VerifiedProcess, stdout 路径, stderr 路径)`` —— 进程组 ID
        已被 spawn_verified 验证 ``pgid == pid``，调用方把它传给
        ``kill_process_tree`` 才能正确终止孙进程。
        临时文件的所有权与生命周期由调用方负责：成功路径走 ``unlink_quietly``
        （前景）/ ``registry.register`` 后由 ``terminate`` 清理（后台）；
        启动失败由 ``finally`` 内显式 ``unlink_quietly`` 回收。
        """
        stdout_path = make_temp_output_file(prefix=_TEMP_PREFIX)
        stderr_path = make_temp_output_file(prefix=_TEMP_PREFIX)
        # 刻意不用 with：句柄要跨越 Popen 存活，启动后立即关闭（子进程已继承 fd）
        out_handle = open(stdout_path, "wb")  # noqa: SIM115
        err_handle = open(stderr_path, "wb")  # noqa: SIM115
        try:
            verified = spawn_verified(
                [shell.executable, *shell.args_prefix, command],
                cwd=cwd,
                stdout=out_handle,
                stderr=err_handle,
            )
        except Exception:
            unlink_quietly(stdout_path)
            unlink_quietly(stderr_path)
            raise
        finally:
            out_handle.close()
            err_handle.close()
        return verified, stdout_path, stderr_path

    def _run_foreground(
        self, command: str, cwd: Optional[str], shell: ShellSpec, timeout: float
    ) -> ToolResult:
        started = time.monotonic()
        try:
            verified, stdout_path, stderr_path = self._spawn(command, cwd, shell)
        except Exception as exc:
            return ToolResult(success=False, error=f"shell 子进程启动失败: {exc}")
        process = verified.process
        process_group_id = verified.process_group_id

        try:
            timed_out = False
            try:
                # stdout/stderr 都重定向到文件 → communicate 返回 (None, None)，
                # 只借它做"等待 + 超时"语义；退出码走 process.returncode
                process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                # 必须传已验证的进程组 ID；否则 kill_process_tree 拒绝信号并返回 False。
                kill_process_tree(
                    process, reap=True, process_group_id=process_group_id
                )

            duration = time.monotonic() - started
            if timed_out:
                return ToolResult(
                    success=False,
                    error=f"命令执行超时（{timeout:g} 秒），子进程组已被终止",
                )

            stdout, out_truncated, _ = read_capped_output(stdout_path, cap=BASH_MAX_OUTPUT_BYTES)
            stderr, err_truncated, _ = read_capped_output(stderr_path, cap=BASH_MAX_OUTPUT_BYTES)
            return ToolResult(
                success=True,
                content=self._decorate(
                    {
                        "exit_code": process.returncode,
                        "stdout": stdout,
                        "stderr": stderr,
                        "duration_seconds": round(duration, 3),
                        "truncated": out_truncated or err_truncated,
                    },
                    shell,
                    cwd,
                ),
            )
        finally:
            unlink_quietly(stdout_path)
            unlink_quietly(stderr_path)

    def _run_background(
        self, command: str, cwd: Optional[str], shell: ShellSpec
    ) -> ToolResult:
        """启动后台 shell 并登记，立即返回 shell_id。

        后台进程**不受 timeout 约束**——这正是它存在的理由（开发服务器、
        watch 模式）。生命周期由 ``bash_output`` / ``kill_shell`` 管理。
        """
        registry = get_registry()
        if registry.count() >= MAX_BACKGROUND_SESSIONS:
            return ToolResult(
                success=False,
                error=(
                    f"后台 shell 数已达上限 {MAX_BACKGROUND_SESSIONS}，"
                    "请先用 kill_shell 结束不需要的会话"
                ),
            )
        try:
            verified, stdout_path, stderr_path = self._spawn(command, cwd, shell)
        except Exception as exc:
            return ToolResult(success=False, error=f"shell 子进程启动失败: {exc}")
        process = verified.process
        process_group_id = verified.process_group_id

        try:
            session = registry.register(verified, command, stdout_path, stderr_path)
        except SessionLimitExceeded as exc:
            # 预检查与注册之间存在竞态窗口（并发 spawn）：注册失败时必须回收
            # 已起的进程 + 临时文件，否则留下孤儿进程 + 泄漏的临时文件。
            self._cleanup_failed_background(
                process, process_group_id, stdout_path, stderr_path
            )
            return ToolResult(success=False, error=str(exc))

        return ToolResult(
            success=True,
            content=self._decorate(
                {
                    "shell_id": session.shell_id,
                    "command": command,
                    "status": STATUS_RUNNING,
                },
                shell,
                cwd,
            ),
        )

    @staticmethod
    def _cleanup_failed_background(
        process: subprocess.Popen[bytes],
        process_group_id: int,
        stdout_path: str,
        stderr_path: str,
    ) -> None:
        """注册失败的孤儿回收：杀进程组 + 用 identity 删除临时文件。"""
        stdout_identity = file_identity(stdout_path)
        stderr_identity = file_identity(stderr_path)
        kill_process_tree(
            process,
            reap=False,
            process_group_id=process_group_id,
        )
        unlink_owned(stdout_path, stdout_identity)
        unlink_owned(stderr_path, stderr_identity)


class BashOutputTool(BaseTool):
    """读取后台 shell 自上次读取以来的新增输出。"""

    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="bash_output",
            description=(
                "读取后台 shell（bash 工具 run_in_background=true 启动）的新增输出。"
                "每次调用只返回上次读取之后的增量，并报告 status "
                "（running / exited）与 exit_code。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "shell_id": {
                        "type": "string",
                        "description": "bash 后台执行返回的 shell_id",
                    },
                },
                "required": ["shell_id"],
            },
        )

    def execute(self, shell_id: str = "", **kwargs: Any) -> ToolResult:
        if kwargs:
            names = ", ".join(sorted(kwargs))
            return ToolResult(success=False, error=f"未知参数: {names}（合法参数: shell_id）")
        if not isinstance(shell_id, str) or not shell_id.strip():
            return ToolResult(success=False, error="shell_id 不能为空")

        payload = get_registry().read_increment(shell_id, cap=BASH_MAX_OUTPUT_BYTES)
        if payload is None:
            return ToolResult(
                success=False,
                error=f"未知 shell_id: {shell_id}（会话不存在或已被 kill_shell 结束）",
            )
        return ToolResult(success=True, content=payload)


class KillShellTool(BaseTool):
    """终止后台 shell 并清理其资源。"""

    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="kill_shell",
            description=(
                "终止后台 shell（bash 工具 run_in_background=true 启动）"
                "并返回其残余输出。已结束的会话调用此工具等价于收尾清理。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "shell_id": {
                        "type": "string",
                        "description": "bash 后台执行返回的 shell_id",
                    },
                },
                "required": ["shell_id"],
            },
        )

    def execute(self, shell_id: str = "", **kwargs: Any) -> ToolResult:
        if kwargs:
            names = ", ".join(sorted(kwargs))
            return ToolResult(success=False, error=f"未知参数: {names}（合法参数: shell_id）")
        if not isinstance(shell_id, str) or not shell_id.strip():
            return ToolResult(success=False, error="shell_id 不能为空")

        payload = get_registry().terminate(shell_id, cap=BASH_MAX_OUTPUT_BYTES)
        if payload is None:
            return ToolResult(
                success=False,
                error=f"未知 shell_id: {shell_id}（会话不存在或已被 kill_shell 结束）",
            )
        return ToolResult(success=True, content=payload)


__all__ = [
    "BASH_DEFAULT_TIMEOUT_SECONDS",
    "BASH_MIN_TIMEOUT_SECONDS",
    "BASH_MAX_TIMEOUT_SECONDS",
    "BASH_MAX_OUTPUT_BYTES",
    "BashTool",
    "BashOutputTool",
    "KillShellTool",
    "clamp_bash_timeout",
]
