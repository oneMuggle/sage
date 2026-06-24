"""
终端工具 - 执行 Shell 命令
"""

from __future__ import annotations

import shlex
import subprocess

from .base import BaseTool, ToolResult, ToolSchema


class TerminalTool(BaseTool):
    """
    终端工具 - 执行 Shell 命令

    注意: Windows 7 上建议使用 PowerShell 命令
    """

    # 危险命令黑名单
    DANGEROUS_PATTERNS: list[str] = [
        "rm -rf /",
        "rm -rf /",
        "fork bomb",
        ":(){ :|:& };:",
        "dd if=/dev/zero of=/dev/sda",
        "mkfs.ext4",
        "chmod -R 000 /",
        "> /dev/sda",
        "wget.*curl.*sh",
    ]

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="terminal",
            description="""执行终端命令。
警告: 这是一个强大的工具，请仅在用户明确要求时使用。
注意: Windows 7 上建议使用 PowerShell 命令。""",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的命令"},
                    "cwd": {"type": "string", "description": "工作目录 (可选)"},
                    "timeout": {"type": "number", "description": "超时时间(秒)，默认 30"},
                },
                "required": ["command"],
            },
        )

    def _is_dangerous(self, command: str) -> bool:
        """
        检查命令是否危险

        Args:
            command: 要执行的命令

        Returns:
            是否危险
        """
        command_lower = command.lower()

        # 检查是否包含危险模式
        for pattern in self.DANGEROUS_PATTERNS:
            if pattern.lower() in command_lower:
                return True

        # 检查是否有破坏性的 rm -rf 组合
        if "rm -rf" in command_lower and ("/" in command or "--no-preserve-root" not in command):
            # 允许 rm -rf /tmp 等相对路径
            return True

        return False

    def execute(self, command: str, cwd: str = None, timeout: int = 30, **kwargs) -> ToolResult:
        """
        执行命令

        Args:
            command: 要执行的命令
            cwd: 工作目录
            timeout: 超时时间(秒)

        Returns:
            ToolResult 对象
        """
        # 安全检查
        if self._is_dangerous(command):
            return ToolResult(success=False, error="危险命令被拒绝: 不允许执行可能破坏系统的命令")

        try:
            # 使用 shlex 分割命令（更安全）
            cmd_list = shlex.split(command) if not command.startswith("cmd") else None

            if cmd_list is None:
                # Windows cmd 命令
                result = subprocess.run(
                    command,
                    cwd=cwd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
            else:
                # Unix 命令
                result = subprocess.run(
                    cmd_list, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
                )

            success = result.returncode == 0
            error = result.stderr if not success else None

            return ToolResult(
                success=success,
                content={
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
                if success
                else None,
                error=error,
            )

        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error=f"命令执行超时 ({timeout}秒)")
        except Exception as e:
            return ToolResult(success=False, error=f"执行错误: {str(e)}")
